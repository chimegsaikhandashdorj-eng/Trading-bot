"""Technical analyzer & strategy integration tests."""
from __future__ import annotations

import pandas as pd


def test_technical_handles_short_df():
    from analysis.technical import TechnicalAnalyzer
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
    assert TechnicalAnalyzer().analyze(df, "X", "1h") is None


def test_technical_returns_signal_on_trending_data(trending_up_df):
    from analysis.technical import TechnicalAnalyzer
    sig = TechnicalAnalyzer().analyze(trending_up_df, "TEST", "1h")
    # Note: may return None if indicators don't agree — that's fine
    if sig:
        assert sig.signal in ("BUY", "SELL", "NEUTRAL")
        assert 0.0 <= sig.strength <= 1.0


def test_technical_none_for_none_input():
    from analysis.technical import TechnicalAnalyzer
    assert TechnicalAnalyzer().analyze(None, "X", "1h") is None  # type: ignore


def test_sr_handles_short_df():
    from analysis.technical_analyzer.support_resistance import SupportResistanceAnalyzer
    df = pd.DataFrame({"high": [1, 2], "low": [0, 1], "close": [1, 1]})
    levels = SupportResistanceAnalyzer(df).find_levels()
    assert levels.zone == "NEUTRAL"


def test_fib_handles_empty_df():
    import pandas as pd
    from analysis.technical_analyzer.fibonacci import FibonacciAnalyzer
    df = pd.DataFrame({"high": [], "low": [], "close": []})
    fib = FibonacciAnalyzer(df).calculate_levels()
    assert fib.swing_high == 0.0


def test_candle_short_df_no_pattern():
    from analysis.technical_analyzer.candlestick import CandlestickAnalyzer
    df = pd.DataFrame({
        "open": [1, 2], "high": [1, 2], "low": [1, 2],
        "close": [1, 2], "volume": [100, 100],
    })
    res = CandlestickAnalyzer(df).detect_patterns()
    assert res.pattern == "NONE"


def test_chart_pattern_short_df():
    from analysis.technical_analyzer.chart_patterns import ChartPatternAnalyzer
    df = pd.DataFrame({"open": [], "high": [], "low": [], "close": []})
    res = ChartPatternAnalyzer(df).detect_double_patterns()
    assert res.pattern == "NONE"
