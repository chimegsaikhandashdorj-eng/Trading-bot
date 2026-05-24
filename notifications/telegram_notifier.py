import asyncio
import requests
from typing import Optional
import config
from utils.logger import get_logger

log = get_logger("Telegram")


class TelegramNotifier:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            log.warning("Telegram тохируулаагүй. Мэдэгдэл идэвхгүй.")

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
            }, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            log.error(f"Telegram мэдэгдэл алдаа: {e}")
            return False

    def notify_signal(self, symbol: str, signal: str, price: float,
                      strength: float, sentiment: str, reason: str):
        emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        msg = (
            f"{emoji} <b>{signal} СИГНАЛ</b>\n"
            f"📊 Хос: <code>{symbol}</code>\n"
            f"💰 Үнэ: <code>{price:.5f}</code>\n"
            f"💪 Хүч: <code>{strength:.0%}</code>\n"
            f"🐦 X.com: <code>{sentiment}</code>\n"
            f"📝 {reason}"
        )
        self.send(msg)

    def notify_trade(self, symbol: str, action: str, price: float,
                     volume: float, sl: float = 0, tp: float = 0):
        emoji = "📈" if action == "BUY" else "📉"
        msg = (
            f"{emoji} <b>АРИЛЖАА НЭЭГДЛЭЭ</b>\n"
            f"📊 Хос: <code>{symbol}</code>\n"
            f"🎯 Үйлдэл: <b>{action}</b>\n"
            f"💰 Үнэ: <code>{price:.5f}</code>\n"
            f"📦 Хэмжээ: <code>{volume}</code>\n"
            f"🛑 Stop Loss: <code>{sl:.5f}</code>\n"
            f"✅ Take Profit: <code>{tp:.5f}</code>"
        )
        self.send(msg)

    def notify_close(self, symbol: str, profit_loss: float):
        emoji = "✅" if profit_loss >= 0 else "❌"
        pl_str = f"+${profit_loss:.2f}" if profit_loss >= 0 else f"-${abs(profit_loss):.2f}"
        msg = (
            f"{emoji} <b>АРИЛЖАА ХААГДЛАА</b>\n"
            f"📊 Хос: <code>{symbol}</code>\n"
            f"💵 Үр дүн: <b>{pl_str}</b>"
        )
        self.send(msg)

    def notify_error(self, error: str):
        msg = f"⚠️ <b>АЛДАА</b>\n<code>{error}</code>"
        self.send(msg)

    def notify_daily_report(self, balance: float, daily_pnl: float, trades: int):
        emoji = "📈" if daily_pnl >= 0 else "📉"
        msg = (
            f"{emoji} <b>ӨДРИЙН ТАЙЛАН</b>\n"
            f"💼 Баланс: <code>${balance:.2f}</code>\n"
            f"💰 Өдрийн P&L: <code>${daily_pnl:+.2f}</code>\n"
            f"🔢 Нийт арилжаа: <code>{trades}</code>"
        )
        self.send(msg)
