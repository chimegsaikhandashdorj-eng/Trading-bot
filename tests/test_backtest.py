"""Backtest engine smoke + metric tests."""
from __future__ import annotations

import pytest

from backtest import BacktestResult, Trade, _check_exit, _finalize


def _trade(signal="BUY", entry=100.0):
    return Trade(
        signal=signal, entry_bar=0, entry=entry, exit_bar=0,
        exit=entry, exit_reason="open", pnl_pct=0.0, bars=0,
    )


def test_sl_hits_first_when_both_in_bar():
    """If a bar covers both SL and TP, pessimistic exit is SL."""
    t = _trade("BUY", 100.0)
    sl, tp, price, reason = _check_exit(t, high=110, low=90, sl_pct=2, tp_pct=4)
    assert sl and not tp
    assert reason == "sl"
    assert price == 98.0


def test_tp_hits_alone():
    t = _trade("BUY", 100.0)
    sl, tp, price, reason = _check_exit(t, high=105, low=99, sl_pct=2, tp_pct=4)
    assert tp and not sl
    assert price == 104.0


def test_no_exit_within_range():
    t = _trade("BUY", 100.0)
    sl, tp, _, _ = _check_exit(t, high=101, low=99, sl_pct=2, tp_pct=4)
    assert not sl and not tp


def test_sell_sl_above_entry():
    t = _trade("SELL", 100.0)
    sl, tp, price, _ = _check_exit(t, high=103, low=99, sl_pct=2, tp_pct=4)
    assert sl
    assert price == 102.0


def test_finalize_computes_pnl_pct():
    t = _trade("BUY", 100.0)
    _finalize(t, exit_bar=10, exit_price=105.0, reason="tp")
    assert t.bars == 10
    assert t.pnl_pct == 5.0
    assert t.exit_reason == "tp"


def test_result_metrics_with_mixed_trades():
    r = BacktestResult(symbol="X", days=10)
    for pnl in (2, 3, -1, 4, -2):
        t = _trade("BUY", 100.0)
        _finalize(t, 1, 100 + pnl, "tp" if pnl > 0 else "sl")
        r.trades.append(t)
    assert r.n == 5
    assert r.win_rate == 0.6
    assert r.profit_factor == pytest.approx(3.0)


def test_max_drawdown_calculation():
    r = BacktestResult(symbol="X", days=10)
    # +5, +5, -8, -3 → peak=10, equity hits -1, max DD = 11
    for pnl in (5, 5, -8, -3):
        t = _trade("BUY", 100.0)
        _finalize(t, 1, 100 + pnl, "x")
        r.trades.append(t)
    assert r.max_drawdown_pct == 11.0
