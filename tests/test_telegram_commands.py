"""Telegram /commands listener — authorization + dispatch tests."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_bot():
    bot = MagicMock()
    bot.notifier.send = MagicMock()
    bot.status_snapshot.return_value = {
        "paused": False,
        "binance_connected": True,
        "mt5_connected": True,
        "open_positions": 2,
        "daily_pnl": -5.0,
        "daily_trades": 4,
    }
    bot.open_positions = {
        1: {"exchange": "binance", "symbol": "BTC/USDT", "side": "buy", "entry": 50000.0},
        2: {"exchange": "mt5", "symbol": "EURUSD", "side": "sell", "entry": 1.1},
    }
    return bot


@pytest.fixture
def listener(monkeypatch, fake_bot):
    monkeypatch.setattr("config.TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setattr("config.TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr("config.TELEGRAM_POLLING", True)
    from notifications.telegram_commands import TelegramCommandListener
    return TelegramCommandListener(fake_bot)


def _update(text: str, chat_id: str = "12345"):
    return {
        "update_id": 1,
        "message": {"text": text, "chat": {"id": chat_id}},
    }


def test_status_dispatch(listener, fake_bot):
    listener._handle_update(_update("/status"))
    fake_bot.notifier.send.assert_called_once()
    msg = fake_bot.notifier.send.call_args[0][0]
    assert "RUNNING" in msg
    assert "Binance" in msg


def test_pause_dispatch(listener, fake_bot):
    listener._handle_update(_update("/pause"))
    fake_bot.pause.assert_called_once()


def test_resume_dispatch(listener, fake_bot):
    listener._handle_update(_update("/resume"))
    fake_bot.resume.assert_called_once()


def test_positions_dispatch(listener, fake_bot):
    listener._handle_update(_update("/positions"))
    msg = fake_bot.notifier.send.call_args[0][0]
    assert "BTC/USDT" in msg
    assert "EURUSD" in msg


def test_unauthorized_chat_ignored(listener, fake_bot):
    listener._handle_update(_update("/status", chat_id="99999"))
    fake_bot.notifier.send.assert_not_called()
    fake_bot.pause.assert_not_called()


def test_non_command_ignored(listener, fake_bot):
    listener._handle_update(_update("hello"))
    fake_bot.notifier.send.assert_not_called()


def test_unknown_command(listener, fake_bot):
    listener._handle_update(_update("/foo"))
    msg = fake_bot.notifier.send.call_args[0][0]
    assert "Unknown" in msg


def test_help_command(listener, fake_bot):
    listener._handle_update(_update("/help"))
    msg = fake_bot.notifier.send.call_args[0][0]
    assert "/status" in msg and "/pause" in msg


def test_command_with_bot_suffix(listener, fake_bot):
    """Telegram appends @botname in groups — must still match."""
    listener._handle_update(_update("/status@TradingBot"))
    fake_bot.notifier.send.assert_called_once()
