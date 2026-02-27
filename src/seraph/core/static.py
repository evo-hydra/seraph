"""Static analysis aggregation — ruff + mypy on changed files."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from seraph.models.assessment import StaticFinding
from seraph.models.enums import AnalyzerType, Severity

logger = logging.getLogger(__name__)


@dataclass
class StaticRunResult:
    """Wrapper for static analysis output with tool configuration info."""

    findings: list[StaticFinding]
    tool_config: dict[str, bool]  # {"ruff": True/False, "mypy": True/False}


def detect_tool_config(repo_path: Path) -> dict[str, bool]:
    """Detect whether ruff and mypy are configured for this project.

    Checks for config files and pyproject.toml sections. Does not parse
    TOML — just checks for section header strings.
    """
    mypy_configured = False
    ruff_configured = False

    # mypy: mypy.ini, .mypy.ini, setup.cfg [mypy], pyproject.toml [tool.mypy]
    if (repo_path / "mypy.ini").exists() or (repo_path / ".mypy.ini").exists():
        mypy_configured = True
    else:
        setup_cfg = repo_path / "setup.cfg"
        if setup_cfg.exists() and "[mypy]" in setup_cfg.read_text(errors="ignore"):
            mypy_configured = True

    # ruff: ruff.toml, .ruff.toml, pyproject.toml [tool.ruff]
    if (repo_path / "ruff.toml").exists() or (repo_path / ".ruff.toml").exists():
        ruff_configured = True

    # Check pyproject.toml for both
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(errors="ignore")
        if not mypy_configured and "[tool.mypy]" in content:
            mypy_configured = True
        if not ruff_configured and "[tool.ruff]" in content:
            ruff_configured = True

    return {"ruff": ruff_configured, "mypy": mypy_configured}


def run_static_analysis(
    repo_path: Path,
    files: list[str],
    timeout: int = 60,
) -> StaticRunResult:
    """Run ruff and mypy on the specified files, return aggregated findings."""
    tool_config = detect_tool_config(repo_path)
    findings: list[StaticFinding] = []

    abs_files = [str(repo_path / f) for f in files if f.endswith(".py")]
    if not abs_files:
        return StaticRunResult(findings=findings, tool_config=tool_config)

    findings.extend(_run_ruff(repo_path, abs_files, timeout))
    findings.extend(_run_mypy(repo_path, abs_files, timeout))

    return StaticRunResult(findings=findings, tool_config=tool_config)


def _run_ruff(repo_path: Path, abs_files: list[str], timeout: int) -> list[StaticFinding]:
    """Run ruff and parse JSON output."""
    findings: list[StaticFinding] = []
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", "--no-fix", *abs_files],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # ruff returns exit code 1 when it finds issues
        if result.stdout:
            issues = json.loads(result.stdout)
            for issue in issues:
                rel_path = _to_relative(issue.get("filename", ""), repo_path)
                findings.append(
                    StaticFinding(
                        file_path=rel_path,
                        line_number=issue.get("location", {}).get("row", 0),
                        column=issue.get("location", {}).get("column", 0),
                        code=issue.get("code", ""),
                        message=issue.get("message", ""),
                        severity=_ruff_severity(issue.get("code", "")),
                        analyzer=AnalyzerType.RUFF,
                    )
                )
    except subprocess.TimeoutExpired:
        logger.warning("ruff timed out after %ds", timeout)
    except FileNotFoundError:
        logger.warning("ruff not found on PATH — install with: pip install ruff")
    except json.JSONDecodeError as exc:
        logger.debug("Failed to parse ruff JSON output: %s", exc)
    return findings


def _run_mypy(repo_path: Path, abs_files: list[str], timeout: int) -> list[StaticFinding]:
    """Run mypy and parse output."""
    findings: list[StaticFinding] = []
    try:
        result = subprocess.run(
            ["mypy", "--no-color-output", "--no-error-summary", *abs_files],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        for line in result.stdout.splitlines():
            finding = _parse_mypy_line(line, repo_path)
            if finding:
                findings.append(finding)
    except subprocess.TimeoutExpired:
        logger.warning("mypy timed out after %ds", timeout)
    except FileNotFoundError:
        logger.warning("mypy not found on PATH — install with: pip install mypy")
    return findings


def _parse_mypy_line(line: str, repo_path: Path) -> StaticFinding | None:
    """Parse a single mypy output line: 'file:line: severity: message [code]'."""
    parts = line.split(":", maxsplit=3)
    if len(parts) < 4:
        return None

    file_path = _to_relative(parts[0].strip(), repo_path)
    try:
        line_number = int(parts[1].strip())
    except ValueError:
        return None

    rest = parts[2].strip() + ":" + parts[3] if len(parts) > 3 else parts[2].strip()
    # Extract severity and message
    _MYPY_SEVERITY = {"error": Severity.HIGH, "warning": Severity.MEDIUM, "note": Severity.INFO}
    severity = Severity.MEDIUM
    message = rest.strip()
    for prefix, sev in _MYPY_SEVERITY.items():
        if rest.startswith(prefix):
            severity = sev
            message = rest.split(":", 1)[1].strip() if ":" in rest else rest
            break

    # Extract code if present: [code]
    code = ""
    if message.endswith("]") and "[" in message:
        bracket_pos = message.rfind("[")
        code = message[bracket_pos + 1 : -1]
        message = message[:bracket_pos].strip()

    return StaticFinding(
        file_path=file_path,
        line_number=line_number,
        column=0,
        code=code,
        message=message,
        severity=severity,
        analyzer=AnalyzerType.MYPY,
    )


def _to_relative(path: str, repo_path: Path) -> str:
    """Convert absolute path to relative."""
    try:
        return str(Path(path).relative_to(repo_path))
    except ValueError:
        return path


def _ruff_severity(code: str) -> Severity:
    """Map ruff rule codes to severity levels."""
    # Security-related rules
    if code.startswith("S"):
        return Severity.HIGH
    # Error-prone rules
    if code.startswith(("E9", "F")):
        return Severity.HIGH
    # Convention / style
    if code.startswith(("E", "W")):
        return Severity.LOW
    return Severity.MEDIUM
