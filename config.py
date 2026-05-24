import os
from dotenv import load_dotenv

load_dotenv()

# --- Binance ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

# --- MetaTrader 5 ---
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
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
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "1.0"))   # % of balance
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "3.0"))            # % of balance
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "1"))

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
