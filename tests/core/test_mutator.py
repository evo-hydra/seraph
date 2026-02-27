"""Tests for mutator module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from seraph.core.mutator import (
    run_mutations,
    MutationRunResult,
    _map_mutmut_status,
)
from seraph.models.assessment import MutationResult
from seraph.models.enums import MutantStatus


# NOTE: compute_mutation_score tests live in test_reporter.py


class TestMapMutmutStatus:
    def test_killed(self):
        assert _map_mutmut_status("killed") == MutantStatus.KILLED
        assert _map_mutmut_status("ok_killed") == MutantStatus.KILLED

    def test_survived(self):
        assert _map_mutmut_status("survived") == MutantStatus.SURVIVED
        assert _map_mutmut_status("bad_survived") == MutantStatus.SURVIVED

    def test_timeout(self):
        assert _map_mutmut_status("timeout") == MutantStatus.TIMEOUT

    def test_skipped(self):
        assert _map_mutmut_status("skipped") == MutantStatus.SKIPPED

    def test_unknown(self):
        assert _map_mutmut_status("???") == MutantStatus.ERROR


class TestRunMutations:
    @patch("seraph.core.mutator._mutate_single_file")
    def test_skips_non_python(self, mock_mutate, tmp_path):
        (tmp_path / "readme.md").touch()
        result = run_mutations(tmp_path, ["readme.md"])
        mock_mutate.assert_not_called()
        assert isinstance(result, MutationRunResult)
        assert result.results == []
        assert result.tool_available is False

    @patch("seraph.core.mutator._mutate_single_file")
    def test_runs_on_python_files(self, mock_mutate, tmp_path):
        (tmp_path / "foo.py").write_text("x = 1")
        mock_mutate.return_value = (
            [MutationResult(file_path="foo.py", status=MutantStatus.KILLED)],
            True,
        )
        result = run_mutations(tmp_path, ["foo.py"])
        assert isinstance(result, MutationRunResult)
        assert len(result.results) == 1
        assert result.results[0].status == MutantStatus.KILLED
        assert result.tool_available is True

    @patch("seraph.core.mutator._mutate_single_file")
    def test_tool_not_available(self, mock_mutate, tmp_path):
        """FileNotFoundError → tool_available=False."""
        (tmp_path / "foo.py").write_text("x = 1")
        mock_mutate.return_value = ([], False)
        result = run_mutations(tmp_path, ["foo.py"])
        assert result.tool_available is False
        assert result.results == []

    @patch("seraph.core.mutator._mutate_single_file")
    def test_tool_available_no_mutations(self, mock_mutate, tmp_path):
        """Empty results + tool_available=True (no mutable code)."""
        (tmp_path / "foo.py").write_text("x = 1")
        mock_mutate.return_value = ([], True)
        result = run_mutations(tmp_path, ["foo.py"])
        assert result.tool_available is True
        assert result.results == []
