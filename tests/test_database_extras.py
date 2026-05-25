"""Tests for get_open_trades / mark_trade_orphan (added for reconciliation)."""
from __future__ import annotations

import pytest


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from utils import database
    database.init_db()
    return database


def test_get_open_trades_returns_only_open(db):
    t1 = db.open_trade("BTC/USDT", "buy", 50000, 0.001, "binance")
    t2 = db.open_trade("ETH/USDT", "sell", 3000, 0.01, "binance", ticket="999")
    db.close_trade(t1, 5.0)
    open_trades = db.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["id"] == t2


def test_get_open_trades_filters_by_exchange(db):
    db.open_trade("BTC/USDT", "buy", 50000, 0.001, "binance")
    db.open_trade("EURUSD", "buy", 1.1, 0.1, "mt5", ticket="12345")
    binance_only = db.get_open_trades(exchange="binance")
    mt5_only = db.get_open_trades(exchange="mt5")
    assert len(binance_only) == 1
    assert binance_only[0]["exchange"] == "binance"
    assert len(mt5_only) == 1
    assert mt5_only[0]["ticket"] == "12345"


def test_mark_trade_orphan(db):
    tid = db.open_trade("XAUUSD", "buy", 2000, 0.1, "mt5", ticket="999")
    db.mark_trade_orphan(tid)
    assert db.get_open_trades() == []
