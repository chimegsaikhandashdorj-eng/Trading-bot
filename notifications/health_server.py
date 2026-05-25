"""
Lightweight HTTP health-check server.

Uses Python stdlib's `http.server` — no extra dependency, no async runtime.
The server runs in a daemon thread so it never blocks shutdown.

Endpoints
---------
- `GET /health`  — 200 with JSON status snapshot, 503 if bot is stalled
- `GET /metrics` — Prometheus-style plaintext (basic counters)

Use cases
---------
- Docker HEALTHCHECK
- k8s liveness / readiness probes
- External uptime monitors (pingdom, healthchecks.io)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from utils.logger import get_logger

if TYPE_CHECKING:
    from main import TradingBot

log = get_logger("Health")

STALL_MARKER = Path("logs/STALL")
HEARTBEAT_FILE = Path("logs/heartbeat.txt")


def _make_handler(bot: "TradingBot"):
    """Build a BaseHTTPRequestHandler bound to a specific TradingBot instance."""

    class HealthHandler(BaseHTTPRequestHandler):
        # Quiet the default access log
        def log_message(self, format: str, *args) -> None:   # noqa: A002
            return

        def _send_json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_text(self, status: int, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:   # noqa: N802 (http.server API)
            if self.path == "/health":
                snap = bot.status_snapshot()
                # 503 if watchdog marked a stall
                status = 503 if STALL_MARKER.exists() else 200
                snap["stalled"] = STALL_MARKER.exists()
                self._send_json(status, snap)
                return

            if self.path == "/metrics":
                snap = bot.status_snapshot()
                lines = [
                    "# HELP bot_paused 1 if bot is paused",
                    "# TYPE bot_paused gauge",
                    f"bot_paused {int(snap['paused'])}",
                    "# HELP bot_mt5_connected 1 if MT5 session is alive",
                    "# TYPE bot_mt5_connected gauge",
                    f"bot_mt5_connected {int(snap['mt5_connected'])}",
                    "# HELP bot_open_positions Current open positions",
                    "# TYPE bot_open_positions gauge",
                    f"bot_open_positions {snap['open_positions']}",
                    "# HELP bot_daily_pnl Today's realized P&L",
                    "# TYPE bot_daily_pnl gauge",
                    f"bot_daily_pnl {snap['daily_pnl']}",
                    "# HELP bot_daily_trades Today's closed trade count",
                    "# TYPE bot_daily_trades counter",
                    f"bot_daily_trades {snap['daily_trades']}",
                ]
                self._send_text(200, "\n".join(lines) + "\n")
                return

            self._send_json(404, {"error": "not found", "path": self.path})

    return HealthHandler


class HealthServer:
    """Background HTTP server. Stop with `stop()` for clean shutdown."""

    def __init__(self, bot: "TradingBot", host: str = "127.0.0.1", port: int = 8000) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return
        try:
            handler = _make_handler(self.bot)
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as exc:
            log.warning(f"Health server bind failed on {self.host}:{self.port}: {exc}")
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="HealthServer", daemon=True
        )
        self._thread.start()
        log.info(f"Health server listening on http://{self.host}:{self.port}/health")

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        log.info("Health server stopped")
