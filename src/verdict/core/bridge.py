"""SentinelBridge — import Sentinel's KnowledgeStore for risk signals.

Pure data adapter: fetches signals from Sentinel, returns typed models.
All scoring logic lives in reporter.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from verdict.models.assessment import (
    HotFileInfo,
    MissingCoChange,
    PitfallMatch,
    SentinelSignals,
)


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
        except (OSError, RuntimeError) as exc:
            # DB file exists but can't be opened (corrupt, permissions, etc.)
            pass

    def __enter__(self) -> SentinelBridge:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def available(self) -> bool:
        return self._available

    def get_risk_signals(self, changed_files: list[str]) -> SentinelSignals:
        """Query Sentinel for risk signals related to changed files."""
        if not self._store:
            return SentinelSignals(available=False)

        pitfall_matches = self._match_pitfalls(changed_files)
        hot_files = self._get_hot_files(changed_files)
        missing_co_changes = self._get_missing_co_changes(changed_files)

        return SentinelSignals(
            available=True,
            pitfall_matches=pitfall_matches,
            hot_files=hot_files,
            missing_co_changes=missing_co_changes,
        )

    def _match_pitfalls(self, changed_files: list[str]) -> list[PitfallMatch]:
        """Match pitfalls against changed files by file_paths and code_pattern regex."""
        matches: list[PitfallMatch] = []
        if not self._store:
            return matches

        pitfalls = self._store.get_pitfalls(limit=200)
        changed_set = set(changed_files)

        for pitfall in pitfalls:
            # Match by file_paths association (fast path)
            if hasattr(pitfall, "file_paths") and pitfall.file_paths:
                file_path_hits = [f for f in pitfall.file_paths if f in changed_set]
                if file_path_hits:
                    matches.append(PitfallMatch(
                        pitfall_id=pitfall.id,
                        description=pitfall.description,
                        severity=pitfall.severity.value if hasattr(pitfall.severity, "value") else str(pitfall.severity),
                        how_to_prevent=pitfall.how_to_prevent,
                        matched_file=file_path_hits[0],
                        match_type="file_path",
                    ))
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
                        matches.append(PitfallMatch(
                            pitfall_id=pitfall.id,
                            description=pitfall.description,
                            severity=pitfall.severity.value if hasattr(pitfall.severity, "value") else str(pitfall.severity),
                            how_to_prevent=pitfall.how_to_prevent,
                            matched_file=file_path,
                            match_type="code_pattern",
                        ))
                except OSError:
                    continue

        return matches

    def _get_hot_files(self, changed_files: list[str]) -> list[HotFileInfo]:
        """Get hot file data for changed files."""
        hot: list[HotFileInfo] = []
        if not self._store:
            return hot

        for f in changed_files:
            hf = self._store.get_hot_file(f)
            if hf:
                hot.append(HotFileInfo(
                    file_path=hf.file_path,
                    churn_score=hf.churn_score,
                    change_count=hf.change_count,
                    bug_fix_count=hf.bug_fix_count,
                    revert_count=hf.revert_count,
                ))

        return hot

    def _get_missing_co_changes(self, changed_files: list[str]) -> list[MissingCoChange]:
        """Find co-change partners that weren't included in the diff."""
        missing: list[MissingCoChange] = []
        if not self._store:
            return missing

        changed_set = set(changed_files)
        seen_partners: set[str] = set()

        for f in changed_files:
            co_changes = self._store.get_co_changes(f)
            for cc in co_changes:
                partner = cc.file_b if cc.file_a == f else cc.file_a
                if partner not in changed_set and partner not in seen_partners:
                    seen_partners.add(partner)
                    missing.append(MissingCoChange(
                        source_file=f,
                        partner_file=partner,
                        change_count=cc.change_count,
                    ))

        return sorted(missing, key=lambda x: x.change_count, reverse=True)

    def close(self) -> None:
        if self._store:
            try:
                self._store.close()
            except (OSError, RuntimeError):
                pass
            self._store = None
            self._available = False
