"""SentinelBridge — import Sentinel's KnowledgeStore for risk signals."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class SentinelBridge:
    """Bridge to Sentinel's knowledge for risk assessment.

    Imports Sentinel as a Python dependency (not MCP-to-MCP).
    Gracefully degrades if Sentinel is not installed or no data exists.
    """

    def __init__(self, repo_path: Path):
        self._repo_path = repo_path
        self._store = None
        self._available = False

        sentinel_db = repo_path / ".sentinel" / "sentinel.db"
        if not sentinel_db.exists():
            return

        try:
            from sentinel.core.knowledge import KnowledgeStore

            self._store = KnowledgeStore(str(sentinel_db))
            self._store.open()
            self._available = True
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._available

    def get_risk_signals(self, changed_files: list[str]) -> dict[str, Any]:
        """Query Sentinel for risk signals related to changed files."""
        if not self._store:
            return {"available": False, "pitfall_matches": [], "hot_files": [], "missing_co_changes": []}

        pitfall_matches = self._match_pitfalls(changed_files)
        hot_files = self._get_hot_files(changed_files)
        missing_co_changes = self._get_missing_co_changes(changed_files)

        return {
            "available": True,
            "pitfall_matches": pitfall_matches,
            "hot_files": hot_files,
            "missing_co_changes": missing_co_changes,
        }

    def _match_pitfalls(self, changed_files: list[str]) -> list[dict]:
        """Match pitfalls against changed files by file_paths and code_pattern regex."""
        matches: list[dict] = []
        if not self._store:
            return matches

        pitfalls = self._store.get_pitfalls(limit=200)
        changed_set = set(changed_files)

        for pitfall in pitfalls:
            # Match by file_paths association (fast path)
            file_path_matches = []
            if hasattr(pitfall, "file_paths") and pitfall.file_paths:
                file_path_matches = [f for f in pitfall.file_paths if f in changed_set]
                if file_path_matches:
                    matches.append({
                        "pitfall_id": pitfall.id,
                        "description": pitfall.description,
                        "severity": pitfall.severity.value if hasattr(pitfall.severity, "value") else str(pitfall.severity),
                        "how_to_prevent": pitfall.how_to_prevent,
                        "matched_file": file_path_matches[0],
                        "match_type": "file_path",
                    })
                    continue

            # Fall back to code_pattern regex matching
            if not pitfall.code_pattern:
                continue
            try:
                pattern = re.compile(pitfall.code_pattern)
            except re.error:
                continue

            for file_path in changed_files:
                full_path = self._repo_path / file_path
                if not full_path.exists():
                    continue
                try:
                    content = full_path.read_text(errors="replace")
                    if pattern.search(content):
                        matches.append({
                            "pitfall_id": pitfall.id,
                            "description": pitfall.description,
                            "severity": pitfall.severity.value if hasattr(pitfall.severity, "value") else str(pitfall.severity),
                            "how_to_prevent": pitfall.how_to_prevent,
                            "matched_file": file_path,
                            "match_type": "code_pattern",
                        })
                except OSError:
                    continue

        return matches

    def _get_hot_files(self, changed_files: list[str]) -> list[dict]:
        """Get hot file data for changed files."""
        hot: list[dict] = []
        if not self._store:
            return hot

        for f in changed_files:
            hf = self._store.get_hot_file(f)
            if hf:
                hot.append({
                    "file_path": hf.file_path,
                    "churn_score": hf.churn_score,
                    "change_count": hf.change_count,
                    "bug_fix_count": hf.bug_fix_count,
                    "revert_count": hf.revert_count,
                })

        return hot

    def _get_missing_co_changes(self, changed_files: list[str]) -> list[dict]:
        """Find co-change partners that weren't included in the diff."""
        missing: list[dict] = []
        if not self._store:
            return missing

        changed_set = set(changed_files)
        seen_pairs: set[str] = set()

        for f in changed_files:
            co_changes = self._store.get_co_changes(f)
            for cc in co_changes:
                # Determine the partner file
                partner = cc.file_b if cc.file_a == f else cc.file_a
                if partner not in changed_set and partner not in seen_pairs:
                    seen_pairs.add(partner)
                    missing.append({
                        "source_file": f,
                        "partner_file": partner,
                        "change_count": cc.change_count,
                    })

        return sorted(missing, key=lambda x: x["change_count"], reverse=True)

    def compute_risk_score(self, signals: dict) -> float:
        """Compute Sentinel risk score (0-100, higher = safer)."""
        if not signals.get("available"):
            return 100.0  # No data = no known risk

        deductions = 0.0
        # Each hot file deducts based on churn score
        for hf in signals.get("hot_files", []):
            deductions += min(10, hf.get("churn_score", 0) / 5)

        # Each pitfall match deducts
        deductions += len(signals.get("pitfall_matches", [])) * 5

        # Each missing co-change deducts
        deductions += len(signals.get("missing_co_changes", [])) * 3

        return round(max(0.0, 100.0 - deductions), 1)

    def compute_co_change_score(self, signals: dict, changed_files: list[str]) -> float:
        """Compute co-change coverage score (0-100).

        Measures whether all expected co-change partners are included in the diff.
        """
        if not signals.get("available"):
            return 100.0

        missing = signals.get("missing_co_changes", [])
        if not missing and not changed_files:
            return 100.0

        # Score based on ratio of missing partners
        total_partners = len(changed_files) + len(missing)
        if total_partners == 0:
            return 100.0

        coverage = len(changed_files) / total_partners
        return round(coverage * 100, 1)

    def close(self) -> None:
        if self._store:
            try:
                self._store.close()
            except Exception:
                pass
            self._store = None
            self._available = False
