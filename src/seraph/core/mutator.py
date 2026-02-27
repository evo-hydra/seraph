"""Mutation testing via mutmut subprocess integration."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from seraph.models.assessment import MutationResult
from seraph.models.enums import MutantStatus

logger = logging.getLogger(__name__)


@dataclass
class MutationRunResult:
    """Wrapper for mutation run output with tool availability info."""

    results: list[MutationResult]
    tool_available: bool  # True if mutmut was found and executed


def run_mutations(
    repo_path: Path,
    files: list[str],
    timeout_per_file: int = 120,
) -> MutationRunResult:
    """Run mutmut on each file and return mutation results.

    Shells out to mutmut CLI for process isolation and stable contract.
    """
    all_results: list[MutationResult] = []
    tool_available = False

    for file_path in files:
        if not file_path.endswith(".py"):
            continue
        full_path = repo_path / file_path
        if not full_path.exists():
            continue

        results, available = _mutate_single_file(repo_path, file_path, timeout_per_file)
        all_results.extend(results)
        if available:
            tool_available = True

    return MutationRunResult(results=all_results, tool_available=tool_available)


def _mutate_single_file(
    repo_path: Path, file_path: str, timeout: int
) -> tuple[list[MutationResult], bool]:
    """Run mutmut on a single file and parse results.

    Returns (results, tool_available) tuple.
    """
    try:
        subprocess.run(
            [
                "mutmut",
                "run",
                "--paths-to-mutate",
                file_path,
                "--no-progress",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            [
                MutationResult(
                    file_path=file_path,
                    mutant_id="timeout",
                    operator="all",
                    status=MutantStatus.TIMEOUT,
                )
            ],
            True,
        )
    except FileNotFoundError:
        logger.warning("mutmut not installed — install with: pip install 'seraph[mutation]'")
        return ([], False)

    return (_parse_mutmut_results(repo_path, file_path), True)


def _parse_mutmut_results(repo_path: Path, file_path: str) -> list[MutationResult]:
    """Parse mutmut results using `mutmut results` command or JSON cache."""
    # Try JSON cache first (mutmut >= 2.4)
    cache_path = repo_path / ".mutmut-cache"
    if cache_path.exists():
        return _parse_from_cache(cache_path, file_path)

    # Fall back to `mutmut results` command
    return _parse_from_command(repo_path, file_path)


def _parse_from_cache(cache_path: Path, file_path: str) -> list[MutationResult]:
    """Parse results from mutmut's SQLite cache."""
    results: list[MutationResult] = []
    db_path = str(cache_path / "db.sqlite3") if cache_path.is_dir() else str(cache_path)
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM mutant WHERE source_file = ?", (file_path,))
            for row in cur.fetchall():
                col_names = row.keys()
                status = _map_mutmut_status(row["status"] if "status" in col_names else "unknown")
                results.append(
                    MutationResult(
                        file_path=file_path,
                        mutant_id=str(row["id"]),
                        operator=row["operator"] if "operator" in col_names else "unknown",
                        line_number=row["line_number"] if "line_number" in col_names else None,
                        status=status,
                    )
                )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.debug("Failed to parse mutmut cache at %s: %s", db_path, exc)
    except (KeyError, ValueError) as exc:
        logger.debug("Unexpected schema in mutmut cache: %s", exc)
    return results


def _parse_from_command(repo_path: Path, file_path: str) -> list[MutationResult]:
    """Parse results from `mutmut results` command output."""
    results: list[MutationResult] = []
    try:
        proc = subprocess.run(
            ["mutmut", "results"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        current_status = MutantStatus.SURVIVED
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("Survived"):
                current_status = MutantStatus.SURVIVED
            elif line.startswith("Killed"):
                current_status = MutantStatus.KILLED
            elif line.startswith("Timeout"):
                current_status = MutantStatus.TIMEOUT
            elif line and line[0].isdigit():
                for mutant_id in line.split(","):
                    mutant_id = mutant_id.strip()
                    if mutant_id.isdigit():
                        results.append(
                            MutationResult(
                                file_path=file_path,
                                mutant_id=mutant_id,
                                operator="unknown",
                                status=current_status,
                            )
                        )
    except subprocess.TimeoutExpired:
        logger.debug("mutmut results timed out for %s", file_path)
    except FileNotFoundError:
        logger.debug("mutmut not found on PATH")
    return results


def _map_mutmut_status(status: str) -> MutantStatus:
    """Map mutmut status string to our enum."""
    status_lower = status.lower()
    if "killed" in status_lower or "ok" in status_lower:
        return MutantStatus.KILLED
    if "survived" in status_lower or "bad" in status_lower:
        return MutantStatus.SURVIVED
    if "timeout" in status_lower:
        return MutantStatus.TIMEOUT
    if "skipped" in status_lower:
        return MutantStatus.SKIPPED
    return MutantStatus.ERROR
