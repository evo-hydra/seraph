"""Tests for VerdictEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from verdict.core.engine import VerdictEngine
from verdict.core.store import VerdictStore
from verdict.models.assessment import MutationResult, BaselineResult
from verdict.models.enums import Grade, MutantStatus


class TestVerdictEngine:
    def test_empty_diff_returns_perfect(self, store: VerdictStore, tmp_repo: Path):
        engine = VerdictEngine(store, skip_baseline=True, skip_mutations=True)
        report = engine.assess(tmp_repo)
        assert report.overall_grade == Grade.A
        assert report.overall_score == 100.0
        assert report.files_changed == []

    @patch("verdict.core.engine.run_static_analysis")
    @patch("verdict.core.engine.run_mutations")
    @patch("verdict.core.engine.run_baseline")
    @patch("verdict.core.engine.parse_diff")
    def test_full_pipeline(
        self, mock_diff, mock_baseline, mock_mutate, mock_static,
        store: VerdictStore, tmp_repo: Path
    ):
        from verdict.core.differ import DiffResult, FileChange

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

        engine = VerdictEngine(store)
        report = engine.assess(tmp_repo)

        assert report.files_changed == ["src/foo.py"]
        assert report.overall_grade == Grade.A

        # Verify persisted
        saved = store.get_assessment(report.id)
        assert saved is not None

    def test_skip_baseline_and_mutations(self, store: VerdictStore, tmp_repo: Path):
        from tests.conftest import _git

        # Add a file change
        (tmp_repo / "new.py").write_text("x = 1\n")
        _git(tmp_repo, "add", "new.py")
        _git(tmp_repo, "commit", "-q", "-m", "add new")

        engine = VerdictEngine(store, skip_baseline=True, skip_mutations=True)
        report = engine.assess(tmp_repo, ref_before="HEAD~1")

        assert "new.py" in report.files_changed
        assert report.mutation_score == 100.0  # Skipped = perfect

    @patch("verdict.core.engine.run_mutations")
    @patch("verdict.core.engine.parse_diff")
    def test_mutate_only(self, mock_diff, mock_mutate, store: VerdictStore, tmp_repo: Path):
        from verdict.core.differ import DiffResult, FileChange

        mock_diff.return_value = DiffResult(
            files=[FileChange(path="foo.py")],
        )
        mock_mutate.return_value = [
            MutationResult(status=MutantStatus.KILLED),
            MutationResult(status=MutantStatus.SURVIVED),
        ]

        engine = VerdictEngine(store)
        report = engine.mutate_only(tmp_repo)

        assert report.mutation_score == 50.0

        # Only mutation dimension should be evaluated
        evaluated = [d for d in report.dimensions if d.evaluated]
        assert len(evaluated) == 1
        assert evaluated[0].name == "Mutation Score"
