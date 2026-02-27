"""Tests for VerdictConfig loading and defaults."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from verdict.config import VerdictConfig, ScoringConfig


class TestVerdictConfig:
    def test_default_config(self):
        """All defaults match current hardcoded values."""
        config = VerdictConfig()
        assert config.timeouts.mutation_per_file == 120
        assert config.timeouts.static_analysis == 60
        assert config.timeouts.baseline_per_run == 120
        assert config.pipeline.baseline_runs == 3
        assert config.pipeline.max_output_chars == 16_000
        assert config.pipeline.db_dir == ".verdict"
        assert config.pipeline.db_name == "verdict.db"
        assert config.retention.retention_days == 90
        assert config.retention.auto_prune is False
        assert config.logging.level == "WARNING"

    def test_load_from_toml(self, tmp_path):
        """Config loads overrides from .verdict/config.toml."""
        config_dir = tmp_path / ".verdict"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            "[timeouts]\n"
            "mutation_per_file = 300\n"
            "static_analysis = 30\n"
            "\n"
            "[scoring]\n"
            "mutation_weight = 0.50\n"
            "static_weight = 0.10\n"
            "\n"
            "[pipeline]\n"
            "baseline_runs = 5\n"
            "\n"
            "[retention]\n"
            "retention_days = 30\n"
        )

        config = VerdictConfig.load(tmp_path)
        assert config.timeouts.mutation_per_file == 300
        assert config.timeouts.static_analysis == 30
        # Non-overridden defaults still hold
        assert config.timeouts.baseline_per_run == 120
        assert config.scoring.mutation_weight == 0.50
        assert config.scoring.static_weight == 0.10
        assert config.pipeline.baseline_runs == 5
        assert config.retention.retention_days == 30

    def test_env_var_override(self, tmp_path):
        """Env vars override defaults."""
        with patch.dict(os.environ, {"VERDICT_TIMEOUT_MUTATION_PER_FILE": "999"}):
            config = VerdictConfig.load(tmp_path)
        assert config.timeouts.mutation_per_file == 999

    def test_env_overrides_toml(self, tmp_path):
        """Env vars take precedence over TOML."""
        config_dir = tmp_path / ".verdict"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            "[timeouts]\n"
            "mutation_per_file = 300\n"
        )
        with patch.dict(os.environ, {"VERDICT_TIMEOUT_MUTATION_PER_FILE": "999"}):
            config = VerdictConfig.load(tmp_path)
        assert config.timeouts.mutation_per_file == 999

    def test_missing_config_file(self, tmp_path):
        """Missing config file returns all defaults."""
        config = VerdictConfig.load(tmp_path)
        assert config == VerdictConfig()

    def test_dimension_weights_sum_to_one(self):
        """Default dimension weights sum to 1.0."""
        scoring = ScoringConfig()
        total = sum(scoring.dimension_weights.values())
        assert abs(total - 1.0) < 1e-9

    def test_frozen_config(self):
        """Config is immutable after creation."""
        config = VerdictConfig()
        with pytest.raises(AttributeError):
            config.timeouts = None  # type: ignore[misc]

    def test_grade_thresholds_property(self):
        """scoring.grade_thresholds returns the correct tuple."""
        scoring = ScoringConfig()
        assert scoring.grade_thresholds == (90.0, 75.0, 60.0, 40.0)

        custom = ScoringConfig(grade_a=95.0, grade_b=80.0, grade_c=65.0, grade_d=50.0)
        assert custom.grade_thresholds == (95.0, 80.0, 65.0, 50.0)
