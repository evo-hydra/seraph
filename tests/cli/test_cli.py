"""Tests for CLI app."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from verdict.cli.app import app
from verdict.core.store import VerdictStore
from verdict.models.assessment import AssessmentReport
from verdict.models.enums import Grade

runner = CliRunner()


class TestCLI:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Verification intelligence" in result.stdout or "Usage" in result.stdout

    def test_history_empty(self, tmp_path):
        # Create a .verdict dir with an empty store
        store = VerdictStore(tmp_path / ".verdict" / "verdict.db")
        store.open()
        store.close()

        result = runner.invoke(app, ["history", str(tmp_path)])
        assert result.exit_code == 0
        assert "No assessments" in result.stdout

    def test_history_with_data(self, tmp_path):
        store = VerdictStore(tmp_path / ".verdict" / "verdict.db")
        store.open()
        report = AssessmentReport(
            repo_path=str(tmp_path),
            files_changed=["foo.py"],
            overall_score=85.0,
            overall_grade=Grade.B,
            mutation_score=90.0,
            static_issues=1,
        )
        store.save_assessment(report)
        store.close()

        result = runner.invoke(app, ["history", str(tmp_path)])
        assert result.exit_code == 0

    def test_feedback_invalid_outcome(self, tmp_path):
        store = VerdictStore(tmp_path / ".verdict" / "verdict.db")
        store.open()
        store.close()

        result = runner.invoke(app, ["feedback", "abc123", "invalid", "--repo", str(tmp_path)])
        assert result.exit_code == 1

    def test_feedback_missing_assessment(self, tmp_path):
        store = VerdictStore(tmp_path / ".verdict" / "verdict.db")
        store.open()
        store.close()

        result = runner.invoke(app, ["feedback", "nonexistent", "accepted", "--repo", str(tmp_path)])
        assert result.exit_code == 1
