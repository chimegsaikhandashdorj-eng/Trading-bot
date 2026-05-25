"""Risk manager invariants — these would have caught the original bugs."""
from __future__ import annotations


import pytest



@pytest.fixture
def rm(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from risk.risk_manager import RiskManager
    return RiskManager()


def test_position_size_uses_full_risk_budget(rm):
    """1% of 1000 = $10 risk. At $50k BTC, that should be 0.0002 BTC."""
    decision = rm.evaluate_trade(
        symbol="BTC/USDT", signal="BUY", balance=1000.0,
        current_price=50000.0, technical_strength=1.0,
        sentiment_confirmed=True, is_forex=False,
    )
    assert decision.allowed
    # Sentiment double-penalty bug would have produced 0.00005 here
    assert decision.position_size >= 0.0001


def test_neutral_sentiment_does_not_zero_position(rm):
    """Sentiment-neutral signals must still produce a tradeable size."""
    decision = rm.evaluate_trade(
        symbol="BTC/USDT", signal="BUY", balance=1000.0,
        current_price=50000.0, technical_strength=0.8,
        sentiment_confirmed=False, is_forex=False,
    )
    assert decision.allowed
    assert decision.position_size > 0


def test_low_strength_blocks_trade(rm):
    decision = rm.evaluate_trade(
        symbol="BTC/USDT", signal="BUY", balance=1000.0,
        current_price=50000.0, technical_strength=0.3,
        sentiment_confirmed=True, is_forex=False,
    )
    assert not decision.allowed
    assert "хүч" in decision.reason or "strength" in decision.reason.lower()


def test_zero_price_is_rejected(rm):
    decision = rm.evaluate_trade(
        symbol="BTC/USDT", signal="BUY", balance=1000.0,
        current_price=0.0, technical_strength=1.0,
        sentiment_confirmed=True, is_forex=False,
    )
    assert not decision.allowed


def test_forex_lot_size_within_bounds(rm):
    decision = rm.evaluate_trade(
        symbol="EURUSD", signal="BUY", balance=10000.0,
        current_price=1.1, technical_strength=1.0,
        sentiment_confirmed=True, is_forex=True,
    )
    assert decision.allowed
    assert 0.01 <= decision.position_size <= 10.0


def test_forex_unknown_pip_value_falls_back(rm):
    """Unknown forex symbol uses default $10/pip — should still trade."""
    decision = rm.evaluate_trade(
        symbol="MYSTERY", signal="BUY", balance=10000.0,
        current_price=1.0, technical_strength=1.0,
        sentiment_confirmed=True, is_forex=True,
    )
    assert decision.allowed


def test_breakeven_trigger_xauusd_vs_eurusd(rm):
    """XAUUSD needs a much bigger move than EURUSD to hit breakeven."""
    eurusd_hit = rm.should_move_to_breakeven(
        side="buy", entry_price=1.1000, current_price=1.1100,
        point=0.00001, symbol="EURUSD",
    )
    assert eurusd_hit   # 100 pip move

    gold_small = rm.should_move_to_breakeven(
        side="buy", entry_price=2000.0, current_price=2001.0,
        point=0.01, symbol="XAUUSD",
    )
    assert not gold_small   # $1 move = 100 points < 1000 trigger

    gold_big = rm.should_move_to_breakeven(
        side="buy", entry_price=2000.0, current_price=2010.0,
        point=0.01, symbol="XAUUSD",
    )
    assert gold_big   # $10 move = 1000 points >= trigger


def test_breakeven_zero_point_safe(rm):
    assert not rm.should_move_to_breakeven(
        side="buy", entry_price=100, current_price=200,
        point=0.0, symbol="EURUSD",
    )


def test_slippage_tolerance():
    from risk.risk_manager import RiskManager
    assert RiskManager.slippage_ok(100.0, 100.05)
    assert not RiskManager.slippage_ok(100.0, 101.0)
    assert not RiskManager.slippage_ok(0.0, 1.0)
