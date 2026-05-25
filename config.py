"""
Application configuration loaded from environment variables.

All env-based settings live here so the rest of the codebase can `import config`
and receive validated, typed values. Use `validate()` at startup to surface
misconfiguration early instead of crashing mid-trade.
"""
from __future__ import annotations

import os
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────────────────────────────────
# Typed parsers — never raise on bad input, fall back to default + warn
# ──────────────────────────────────────────────────────────────────────────

def _safe_int(key: str, default: int = 0) -> int:
    raw = os.getenv(key, str(default)).strip()
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _safe_float(key: str, default: float) -> float:
    raw = os.getenv(key, str(default)).strip()
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _safe_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("true", "1", "yes", "on")


# ──────────────────────────────────────────────────────────────────────────
# Exchange credentials
# ──────────────────────────────────────────────────────────────────────────
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY: str = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET: bool = _safe_bool("BINANCE_TESTNET", False)

MT5_LOGIN: int = _safe_int("MT5_LOGIN", 0)
MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
MT5_SERVER: str = os.getenv("MT5_SERVER", "")

# ──────────────────────────────────────────────────────────────────────────
# Sentiment APIs
# ──────────────────────────────────────────────────────────────────────────
X_BEARER_TOKEN: str = os.getenv("X_BEARER_TOKEN", "")
X_API_KEY: str = os.getenv("X_API_KEY", "")
X_API_SECRET: str = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN: str = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET: str = os.getenv("X_ACCESS_SECRET", "")

CRYPTOPANIC_API_KEY: str = os.getenv("CRYPTOPANIC_API_KEY", "")

# ──────────────────────────────────────────────────────────────────────────
# Notifications
# ──────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ──────────────────────────────────────────────────────────────────────────
# Risk Management
# ──────────────────────────────────────────────────────────────────────────
MAX_RISK_PER_TRADE: float = _safe_float("MAX_RISK_PER_TRADE", 1.0)   # % of balance
MAX_DAILY_LOSS: float = _safe_float("MAX_DAILY_LOSS", 3.0)           # % of balance
DEFAULT_LEVERAGE: int = _safe_int("DEFAULT_LEVERAGE", 1)

CRYPTO_SL_PCT: float = _safe_float("CRYPTO_SL_PCT", 2.0)   # 2% stop loss
CRYPTO_TP_PCT: float = _safe_float("CRYPTO_TP_PCT", 4.0)   # 4% take profit (1:2 R:R)

# ──────────────────────────────────────────────────────────────────────────
# Operational endpoints
# ──────────────────────────────────────────────────────────────────────────
HEALTH_HOST: str = os.getenv("HEALTH_HOST", "127.0.0.1")
HEALTH_PORT: int = _safe_int("HEALTH_PORT", 8000)
TELEGRAM_POLLING: bool = _safe_bool("TELEGRAM_POLLING", False)  # /commands feature

# Symbol-aware pip values ($/pip per standard lot)
PIP_VALUES: Dict[str, float] = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 9.09,   # JPY pair — approximate, varies with USDJPY rate
    "XAUUSD": 1.0,    # gold: 1 pip = $0.01, lot=100oz → $1/pip
}

# Symbol-aware breakeven trigger thresholds (in broker points)
BREAKEVEN_TRIGGER_POINTS: Dict[str, int] = {
    "EURUSD": 1000,   # 100 pip
    "GBPUSD": 1000,
    "USDJPY": 1000,
    "XAUUSD": 1000,   # 1000 × 0.01 = $10 move (~0.5% @ $2000)
}

# ──────────────────────────────────────────────────────────────────────────
# Trading universe
# ──────────────────────────────────────────────────────────────────────────
CRYPTO_SYMBOLS: List[str] = ["BTC/USDT", "ETH/USDT"]
FOREX_SYMBOLS: List[str] = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]

TIMEFRAME_PRIMARY: str = "1h"
TIMEFRAME_CONFIRM: str = "4h"

# ──────────────────────────────────────────────────────────────────────────
# Technical analysis thresholds
# ──────────────────────────────────────────────────────────────────────────
RSI_OVERSOLD: int = 30
RSI_OVERBOUGHT: int = 70
RSI_PERIOD: int = 14

# ──────────────────────────────────────────────────────────────────────────
# Sentiment keyword universe
# ──────────────────────────────────────────────────────────────────────────
SENTIMENT_KEYWORDS: Dict[str, List[str]] = {
    "BTC/USDT":  ["bitcoin", "BTC", "#bitcoin", "#BTC", "crypto"],
    "ETH/USDT":  ["ethereum", "ETH", "#ethereum", "#ETH"],
    "XAUUSD":    ["gold", "XAUUSD", "#gold", "goldprice"],
    "EURUSD":    ["eurusd", "EURUSD", "#eurusd", "euro dollar"],
    "GBPUSD":    ["gbpusd", "GBPUSD", "#gbpusd", "pound dollar"],
    "USDJPY":    ["usdjpy", "USDJPY", "#usdjpy"],
}

SENTIMENT_ACCOUNTS: List[str] = [
    "michaeljburry",
    "RaoulGMI",
    "CryptoCapo_",
    "PeterLBrandt",
    "zerohedge",
    "Forbes",
    "Reuters",
]


# ──────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────

class ConfigError(RuntimeError):
    """Raised when a required configuration value is missing or invalid."""


def validate(strict: bool = False) -> List[str]:
    """
    Validate configuration at startup.

    Parameters
    ----------
    strict : bool
        If True, raise ConfigError on any problem. If False, return a list
        of human-readable warnings so the caller can decide.

    Returns
    -------
    List[str]
        Warning messages. Empty list = clean config.
    """
    warnings: List[str] = []

    # Risk bounds
    if not (0 < MAX_RISK_PER_TRADE <= 5):
        warnings.append(
            f"MAX_RISK_PER_TRADE={MAX_RISK_PER_TRADE}% — recommended 0.1–2%"
        )
    if not (0 < MAX_DAILY_LOSS <= 20):
        warnings.append(
            f"MAX_DAILY_LOSS={MAX_DAILY_LOSS}% — recommended 1–10%"
        )
    if CRYPTO_SL_PCT <= 0 or CRYPTO_TP_PCT <= 0:
        warnings.append(
            f"CRYPTO_SL_PCT={CRYPTO_SL_PCT} CRYPTO_TP_PCT={CRYPTO_TP_PCT} — must be > 0"
        )
    if CRYPTO_TP_PCT <= CRYPTO_SL_PCT:
        warnings.append(
            f"CRYPTO_TP_PCT ({CRYPTO_TP_PCT}) <= CRYPTO_SL_PCT ({CRYPTO_SL_PCT}) — negative expected value"
        )

    # Symbol coverage
    for sym in FOREX_SYMBOLS:
        if sym not in PIP_VALUES:
            warnings.append(f"PIP_VALUES missing entry for forex symbol {sym}")
        if sym not in BREAKEVEN_TRIGGER_POINTS:
            warnings.append(f"BREAKEVEN_TRIGGER_POINTS missing entry for {sym}")

    # Connectivity hints (non-fatal — bot can run partial)
    if CRYPTO_SYMBOLS and not (BINANCE_API_KEY and BINANCE_SECRET_KEY):
        warnings.append("Binance creds missing — crypto trading will fail")
    if FOREX_SYMBOLS and MT5_LOGIN == 0:
        warnings.append("MT5_LOGIN not set — forex/gold trading will be skipped")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        warnings.append("Telegram not configured — notifications disabled")

    if strict and warnings:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(warnings))
    return warnings
