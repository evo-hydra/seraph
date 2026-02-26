"""Tests for mutator module."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from verdict.core.mutator import (
    run_mutations,
    _map_mutmut_status,
)
from verdict.core.reporter import compute_mutation_score
from verdict.models.assessment import MutationResult
from verdict.models.enums import MutantStatus


class TestComputeMutationScore:
    def test_no_mutants(self):
        assert compute_mutation_score([]) == 100.0

    def test_all_killed(self):
        results = [
            MutationResult(status=MutantStatus.KILLED),
            MutationResult(status=MutantStatus.KILLED),
        ]
        assert compute_mutation_score(results) == 100.0

    def test_none_killed(self):
        results = [
            MutationResult(status=MutantStatus.SURVIVED),
            MutationResult(status=MutantStatus.SURVIVED),
        ]
        assert compute_mutation_score(results) == 0.0

    def test_mixed(self):
        results = [
            MutationResult(status=MutantStatus.KILLED),
            MutationResult(status=MutantStatus.SURVIVED),
            MutationResult(status=MutantStatus.KILLED),
            MutationResult(status=MutantStatus.TIMEOUT),
        ]
        # 2 killed out of 4
        assert compute_mutation_score(results) == 50.0


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
    @patch("verdict.core.mutator._mutate_single_file")
    def test_skips_non_python(self, mock_mutate, tmp_path):
        (tmp_path / "readme.md").touch()
        results = run_mutations(tmp_path, ["readme.md"])
        mock_mutate.assert_not_called()
        assert results == []

    @patch("verdict.core.mutator._mutate_single_file")
    def test_runs_on_python_files(self, mock_mutate, tmp_path):
        (tmp_path / "foo.py").write_text("x = 1")
        mock_mutate.return_value = [
            MutationResult(file_path="foo.py", status=MutantStatus.KILLED)
        ]
        results = run_mutations(tmp_path, ["foo.py"])
        assert len(results) == 1
        assert results[0].status == MutantStatus.KILLED
