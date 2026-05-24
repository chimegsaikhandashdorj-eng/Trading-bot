import os
from dotenv import load_dotenv

load_dotenv()


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


# --- Binance ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

# --- MetaTrader 5 ---
MT5_LOGIN = _safe_int("MT5_LOGIN", 0)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

# --- X.com ---
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
X_API_KEY = os.getenv("X_API_KEY", "")
X_API_SECRET = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET", "")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- CryptoPanic (X.com fallback) ---
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")

# --- Risk Management ---
MAX_RISK_PER_TRADE = _safe_float("MAX_RISK_PER_TRADE", 1.0)   # % of balance
MAX_DAILY_LOSS = _safe_float("MAX_DAILY_LOSS", 3.0)           # % of balance
DEFAULT_LEVERAGE = _safe_int("DEFAULT_LEVERAGE", 1)

# Crypto SL/TP — % of entry price (Binance OCO-д ашиглана)
CRYPTO_SL_PCT = _safe_float("CRYPTO_SL_PCT", 2.0)   # 2% stop loss
CRYPTO_TP_PCT = _safe_float("CRYPTO_TP_PCT", 4.0)   # 4% take profit (1:2 R:R)

# Symbol-аас хамаарсан pip values ($/pip/standard lot)
PIP_VALUES = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 9.09,   # ойролцоо, JPY pair
    "XAUUSD": 1.0,    # gold-ийн 1 pip = $0.01, lot=100oz → $1/pip
}

# Symbol-аас хамаарсан breakeven trigger (point-оор)
BREAKEVEN_TRIGGER_POINTS = {
    "EURUSD": 1000,   # 100 pip
    "GBPUSD": 1000,
    "USDJPY": 1000,
    "XAUUSD": 50000,  # ~$5 хөдөлгөөн
}

# --- Trading Symbols ---
CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT"]
FOREX_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]

# --- Timeframes ---
TIMEFRAME_PRIMARY = "1h"
TIMEFRAME_CONFIRM = "4h"

# --- Technical Analysis thresholds ---
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_PERIOD = 14

# --- X.com sentiment keywords ---
SENTIMENT_KEYWORDS = {
    "BTC/USDT":  ["bitcoin", "BTC", "#bitcoin", "#BTC", "crypto"],
    "ETH/USDT":  ["ethereum", "ETH", "#ethereum", "#ETH"],
    "XAUUSD":    ["gold", "XAUUSD", "#gold", "goldprice"],
    "EURUSD":    ["eurusd", "EURUSD", "#eurusd", "euro dollar"],
    "GBPUSD":    ["gbpusd", "GBPUSD", "#gbpusd", "pound dollar"],
    "USDJPY":    ["usdjpy", "USDJPY", "#usdjpy"],
}

SENTIMENT_ACCOUNTS = [
    "michaeljburry",
    "RaoulGMI",
    "CryptoCapo_",
    "PeterLBrandt",
    "zerohedge",
    "Forbes",
    "Reuters",
]
