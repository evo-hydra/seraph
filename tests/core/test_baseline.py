"""Tests for baseline module."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from verdict.core.baseline import _parse_test_failures, run_baseline


class TestParseTestFailures:
    def test_no_failures(self):
        output = """\
tests/test_a.py::test_one PASSED
tests/test_a.py::test_two PASSED
"""
        assert _parse_test_failures(output) == set()

    def test_with_failures(self):
        output = """\
tests/test_a.py::test_one PASSED
tests/test_a.py::test_two FAILED
tests/test_b.py::test_three FAILED
"""
        result = _parse_test_failures(output)
        assert result == {"tests/test_a.py::test_two", "tests/test_b.py::test_three"}

    def test_empty_output(self):
        assert _parse_test_failures("") == set()


class TestRunBaseline:
    @patch("verdict.core.baseline._run_tests_once")
    def test_all_stable(self, mock_run):
        mock_run.return_value = set()
        result = run_baseline(Path("/tmp/test"), run_count=3)
        assert result.flaky_tests == []
        assert result.pass_rate == 1.0
        assert result.run_count == 3

    @patch("verdict.core.baseline._run_tests_once")
    def test_flaky_detection(self, mock_run):
        # test_b fails in run 1 and 3 but not 2 → flaky
        mock_run.side_effect = [
            {"test_a", "test_b"},
            {"test_a"},
            {"test_a", "test_b"},
        ]
        result = run_baseline(Path("/tmp/test"), run_count=3)
        # test_a fails in all 3 → not flaky (consistently failing)
        # test_b fails in 2 of 3 → flaky
        assert "test_b" in result.flaky_tests
        assert "test_a" not in result.flaky_tests

    @patch("verdict.core.baseline._run_tests_once")
    def test_consistent_failures_not_flaky(self, mock_run):
        mock_run.return_value = {"test_always_fails"}
        result = run_baseline(Path("/tmp/test"), run_count=3)
        assert result.flaky_tests == []
