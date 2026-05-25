"""Watchdog heartbeat & stall-detection tests."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fresh_paths(monkeypatch, tmp_path):
    """Each test uses tmp logs/ so concurrent tests don't trample each other."""
    monkeypatch.chdir(tmp_path)
    Path("logs").mkdir()
    from notifications import watchdog as wd_mod
    monkeypatch.setattr(wd_mod, "HEARTBEAT_FILE", tmp_path / "logs" / "heartbeat.txt")
    monkeypatch.setattr(wd_mod, "STALL_MARKER", tmp_path / "logs" / "STALL")
    yield tmp_path


def test_tick_writes_heartbeat(fresh_paths):
    from notifications.watchdog import HEARTBEAT_FILE, Watchdog
    wd = Watchdog(notifier=None, check_interval_sec=999)
    wd.tick()
    assert HEARTBEAT_FILE.exists()
    content = HEARTBEAT_FILE.read_text().strip()
    assert content.isdigit()
    wd.stop()


def test_tick_clears_stall_marker(fresh_paths):
    from notifications.watchdog import STALL_MARKER, Watchdog
    STALL_MARKER.write_text("123")
    wd = Watchdog(notifier=None, check_interval_sec=999)
    wd.tick()
    assert not STALL_MARKER.exists()
    wd.stop()


def test_inactivity_triggers_alert(fresh_paths):
    from notifications.watchdog import STALL_MARKER, Watchdog
    notifier = MagicMock()
    wd = Watchdog(
        notifier=notifier,
        inactivity_threshold_sec=0,    # immediate stall
        check_interval_sec=1,
    )
    # Wait one check interval — monitor should fire
    time.sleep(1.5)
    wd.stop()
    assert STALL_MARKER.exists()
    notifier.send.assert_called()
    msg = notifier.send.call_args[0][0]
    assert "WATCHDOG" in msg


def test_no_alert_when_fresh(fresh_paths):
    from notifications.watchdog import STALL_MARKER, Watchdog
    notifier = MagicMock()
    wd = Watchdog(
        notifier=notifier,
        inactivity_threshold_sec=999,  # never stale
        check_interval_sec=1,
    )
    time.sleep(1.2)
    wd.stop()
    assert not STALL_MARKER.exists()
    notifier.send.assert_not_called()


def test_alert_fires_only_once_per_stall(fresh_paths):
    from notifications.watchdog import Watchdog
    notifier = MagicMock()
    wd = Watchdog(
        notifier=notifier,
        inactivity_threshold_sec=0,
        check_interval_sec=1,
    )
    time.sleep(2.5)   # at least 2 check cycles
    wd.stop()
    # Despite multiple stall cycles, alert fires once until tick() resets
    assert notifier.send.call_count == 1


def test_tick_after_alert_re_arms(fresh_paths):
    from notifications.watchdog import Watchdog
    notifier = MagicMock()
    wd = Watchdog(
        notifier=notifier,
        inactivity_threshold_sec=0,
        check_interval_sec=1,
    )
    time.sleep(1.2)
    assert notifier.send.call_count == 1
    wd.tick()  # bot recovered
    time.sleep(1.2)  # stall again
    wd.stop()
    assert notifier.send.call_count == 2
