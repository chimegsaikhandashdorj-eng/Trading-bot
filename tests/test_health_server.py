"""Health-check HTTP endpoint tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock
from urllib.request import urlopen

import pytest


@pytest.fixture
def fake_bot():
    bot = MagicMock()
    bot.status_snapshot.return_value = {
        "paused": False,
        "binance_connected": True,
        "mt5_connected": False,
        "open_positions": 3,
        "daily_pnl": 12.5,
        "daily_trades": 7,
    }
    return bot


@pytest.fixture
def server(monkeypatch, tmp_path, fake_bot):
    monkeypatch.chdir(tmp_path)
    Path("logs").mkdir()
    from notifications import health_server as hs_mod
    monkeypatch.setattr(hs_mod, "STALL_MARKER", tmp_path / "logs" / "STALL")
    from notifications.health_server import HealthServer
    srv = HealthServer(fake_bot, host="127.0.0.1", port=0)   # port=0 → OS picks
    # Skip the OS-picked-port complication by binding to a known free port
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv.port = port
    srv.start()
    time.sleep(0.2)   # give the thread time to bind
    yield srv, port
    srv.stop()


def test_health_returns_200_when_alive(server):
    _, port = server
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read())
    assert body["open_positions"] == 3
    assert body["stalled"] is False


def test_health_returns_503_on_stall(server, monkeypatch, tmp_path):
    srv, port = server
    from notifications import health_server as hs_mod
    hs_mod.STALL_MARKER.write_text("123")
    import urllib.error
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            status = resp.status
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read())
    assert status == 503
    assert body["stalled"] is True


def test_metrics_endpoint_returns_prometheus_text(server):
    _, port = server
    with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
    assert "bot_open_positions 3" in body
    assert "bot_daily_pnl 12.5" in body


def test_unknown_path_returns_404(server):
    _, port = server
    import urllib.error
    try:
        with urlopen(f"http://127.0.0.1:{port}/nope", timeout=5):
            assert False, "should have raised"
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
