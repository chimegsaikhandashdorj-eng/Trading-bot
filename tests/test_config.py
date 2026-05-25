"""Configuration parsing and validation tests."""
from __future__ import annotations

import importlib

import pytest


def test_safe_int_handles_garbage(monkeypatch):
    monkeypatch.setenv("MT5_LOGIN", "abc-not-a-number")
    import config
    importlib.reload(config)
    assert config.MT5_LOGIN == 0


def test_safe_float_handles_empty(monkeypatch):
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "")
    import config
    importlib.reload(config)
    assert config.MAX_RISK_PER_TRADE == 1.0


def test_safe_bool_parses_truthy(monkeypatch):
    for truthy in ("true", "1", "YES", "on"):
        monkeypatch.setenv("BINANCE_TESTNET", truthy)
        import config
        importlib.reload(config)
        assert config.BINANCE_TESTNET is True
    monkeypatch.setenv("BINANCE_TESTNET", "no")
    importlib.reload(config)
    assert config.BINANCE_TESTNET is False


def test_validate_warns_on_extreme_risk(monkeypatch):
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "50")
    monkeypatch.setenv("MAX_DAILY_LOSS", "99")
    import config
    importlib.reload(config)
    warnings = config.validate(strict=False)
    joined = " ".join(warnings)
    assert "MAX_RISK_PER_TRADE" in joined
    assert "MAX_DAILY_LOSS" in joined


def test_validate_strict_raises(monkeypatch):
    monkeypatch.setenv("CRYPTO_SL_PCT", "-1")
    monkeypatch.setenv("CRYPTO_TP_PCT", "-2")
    import config
    importlib.reload(config)
    with pytest.raises(config.ConfigError):
        config.validate(strict=True)


def test_validate_tp_must_exceed_sl(monkeypatch):
    monkeypatch.setenv("CRYPTO_SL_PCT", "5")
    monkeypatch.setenv("CRYPTO_TP_PCT", "3")
    import config
    importlib.reload(config)
    warnings = config.validate(strict=False)
    assert any("negative expected value" in w for w in warnings)


def test_pip_values_cover_all_forex_symbols():
    import config
    importlib.reload(config)
    for sym in config.FOREX_SYMBOLS:
        assert sym in config.PIP_VALUES, f"{sym} missing pip_value"
        assert sym in config.BREAKEVEN_TRIGGER_POINTS, f"{sym} missing breakeven trigger"
