"""
Telegram bot commands listener (long-polling `getUpdates`).

Stays inside the existing `requests` dependency — no `python-telegram-bot`.
Only the configured `TELEGRAM_CHAT_ID` is authorized; messages from any other
chat are ignored.

Supported commands
------------------
- `/status`     — paused?, connections, open positions, daily P&L
- `/positions`  — open positions ledger
- `/pause`      — stop opening new positions
- `/resume`     — resume opening new positions
- `/help`       — list commands
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

import requests

import config
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import TradingBot

log = get_logger("TelegramCmd")


class TelegramCommandListener:
    """Long-polling Telegram command handler. Runs in a daemon thread."""

    POLL_TIMEOUT = 25   # seconds — Telegram long-polling

    def __init__(self, bot: "TradingBot") -> None:
        self.bot = bot
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = str(config.TELEGRAM_CHAT_ID)
        self.enabled = bool(self.token and self.chat_id) and config.TELEGRAM_POLLING
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset: int = 0

    def start(self) -> None:
        if not self.enabled:
            log.info("Telegram commands disabled (set TELEGRAM_POLLING=true to enable)")
            return
        self._thread = threading.Thread(
            target=self._run, name="TelegramCmdListener", daemon=True
        )
        self._thread.start()
        log.info("Telegram command listener started")

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ── Polling loop ────────────────────────────────────────────────────

    def _run(self) -> None:
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        while not self._stopped.is_set():
            try:
                params = {
                    "timeout": self.POLL_TIMEOUT,
                    "offset": self._offset,
                    "allowed_updates": ["message"],
                }
                resp = requests.get(url, params=params, timeout=self.POLL_TIMEOUT + 5)
                if resp.status_code != 200:
                    log.warning(f"getUpdates {resp.status_code}: {resp.text[:200]}")
                    time.sleep(5)
                    continue
                data = resp.json()
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle_update(update)
            except requests.RequestException as exc:
                log.debug(f"getUpdates network error: {exc}")
                time.sleep(2)
            except Exception as exc:
                log.error(f"command listener error: {exc}")
                time.sleep(2)

    # ── Command dispatch ────────────────────────────────────────────────

    def _handle_update(self, update: Dict[str, Any]) -> None:
        msg = update.get("message")
        if not msg:
            return
        # Authorize: ignore anything not from configured chat
        chat = msg.get("chat", {})
        if str(chat.get("id")) != self.chat_id:
            log.warning(f"unauthorized chat: {chat.get('id')}")
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        cmd = text.split()[0].lower().split("@")[0]   # /status@botname → /status

        if cmd == "/status":
            self._reply(self._render_status())
        elif cmd == "/positions":
            self._reply(self._render_positions())
        elif cmd == "/pause":
            self.bot.pause()
            self._reply("⏸ Bot paused — no new entries.")
        elif cmd == "/resume":
            self.bot.resume()
            self._reply("▶ Bot resumed.")
        elif cmd in ("/help", "/start"):
            self._reply(
                "Available commands:\n"
                "/status — runtime status\n"
                "/positions — open positions\n"
                "/pause — stop new entries\n"
                "/resume — resume entries\n"
                "/help — this message"
            )
        else:
            self._reply(f"Unknown command: {cmd}. Try /help.")

    # ── Renderers ───────────────────────────────────────────────────────

    def _render_status(self) -> str:
        snap = self.bot.status_snapshot()
        paused = "PAUSED ⏸" if snap["paused"] else "RUNNING ▶"
        return (
            f"<b>STATUS</b>: {paused}\n"
            f"Binance: {'✅' if snap['binance_connected'] else '❌'}\n"
            f"MT5: {'✅' if snap['mt5_connected'] else '❌'}\n"
            f"Open positions: <code>{snap['open_positions']}</code>\n"
            f"Daily P&amp;L: <code>${snap['daily_pnl']:+.2f}</code>\n"
            f"Trades today: <code>{snap['daily_trades']}</code>"
        )

    def _render_positions(self) -> str:
        # `snapshot()` copies under lock, safe to iterate in this thread.
        snapshot = self.bot.open_positions.snapshot()
        if not snapshot:
            return "No open positions."
        lines = ["<b>OPEN POSITIONS</b>"]
        for tid, p in snapshot:
            ex = p.get("exchange", "?")
            symbol = p.get("symbol", "?")
            side = p.get("side", "?")
            entry = p.get("entry", 0.0)
            lines.append(
                f"• #{tid} [{ex}] {symbol} {side.upper()} @ {entry:.5f}"
            )
        return "\n".join(lines)

    def _reply(self, text: str) -> None:
        """Send a reply via the main notifier (uses the same retry/queue logic)."""
        self.bot.notifier.send(text)
