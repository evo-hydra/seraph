"""Flakiness baseline — run tests N times unmutated to detect flaky tests."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from verdict.models.assessment import BaselineResult


def run_baseline(
    repo_path: Path,
    test_cmd: str = "pytest",
    run_count: int = 3,
    timeout: int = 120,
) -> BaselineResult:
    """Run the test suite `run_count` times and identify flaky tests.

    A test is flaky if it doesn't produce the same pass/fail result across all runs.
    """
    all_failures: list[set[str]] = []

    for _ in range(run_count):
        failures = _run_tests_once(repo_path, test_cmd, timeout)
        all_failures.append(failures)

    # A test is flaky if it fails in some runs but not all
    all_test_ids: set[str] = set()
    for failures in all_failures:
        all_test_ids.update(failures)

    flaky: list[str] = []
    for test_id in sorted(all_test_ids):
        fail_count = sum(1 for failures in all_failures if test_id in failures)
        if 0 < fail_count < run_count:
            flaky.append(test_id)

    # Calculate overall pass rate
    total_results = sum(len(f) for f in all_failures)
    if all_test_ids:
        # pass_rate = 1 - (average failures per run / total unique tests seen)
        avg_failures = total_results / run_count
        pass_rate = max(0.0, 1.0 - (avg_failures / max(len(all_test_ids), 1)))
    else:
        pass_rate = 1.0

    return BaselineResult(
        repo_path=str(repo_path),
        test_cmd=test_cmd,
        run_count=run_count,
        flaky_tests=flaky,
        pass_rate=round(pass_rate, 4),
    )


def _run_tests_once(repo_path: Path, test_cmd: str, timeout: int) -> set[str]:
    """Run tests once and return set of failed test IDs."""
    cmd_parts = test_cmd.split()
    # Add verbose output for test ID parsing
    if cmd_parts[0] == "pytest" and "-v" not in cmd_parts:
        cmd_parts.append("-v")

    try:
        result = subprocess.run(
            cmd_parts,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"__timeout__"}

    return _parse_pytest_failures(result.stdout)


def _parse_pytest_failures(output: str) -> set[str]:
    """Parse pytest verbose output to extract failed test IDs."""
    failures: set[str] = set()
    for line in output.splitlines():
        # pytest -v format: "tests/test_foo.py::test_bar FAILED"
        if " FAILED" in line:
            test_id = line.split(" FAILED")[0].strip()
            if test_id:
                failures.add(test_id)
    return failures
