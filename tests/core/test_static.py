"""Tests for static analysis module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from seraph.core.static import (
    StaticRunResult,
    _parse_mypy_line,
    _ruff_severity,
    detect_tool_config,
    run_static_analysis,
)
from seraph.models.assessment import StaticFinding
from seraph.models.enums import AnalyzerType, Severity


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


class TestDetectToolConfig:
    def test_no_config_files(self, tmp_path):
        result = detect_tool_config(tmp_path)
        assert result == {"ruff": False, "mypy": False}

    def test_mypy_ini(self, tmp_path):
        (tmp_path / "mypy.ini").write_text("[mypy]\n")
        result = detect_tool_config(tmp_path)
        assert result["mypy"] is True

    def test_dot_mypy_ini(self, tmp_path):
        (tmp_path / ".mypy.ini").write_text("[mypy]\n")
        result = detect_tool_config(tmp_path)
        assert result["mypy"] is True

    def test_pyproject_tool_mypy(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.mypy]\nstrict = true\n")
        result = detect_tool_config(tmp_path)
        assert result["mypy"] is True

    def test_ruff_toml(self, tmp_path):
        (tmp_path / "ruff.toml").write_text("line-length = 88\n")
        result = detect_tool_config(tmp_path)
        assert result["ruff"] is True

    def test_dot_ruff_toml(self, tmp_path):
        (tmp_path / ".ruff.toml").write_text("line-length = 88\n")
        result = detect_tool_config(tmp_path)
        assert result["ruff"] is True

    def test_pyproject_tool_ruff(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        result = detect_tool_config(tmp_path)
        assert result["ruff"] is True

    def test_setup_cfg_mypy(self, tmp_path):
        (tmp_path / "setup.cfg").write_text("[mypy]\nignore_missing_imports = True\n")
        result = detect_tool_config(tmp_path)
        assert result["mypy"] is True

    def test_pyproject_both_tools(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.mypy]\nstrict = true\n\n[tool.ruff]\nline-length = 88\n"
        )
        result = detect_tool_config(tmp_path)
        assert result["mypy"] is True
        assert result["ruff"] is True


class TestRunStaticAnalysis:
    @patch("seraph.core.static._run_ruff")
    @patch("seraph.core.static._run_mypy")
    def test_returns_static_run_result(self, mock_mypy, mock_ruff, tmp_path):
        mock_ruff.return_value = []
        mock_mypy.return_value = []
        result = run_static_analysis(tmp_path, ["foo.py"])
        assert isinstance(result, StaticRunResult)
        assert result.findings == []
        assert "ruff" in result.tool_config
        assert "mypy" in result.tool_config


