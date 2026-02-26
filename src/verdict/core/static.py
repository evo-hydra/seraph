"""Static analysis aggregation — ruff + mypy on changed files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from verdict.models.assessment import StaticFinding
from verdict.models.enums import AnalyzerType, Severity


def run_static_analysis(
    repo_path: Path,
    files: list[str],
    timeout: int = 60,
) -> list[StaticFinding]:
    """Run ruff and mypy on the specified files, return aggregated findings."""
    findings: list[StaticFinding] = []

    abs_files = [str(repo_path / f) for f in files if f.endswith(".py")]
    if not abs_files:
        return findings

    findings.extend(_run_ruff(repo_path, abs_files, timeout))
    findings.extend(_run_mypy(repo_path, abs_files, timeout))

    return findings


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
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
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
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
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
    # Extract severity
    severity = Severity.MEDIUM
    if rest.startswith("error"):
        severity = Severity.HIGH
        message = rest.split(":", 1)[1].strip() if ":" in rest else rest
    elif rest.startswith("warning"):
        severity = Severity.MEDIUM
        message = rest.split(":", 1)[1].strip() if ":" in rest else rest
    elif rest.startswith("note"):
        severity = Severity.INFO
        message = rest.split(":", 1)[1].strip() if ":" in rest else rest
    else:
        message = rest.strip()

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


def compute_static_score(findings: list[StaticFinding], file_count: int) -> float:
    """Compute static cleanliness score (0-100).

    Score decreases based on issues per file, weighted by severity.
    """
    if file_count == 0:
        return 100.0

    severity_weights = {
        Severity.CRITICAL: 10,
        Severity.HIGH: 5,
        Severity.MEDIUM: 2,
        Severity.LOW: 1,
        Severity.INFO: 0,
    }

    weighted_issues = sum(severity_weights.get(f.severity, 1) for f in findings)
    issues_per_file = weighted_issues / file_count

    # 0 issues = 100, 10+ weighted issues/file = 0
    score = max(0.0, 100.0 - (issues_per_file * 10))
    return round(score, 1)
