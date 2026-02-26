"""Tests for SentinelBridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verdict.core.bridge import SentinelBridge
from verdict.models.assessment import SentinelSignals


class TestSentinelBridgeUnavailable:
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


class TestSentinelBridgeAvailable:
    """Tests with a mocked KnowledgeStore to cover the connected path."""

    def _make_bridge_with_mock_store(self, tmp_path):
        """Create a bridge with a mocked KnowledgeStore."""
        sentinel_dir = tmp_path / ".sentinel"
        sentinel_dir.mkdir()
        (sentinel_dir / "sentinel.db").touch()

        mock_store = MagicMock()
        bridge = SentinelBridge.__new__(SentinelBridge)
        bridge._store = mock_store
        bridge._repo_path = tmp_path
        bridge._available = True
        return bridge, mock_store

    def test_available_with_store(self, tmp_path):
        bridge, _ = self._make_bridge_with_mock_store(tmp_path)
        assert bridge.available is True
        bridge.close()

    def test_returns_pitfall_matches(self, tmp_path):
        bridge, mock_store = self._make_bridge_with_mock_store(tmp_path)

        mock_pitfall = MagicMock()
        mock_pitfall.file_paths = ["foo.py"]
        mock_pitfall.description = "Watch out for X"
        mock_pitfall.severity = "high"
        mock_pitfall.code_pattern = None
        mock_store.get_pitfalls.return_value = [mock_pitfall]
        mock_store.get_hot_file.return_value = None
        mock_store.get_co_changes.return_value = []

        signals = bridge.get_risk_signals(["foo.py"])
        assert signals.available is True
        assert len(signals.pitfall_matches) >= 1
        bridge.close()

    def test_returns_hot_files(self, tmp_path):
        bridge, mock_store = self._make_bridge_with_mock_store(tmp_path)

        mock_hot = MagicMock()
        mock_hot.file_path = "foo.py"
        mock_hot.churn_score = 42.0
        mock_hot.change_count = 10
        mock_hot.bug_fix_count = 2
        mock_hot.revert_count = 0
        mock_store.get_pitfalls.return_value = []
        mock_store.get_hot_file.return_value = mock_hot
        mock_store.get_co_changes.return_value = []

        signals = bridge.get_risk_signals(["foo.py"])
        assert len(signals.hot_files) == 1
        assert signals.hot_files[0].churn_score == 42.0
        bridge.close()

    def test_returns_missing_co_changes(self, tmp_path):
        bridge, mock_store = self._make_bridge_with_mock_store(tmp_path)

        mock_co = MagicMock()
        mock_co.file_a = "foo.py"
        mock_co.file_b = "bar.py"
        mock_co.change_count = 5
        mock_store.get_pitfalls.return_value = []
        mock_store.get_hot_file.return_value = None
        mock_store.get_co_changes.return_value = [mock_co]

        # bar.py is NOT in changed_files → it's "missing"
        signals = bridge.get_risk_signals(["foo.py"])
        assert len(signals.missing_co_changes) == 1
        assert signals.missing_co_changes[0].partner_file == "bar.py"
        bridge.close()

    def test_co_change_not_missing_when_included(self, tmp_path):
        bridge, mock_store = self._make_bridge_with_mock_store(tmp_path)

        mock_co = MagicMock()
        mock_co.file_a = "foo.py"
        mock_co.file_b = "bar.py"
        mock_co.change_count = 5
        mock_store.get_pitfalls.return_value = []
        mock_store.get_hot_file.return_value = None
        mock_store.get_co_changes.return_value = [mock_co]

        # bar.py IS in changed_files → not missing
        signals = bridge.get_risk_signals(["foo.py", "bar.py"])
        assert signals.missing_co_changes == []
        bridge.close()
