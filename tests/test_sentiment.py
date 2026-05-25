"""Sentiment scoring tests — spam filter, negation handling, cache."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def analyzer(monkeypatch):
    monkeypatch.setattr("config.X_BEARER_TOKEN", "")
    monkeypatch.setattr("config.CRYPTOPANIC_API_KEY", "")
    from analysis.sentiment import SentimentAnalyzer, _cache
    _cache.clear()
    return SentimentAnalyzer()


def test_bullish_text_scores_positive(analyzer):
    assert analyzer._score_text("Massive bull rally incoming, breakout confirmed") > 0


def test_bearish_text_scores_negative(analyzer):
    assert analyzer._score_text("Crash and dump, big sell-off ahead") < 0


def test_negation_flips_polarity(analyzer):
    # "not bullish" must NOT score as bullish
    pos = analyzer._score_text("price is bullish today")
    neg = analyzer._score_text("price is not bullish today")
    assert pos > 0
    assert neg <= 0


def test_spam_returns_zero(analyzer):
    assert analyzer._score_text("Free crypto airdrop, dm me on telegram.me/xxx") == 0.0


def test_empty_text_returns_zero(analyzer):
    assert analyzer._score_text("hello world neutral words") == 0.0


def test_score_to_signal_thresholds(analyzer):
    assert analyzer._score_to_signal(0.5) == "BULLISH"
    assert analyzer._score_to_signal(-0.5) == "BEARISH"
    assert analyzer._score_to_signal(0.0) == "NEUTRAL"
    assert analyzer._score_to_signal(0.10) == "NEUTRAL"


def test_cache_returns_same_signal(analyzer):
    from analysis.sentiment import SentimentSignal
    sig = SentimentSignal(
        symbol="BTC/USDT", sentiment="BULLISH", score=0.5,
        tweet_count=10, positive_count=8, negative_count=2,
        confirm_trade=True, source="x.com",
    )
    analyzer._set_cache("BTC/USDT", sig)
    assert analyzer._get_cached("BTC/USDT") is sig


def test_cache_expires(analyzer, monkeypatch):
    from analysis import sentiment
    monkeypatch.setattr(sentiment, "_CACHE_TTL", 0.01)
    sig = sentiment.SentimentSignal(
        symbol="X", sentiment="NEUTRAL", score=0.0,
        tweet_count=0, positive_count=0, negative_count=0,
        confirm_trade=False, source="none",
    )
    analyzer._set_cache("X", sig)
    time.sleep(0.02)
    assert analyzer._get_cached("X") is None
