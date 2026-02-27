"""Tests for SeraphEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from seraph.config import SeraphConfig, TimeoutConfig, ScoringConfig
from seraph.core.differ import DiffResult, FileChange
from seraph.core.engine import SeraphEngine
from seraph.core.store import SeraphStore
from seraph.models.assessment import MutationResult, BaselineResult
from seraph.models.enums import Grade, MutantStatus


class TestSeraphEngine:
    def test_empty_diff_returns_perfect(self, store: SeraphStore, tmp_repo: Path):
        engine = SeraphEngine(store, skip_baseline=True, skip_mutations=True)
        report = engine.assess(tmp_repo)
        assert report.overall_grade == Grade.A
        assert report.overall_score == 100.0
        assert report.files_changed == []

    def test_empty_diff_is_persisted(self, store: SeraphStore, tmp_repo: Path):
        engine = SeraphEngine(store, skip_baseline=True, skip_mutations=True)
        report = engine.assess(tmp_repo)
        saved = store.get_assessment(report.id)
        assert saved is not None

    @patch("seraph.core.engine.run_static_analysis")
    @patch("seraph.core.engine.run_mutations")
    @patch("seraph.core.engine.run_baseline")
    @patch("seraph.core.engine.parse_diff")
    def test_full_pipeline(
        self, mock_diff, mock_baseline, mock_mutate, mock_static,
        store: SeraphStore, tmp_repo: Path
    ):
        mock_diff.return_value = DiffResult(
            files=[FileChange(path="src/foo.py")],
        )
        mock_baseline.return_value = BaselineResult(
            repo_path=str(tmp_repo),
            flaky_tests=[],
            pass_rate=1.0,
        )
        mock_mutate.return_value = [
            MutationResult(file_path="src/foo.py", status=MutantStatus.KILLED),
        ]
        mock_static.return_value = []

        engine = SeraphEngine(store)
        report = engine.assess(tmp_repo)

        assert report.files_changed == ["src/foo.py"]
        assert report.overall_grade == Grade.A

        # All dimensions should be evaluated
        evaluated = [d for d in report.dimensions if d.evaluated]
        assert len(evaluated) == 5

        # Verify persisted
        saved = store.get_assessment(report.id)
        assert saved is not None

    def test_skip_baseline_and_mutations(self, store: SeraphStore, tmp_repo: Path):
        from tests.conftest import _git

        # Add a file change
        (tmp_repo / "new.py").write_text("x = 1\n")
        _git(tmp_repo, "add", "new.py")
        _git(tmp_repo, "commit", "-q", "-m", "add new")

        engine = SeraphEngine(store, skip_baseline=True, skip_mutations=True)
        report = engine.assess(tmp_repo, ref_before="HEAD~1")

        assert "new.py" in report.files_changed
        assert report.mutation_score == 100.0  # Skipped = perfect

        # Baseline and mutation should NOT be evaluated
        evaluated_names = {d.name for d in report.dimensions if d.evaluated}
        assert "Mutation Score" not in evaluated_names
        assert "Test Baseline" not in evaluated_names
        # Static, sentinel, co-change should still be evaluated
        assert "Static Cleanliness" in evaluated_names
        assert "Sentinel Risk" in evaluated_names
        assert "Co-change Coverage" in evaluated_names

    @patch("seraph.core.engine.run_static_analysis")
    @patch("seraph.core.engine.parse_diff")
    def test_non_python_only_skips_heavy_steps(
        self, mock_diff, mock_static,
        store: SeraphStore, tmp_repo: Path
    ):
        """Only non-Python files changed: baseline, mutation, static are skipped."""
        mock_diff.return_value = DiffResult(
            files=[FileChange(path="README.md")],
        )

        engine = SeraphEngine(store, skip_baseline=False, skip_mutations=False)
        report = engine.assess(tmp_repo)

        assert report.files_changed == ["README.md"]
        # Static analysis should not have been called (no py_files)
        mock_static.assert_not_called()
        # Baseline and mutation not evaluated (no py_files)
        evaluated_names = {d.name for d in report.dimensions if d.evaluated}
        assert "Mutation Score" not in evaluated_names
        assert "Test Baseline" not in evaluated_names

    @patch("seraph.core.engine.run_mutations")
    @patch("seraph.core.engine.parse_diff")
    def test_mutate_only(self, mock_diff, mock_mutate, store: SeraphStore, tmp_repo: Path):
        mock_diff.return_value = DiffResult(
            files=[FileChange(path="foo.py")],
        )
        mock_mutate.return_value = [
            MutationResult(status=MutantStatus.KILLED),
            MutationResult(status=MutantStatus.SURVIVED),
        ]

        engine = SeraphEngine(store)
        report = engine.mutate_only(tmp_repo)

        assert report.mutation_score == 50.0

        # Only mutation dimension should be evaluated
        evaluated = [d for d in report.dimensions if d.evaluated]
        assert len(evaluated) == 1
        assert evaluated[0].name == "Mutation Score"

    def test_engine_accepts_config(self, store: SeraphStore, tmp_repo: Path):
        """SeraphEngine works with a custom SeraphConfig."""
        config = SeraphConfig(
            timeouts=TimeoutConfig(mutation_per_file=60, static_analysis=30),
            scoring=ScoringConfig(mutation_weight=0.50, static_weight=0.10),
        )
        engine = SeraphEngine(store, config=config, skip_baseline=True, skip_mutations=True)
        report = engine.assess(tmp_repo)
        # Should still work (empty diff = grade A)
        assert report.overall_grade == Grade.A

    @patch("seraph.core.engine.run_static_analysis")
    @patch("seraph.core.engine.run_baseline")
    @patch("seraph.core.engine.parse_diff")
    def test_step_failure_doesnt_crash_pipeline(
        self, mock_diff, mock_baseline, mock_static,
        store: SeraphStore, tmp_repo: Path
    ):
        """A single step failure doesn't crash the entire pipeline."""
        mock_diff.return_value = DiffResult(
            files=[FileChange(path="src/foo.py")],
        )
        # Baseline raises, but pipeline should continue
        mock_baseline.side_effect = RuntimeError("baseline boom")
        mock_static.return_value = []

        engine = SeraphEngine(store, skip_mutations=True)
        report = engine.assess(tmp_repo)

        # Pipeline should still produce a report
        assert report is not None
        assert report.overall_grade is not None
        # Baseline should NOT be in evaluated dimensions (since it failed)
        evaluated_names = {d.name for d in report.dimensions if d.evaluated}
        assert "Test Baseline" not in evaluated_names
