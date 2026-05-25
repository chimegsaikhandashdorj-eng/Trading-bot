"""Telegram notifier safety — HTML escaping, queue boundedness."""
from __future__ import annotations

from notifications.telegram_notifier import _esc


def test_escape_angle_brackets():
    assert _esc("<script>") == "&lt;script&gt;"


def test_escape_ampersand():
    assert _esc("a & b") == "a &amp; b"


def test_escape_already_safe():
    assert _esc("plain text 123") == "plain text 123"


def test_notifier_disabled_when_no_creds(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr("config.TELEGRAM_CHAT_ID", "")
    from notifications.telegram_notifier import TelegramNotifier
    n = TelegramNotifier()
    assert n.enabled is False
    # send must short-circuit, not raise
    assert n.send("anything") is False
