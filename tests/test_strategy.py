"""Strategy combiner — integration tests over the three-layer ensemble."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from analysis.sentiment import SentimentSignal


def _neutral_sentiment(symbol="BTC/USDT"):
    return SentimentSignal(
        symbol=symbol, sentiment="NEUTRAL", score=0.0,
        tweet_count=0, positive_count=0, negative_count=0,
        confirm_trade=False, source="none",
    )


def _bullish_sentiment(symbol="BTC/USDT"):
    return SentimentSignal(
        symbol=symbol, sentiment="BULLISH", score=0.6,
        tweet_count=10, positive_count=8, negative_count=2,
        confirm_trade=True, source="x.com",
    )


def _bearish_sentiment(symbol="BTC/USDT"):
    return SentimentSignal(
        symbol=symbol, sentiment="BEARISH", score=-0.6,
        tweet_count=10, positive_count=2, negative_count=8,
        confirm_trade=True, source="x.com",
    )


@pytest.fixture
def strategy(monkeypatch):
    """Strategy with sentiment auto-patched to NEUTRAL (no live API calls)."""
    monkeypatch.setattr("config.X_BEARER_TOKEN", "")
    monkeypatch.setattr("config.CRYPTOPANIC_API_KEY", "")
    from analysis.sentiment import _cache
    _cache.clear()
    from strategy.strategy import CombinedStrategy
    return CombinedStrategy()


def test_returns_none_on_flat_data(strategy, flat_df):
    """Flat market → basic TA NEUTRAL → no signal."""
    result = strategy.evaluate(flat_df, None, "TEST")
    assert result is None


def test_sentiment_score_matches_signal(strategy):
    score, reason = strategy._sentiment_score("BUY", _bullish_sentiment())
    assert score == strategy.SENTIMENT_WEIGHT
    assert "нийцлээ" in reason


def test_sentiment_score_contradicts_signal(strategy):
    score, reason = strategy._sentiment_score("BUY", _bearish_sentiment())
    assert score < 0
    assert "зөрчилдлөө" in reason


def test_sentiment_score_neutral_small_positive(strategy):
    score, _ = strategy._sentiment_score("BUY", _neutral_sentiment())
    assert 0 < score < strategy.SENTIMENT_WEIGHT


def test_sentiment_score_no_data_small_positive(strategy):
    score, reason = strategy._sentiment_score("BUY", None)
    assert score > 0
    assert "байхгүй" in reason


def test_confidence_threshold_blocks_weak_signals(strategy, trending_up_df):
    """Mock everything weak — combined confidence below threshold returns None."""
    from analysis.technical import TechnicalSignal
    from analysis.technical_analyzer import AdvancedTAScore

    weak = TechnicalSignal(
        symbol="X", timeframe="1h", signal="BUY",
        strength=0.5, rsi=35, macd_signal="BUY", ma_trend="UP",
        bb_position="LOWER", current_price=100.0,
    )
    adv = AdvancedTAScore(
        signal="NEUTRAL", score=0.0, sr_zone="NEUTRAL",
        fib_in_golden=False, candle_pattern="NONE",
        chart_pattern="NONE", sr_htf_ok=True,
    )
    with patch.object(strategy.basic_ta, "analyze", return_value=weak), \
         patch("strategy.strategy.generate_ta_score", return_value=adv), \
         patch.object(strategy.sentiment, "analyze", return_value=_neutral_sentiment()):
        result = strategy.evaluate(trending_up_df, None, "X")
    # 0.5*0.4 + 0 + 0.05 = 0.25 < 0.55
    assert result is None


def test_strong_alignment_passes(strategy, trending_up_df):
    from analysis.technical import TechnicalSignal
    from analysis.technical_analyzer import AdvancedTAScore

    strong = TechnicalSignal(
        symbol="X", timeframe="1h", signal="BUY",
        strength=1.0, rsi=20, macd_signal="BUY", ma_trend="UP",
        bb_position="LOWER", current_price=100.0,
    )
    adv = AdvancedTAScore(
        signal="BUY", score=1.0, sr_zone="SUPPORT_ZONE",
        fib_in_golden=True, candle_pattern="HAMMER",
        chart_pattern="NONE", sr_htf_ok=True,
    )
    with patch.object(strategy.basic_ta, "analyze", return_value=strong), \
         patch("strategy.strategy.generate_ta_score", return_value=adv), \
         patch.object(strategy.sentiment, "analyze", return_value=_bullish_sentiment()):
        result = strategy.evaluate(trending_up_df, None, "X")
    assert result is not None
    assert result.final_signal == "BUY"
    assert result.confidence >= 0.55


def test_contradicting_advanced_ta_blocks(strategy, trending_up_df):
    from analysis.technical import TechnicalSignal
    from analysis.technical_analyzer import AdvancedTAScore

    basic = TechnicalSignal(
        symbol="X", timeframe="1h", signal="BUY",
        strength=0.9, rsi=25, macd_signal="BUY", ma_trend="UP",
        bb_position="LOWER", current_price=100.0,
    )
    contra = AdvancedTAScore(
        signal="SELL", score=0.8, sr_zone="RESISTANCE_ZONE",
        fib_in_golden=False, candle_pattern="SHOOTING_STAR",
        chart_pattern="DOUBLE_TOP", sr_htf_ok=True,
    )
    with patch.object(strategy.basic_ta, "analyze", return_value=basic), \
         patch("strategy.strategy.generate_ta_score", return_value=contra), \
         patch.object(strategy.sentiment, "analyze", return_value=_bullish_sentiment()):
        result = strategy.evaluate(trending_up_df, None, "X")
    assert result is None
