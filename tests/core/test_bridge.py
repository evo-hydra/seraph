"""Tests for SentinelBridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verdict.core.bridge import SentinelBridge


class TestSentinelBridge:
    def test_unavailable_when_no_db(self, tmp_path):
        bridge = SentinelBridge(tmp_path)
        assert bridge.available is False
        signals = bridge.get_risk_signals(["foo.py"])
        assert signals["available"] is False
        bridge.close()

    def test_unavailable_when_sentinel_not_installed(self, tmp_path):
        # Create the sentinel db path but sentinel isn't importable
        sentinel_dir = tmp_path / ".sentinel"
        sentinel_dir.mkdir()
        (sentinel_dir / "sentinel.db").touch()

        with patch.dict("sys.modules", {"sentinel": None, "sentinel.core": None, "sentinel.core.knowledge": None}):
            bridge = SentinelBridge(tmp_path)
            assert bridge.available is False
            bridge.close()

    def test_compute_risk_score_no_data(self):
        bridge = SentinelBridge(Path("/nonexistent"))
        score = bridge.compute_risk_score({"available": False})
        assert score == 100.0
        bridge.close()

    def test_compute_risk_score_with_signals(self):
        bridge = SentinelBridge(Path("/nonexistent"))
        signals = {
            "available": True,
            "pitfall_matches": [{"id": "1"}, {"id": "2"}],
            "hot_files": [{"churn_score": 50}],
            "missing_co_changes": [{"partner": "a.py"}],
        }
        score = bridge.compute_risk_score(signals)
        # 2 pitfalls * 5 = 10, 1 hot file (50/5=10 capped at 10) = 10, 1 missing * 3 = 3
        assert score == 100 - 10 - 10 - 3  # 77
        bridge.close()

    def test_compute_co_change_score_no_data(self):
        bridge = SentinelBridge(Path("/nonexistent"))
        score = bridge.compute_co_change_score({"available": False}, ["a.py"])
        assert score == 100.0
        bridge.close()

    def test_compute_co_change_score_with_missing(self):
        bridge = SentinelBridge(Path("/nonexistent"))
        signals = {
            "available": True,
            "missing_co_changes": [{"partner": "b.py"}, {"partner": "c.py"}],
        }
        # 2 changed + 2 missing = 4 total partners, coverage = 2/4 = 50%
        score = bridge.compute_co_change_score(signals, ["a.py", "d.py"])
        assert score == 50.0
        bridge.close()
