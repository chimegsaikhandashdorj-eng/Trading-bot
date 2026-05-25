# Trading Bot — Forex / Gold / BTC / ETH

Multi-market trading bot combining technical analysis, social-sentiment confirmation, and disciplined risk management.

[![CI](https://github.com/chimegsaikhandashdorj-eng/Trading-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/chimegsaikhandashdorj-eng/Trading-bot/actions)

## Markets

| Asset class | Exchange | Symbols |
|-------------|----------|---------|
| Crypto      | Binance (ccxt) | `BTC/USDT`, `ETH/USDT` |
| Forex/Gold  | MetaTrader 5   | `XAUUSD`, `EURUSD`, `GBPUSD`, `USDJPY` |

## Strategy stack

1. **Basic TA (40%)** — RSI, MACD (golden/death cross), EMA 20/50/200 trend, Bollinger Bands
2. **Advanced TA (30%)** — support/resistance zones, Fibonacci golden zone, candlestick patterns, double top/bottom
3. **Sentiment (30%)** — X.com (Twitter API v2) with CryptoPanic fallback

A trade fires only when **all three** layers agree and the combined confidence ≥ 0.55. Strategy is multi-timeframe — `1h` signal must be confirmed by `4h` direction.

## Risk management

- Per-trade risk capped at `MAX_RISK_PER_TRADE` (default 1% of balance)
- Daily loss circuit-breaker at `MAX_DAILY_LOSS` (default 3%) — restart-safe (SQLite-backed)
- Symbol-aware pip values and breakeven triggers (XAUUSD ≠ EURUSD)
- Mandatory stop-loss on every order (Binance OCO + MT5 native SL)
- Auto-move SL to breakeven after profit milestone
- Slippage tolerance check (0.1%)
- Spread filter for forex (per-symbol thresholds)

## Setup

### 1. Clone & install

```powershell
git clone https://github.com/chimegsaikhandashdorj-eng/Trading-bot.git
cd Trading-bot
pip install -r requirements.txt
```

**TA-Lib (optional, Windows)** — `pip install` won't compile. Either:
- `pip install --index-url https://pypi.anaconda.org/ranaroussi/simple ta-lib`
- or download a pre-built wheel from [cgohlke/talib-build](https://github.com/cgohlke/talib-build/releases)

Without TA-Lib the candle analyzer falls back to a hand-coded recognizer (same patterns, slightly slower).

### 2. Configure credentials

```powershell
python setup.py    # copies .env.example → .env
```

Fill in `.env`:

| Variable | Required for | Where to get it |
|----------|--------------|-----------------|
| `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` | crypto trading | binance.com → API Management |
| `BINANCE_TESTNET` | optional | `true` to use Binance testnet |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | forex/gold | MetaTrader 5 broker dashboard |
| `X_BEARER_TOKEN` (+ keys) | sentiment | developer.twitter.com |
| `CRYPTOPANIC_API_KEY` | sentiment fallback | cryptopanic.com/developers/api |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | notifications | @BotFather + @userinfobot |
| `MAX_RISK_PER_TRADE` | risk | % of balance per trade (default 1) |
| `MAX_DAILY_LOSS` | risk | % of balance per day (default 3) |
| `CRYPTO_SL_PCT` / `CRYPTO_TP_PCT` | risk | crypto SL/TP % (default 2 / 4) |

### 3. Validate before going live

```powershell
# Run unit tests
pytest tests/

# Backtest on historical data
python backtest.py --symbol BTC/USDT --days 90 --sl 2 --tp 4

# Paper-trade with Binance testnet for at least 2 weeks
# Set BINANCE_TESTNET=true in .env

# Live
python main.py
```

## Architecture

```
trading_bot/
├── main.py                          # composition root + scheduler
├── config.py                        # env-validated settings
├── backtest.py                      # bar-by-bar replay engine
├── setup.py                         # interactive .env wizard
├── exchanges/
│   ├── binance_client.py            # ccxt wrapper (spot, SL via STOP_LOSS_LIMIT)
│   └── mt5_client.py                # MetaTrader 5 wrapper (forex/gold)
├── strategy/
│   └── strategy.py                  # weighted basic+advanced+sentiment combiner
├── analysis/
│   ├── technical.py                 # RSI/MACD/EMA/BB
│   ├── sentiment.py                 # X.com + CryptoPanic, thread-safe cache
│   └── technical_analyzer/          # advanced TA submodules
│       ├── support_resistance.py    # ATR-clustered SR zones
│       ├── fibonacci.py             # golden zone retracement
│       ├── candlestick.py           # TA-Lib + manual patterns
│       └── chart_patterns.py        # double top/bottom + wick rejection
├── risk/risk_manager.py             # position sizing, daily loss gate, breakeven
├── notifications/telegram_notifier.py  # background-threaded Telegram
├── utils/
│   ├── database.py                  # SQLite trades + daily_stats
│   └── logger.py                    # rotating file + colored console
└── tests/                           # pytest — 46 tests
```

## Scheduler

- `:01:30` each hour — analyze all symbols (past candle has settled)
- every 5 min — move SL to breakeven if profit reached
- every 2 min — sync broker-side closures into SQLite
- `23:55` daily — Telegram daily report

## Telegram messages

The notifier runs in a daemon thread — `send()` is non-blocking. Two retries per message, plain-text fallback on Telegram parse errors, queue capped at 200 to bound memory.

## Safety checklist before live trading

- [ ] Run `pytest tests/` — all green
- [ ] Run `python backtest.py` on ≥ 90 days for each symbol you trade
- [ ] Run with `BINANCE_TESTNET=true` for at least 2 weeks
- [ ] Run on an MT5 demo account
- [ ] Confirm Telegram notifications arrive (sends `"Trading Bot started!"` on launch)
- [ ] Manually verify SL/TP appear on the exchange after the first signal
- [ ] Confirm `MAX_DAILY_LOSS` triggers in a simulated bad day

## License

Personal use. No warranty — trading carries risk of total loss.
