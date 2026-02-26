"""Tests for SentinelBridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verdict.core.bridge import SentinelBridge
from verdict.models.assessment import SentinelSignals


class TestSentinelBridge:
    def test_unavailable_when_no_db(self, tmp_path):
        bridge = SentinelBridge(tmp_path)
        assert bridge.available is False
        signals = bridge.get_risk_signals(["foo.py"])
        assert signals.available is False
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

    def test_context_manager(self, tmp_path):
        with SentinelBridge(tmp_path) as bridge:
            assert bridge.available is False
            signals = bridge.get_risk_signals(["foo.py"])
            assert signals.available is False

    def test_returns_typed_signals(self, tmp_path):
        bridge = SentinelBridge(tmp_path)
        signals = bridge.get_risk_signals(["foo.py"])
        assert isinstance(signals, SentinelSignals)
        assert signals.pitfall_matches == []
        assert signals.hot_files == []
        assert signals.missing_co_changes == []
        bridge.close()
