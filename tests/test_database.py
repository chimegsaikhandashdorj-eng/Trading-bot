"""Persistence layer tests — open/close trade, daily aggregation."""
from __future__ import annotations

import pytest


@pytest.fixture
def db_module(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from utils import database
    database.init_db()
    return database


def test_open_then_close_writes_pnl(db_module):
    tid = db_module.open_trade("BTC/USDT", "buy", 50000.0, 0.001, "binance")
    assert tid > 0
    db_module.close_trade(tid, 12.5)
    stats = db_module.get_daily_stats()
    assert stats["total_pnl"] == 12.5
    assert stats["trade_count"] == 1
    assert stats["win_count"] == 1


def test_loss_is_aggregated(db_module):
    t1 = db_module.open_trade("ETH/USDT", "sell", 3000, 0.01, "binance")
    t2 = db_module.open_trade("ETH/USDT", "buy", 3000, 0.01, "binance")
    db_module.close_trade(t1, -8.0)
    db_module.close_trade(t2, +3.0)
    assert db_module.get_daily_loss() == 5.0   # net loss = abs(min(-5, 0))


def test_winners_only_means_zero_loss(db_module):
    tid = db_module.open_trade("BTC/USDT", "buy", 50000, 0.001, "binance")
    db_module.close_trade(tid, 25.0)
    assert db_module.get_daily_loss() == 0.0


def test_empty_stats_default(db_module):
    stats = db_module.get_daily_stats()
    assert stats == {"date": stats["date"], "total_pnl": 0.0, "trade_count": 0, "win_count": 0}
