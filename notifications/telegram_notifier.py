"""
Telegram notifier with non-blocking background worker.

Notifications are queued and sent in a daemon thread so the trading
loop never blocks on network I/O. HTML messages are escaped and
delivery falls back to plain text on Telegram parse errors.
"""
from __future__ import annotations

import html
import queue
import threading
import time
from typing import Optional

import requests

import config
from utils.logger import get_logger

log = get_logger("Telegram")

# Module-level sentinel to signal worker shutdown
_SHUTDOWN = object()


def _esc(value: object) -> str:
    """Escape `< > &` for Telegram HTML parse_mode."""
    return html.escape(str(value), quote=False)


class TelegramNotifier:
    """
    Background-threaded Telegram notifier.

    `send()` returns immediately — the message is enqueued and dispatched
    by a worker thread. Two retry attempts per message; on Telegram 400
    (parse error) the worker re-sends as plain text.
    """

    def __init__(self) -> None:
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        self._queue: "queue.Queue[tuple[str, str] | object]" = queue.Queue(maxsize=200)
        self._worker: Optional[threading.Thread] = None
        if self.enabled:
            self._worker = threading.Thread(
                target=self._run, name="TelegramWorker", daemon=True
            )
            self._worker.start()
        else:
            log.warning("Telegram тохируулаагүй. Мэдэгдэл идэвхгүй.")

    # ── Public API ────────────────────────────────────────────────────────

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Queue a message. Returns True if accepted, False if disabled or full."""
        if not self.enabled:
            return False
        try:
            self._queue.put_nowait((message, parse_mode))
            return True
        except queue.Full:
            log.warning("Telegram queue full — message dropped")
            return False

    def shutdown(self, timeout: float = 5.0) -> None:
        """Gracefully drain the queue and stop the worker."""
        if not self.enabled or not self._worker:
            return
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:
            pass
        self._worker.join(timeout=timeout)

    # ── Worker ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _SHUTDOWN:
                    return
                if not isinstance(item, tuple) or len(item) != 2:
                    log.warning(f"Telegram worker got bad item: {item!r}")
                    continue
                message, parse_mode = item
                try:
                    self._dispatch(message, parse_mode)
                except Exception as exc:   # never let worker die
                    log.error(f"Telegram worker error: {exc}")
            finally:
                self._queue.task_done()

    def _dispatch(self, message: str, parse_mode: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        for attempt in (1, 2):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    return True
                log.warning(f"Telegram {resp.status_code}: {resp.text[:200]}")
                # 400 — HTML parse error → retry as plain text
                if resp.status_code == 400 and payload.get("parse_mode") == "HTML":
                    payload["parse_mode"] = ""
                    payload["text"] = html.unescape(message)
                    continue
                # Retryable 5xx
                if 500 <= resp.status_code < 600:
                    time.sleep(1.0 * attempt)
                    continue
                return False
            except requests.RequestException as exc:
                log.error(f"Telegram retry={attempt}: {exc}")
                time.sleep(1.0 * attempt)
        return False

    # ── Composed messages ──────────────────────────────────────────────────

    def notify_signal(self, symbol: str, signal: str, price: float,
                      strength: float, sentiment: str, reason: str) -> None:
        emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        msg = (
            f"{emoji} <b>{_esc(signal)} СИГНАЛ</b>\n"
            f"📊 Хос: <code>{_esc(symbol)}</code>\n"
            f"💰 Үнэ: <code>{price:.5f}</code>\n"
            f"💪 Хүч: <code>{strength:.0%}</code>\n"
            f"🐦 X.com: <code>{_esc(sentiment)}</code>\n"
            f"📝 {_esc(reason)}"
        )
        self.send(msg)

    def notify_trade(self, symbol: str, action: str, price: float,
                     volume: float, sl: float = 0, tp: float = 0) -> None:
        emoji = "📈" if action == "BUY" else "📉"
        msg = (
            f"{emoji} <b>АРИЛЖАА НЭЭГДЛЭЭ</b>\n"
            f"📊 Хос: <code>{_esc(symbol)}</code>\n"
            f"🎯 Үйлдэл: <b>{_esc(action)}</b>\n"
            f"💰 Үнэ: <code>{price:.5f}</code>\n"
            f"📦 Хэмжээ: <code>{volume}</code>\n"
            f"🛑 Stop Loss: <code>{sl:.5f}</code>\n"
            f"✅ Take Profit: <code>{tp:.5f}</code>"
        )
        self.send(msg)

    def notify_close(self, symbol: str, profit_loss: float) -> None:
        emoji = "✅" if profit_loss >= 0 else "❌"
        pl_str = f"+${profit_loss:.2f}" if profit_loss >= 0 else f"-${abs(profit_loss):.2f}"
        msg = (
            f"{emoji} <b>АРИЛЖАА ХААГДЛАА</b>\n"
            f"📊 Хос: <code>{_esc(symbol)}</code>\n"
            f"💵 Үр дүн: <b>{pl_str}</b>"
        )
        self.send(msg)

    def notify_error(self, error: str) -> None:
        msg = f"⚠️ <b>АЛДАА</b>\n<code>{_esc(error)}</code>"
        self.send(msg)

    def notify_daily_report(self, balance: float, daily_pnl: float, trades: int) -> None:
        emoji = "📈" if daily_pnl >= 0 else "📉"
        msg = (
            f"{emoji} <b>ӨДРИЙН ТАЙЛАН</b>\n"
            f"💼 Баланс: <code>${balance:.2f}</code>\n"
            f"💰 Өдрийн P&L: <code>${daily_pnl:+.2f}</code>\n"
            f"🔢 Нийт арилжаа: <code>{trades}</code>"
        )
        self.send(msg)
