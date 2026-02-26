"""Tests for static analysis module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from verdict.core.static import (
    _parse_mypy_line,
    _ruff_severity,
    run_static_analysis,
)
from verdict.models.assessment import StaticFinding
from verdict.models.enums import AnalyzerType, Severity


# NOTE: compute_static_score tests live in test_reporter.py


class TestRuffSeverity:
    def test_security(self):
        assert _ruff_severity("S101") == Severity.HIGH

    def test_error(self):
        assert _ruff_severity("E999") == Severity.HIGH
        assert _ruff_severity("F401") == Severity.HIGH

    def test_convention(self):
        assert _ruff_severity("E501") == Severity.LOW
        assert _ruff_severity("W291") == Severity.LOW

    def test_other(self):
        assert _ruff_severity("C901") == Severity.MEDIUM


class TestParseMypyLine:
    def test_error_line(self):
        finding = _parse_mypy_line(
            '/tmp/test/foo.py:10: error: Incompatible types [assignment]',
            Path("/tmp/test"),
        )
        assert finding is not None
        assert finding.file_path == "foo.py"
        assert finding.line_number == 10
        assert finding.severity == Severity.HIGH
        assert finding.code == "assignment"

    def test_warning_line(self):
        finding = _parse_mypy_line(
            '/tmp/test/bar.py:5: warning: Unused variable',
            Path("/tmp/test"),
        )
        assert finding is not None
        assert finding.severity == Severity.MEDIUM

    def test_note_line(self):
        finding = _parse_mypy_line(
            '/tmp/test/baz.py:1: note: See docs',
            Path("/tmp/test"),
        )
        assert finding is not None
        assert finding.severity == Severity.INFO

    def test_invalid_line(self):
        assert _parse_mypy_line("not a valid line", Path("/tmp")) is None


