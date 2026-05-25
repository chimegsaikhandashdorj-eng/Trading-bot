# Repo notes for Claude

This file primes Claude with everything it needs to be productive in this repo without re-deriving context every session.

## What this is

Multi-market trading bot: Binance (crypto) + MT5 (forex/gold) + X.com sentiment + TA. Single-process Python 3.12 app, scheduler-driven, SQLite-backed.

## Where things live

- **Composition root**: `main.py` — `TradingBot` class wires exchanges, strategy, risk, notifier
- **Config**: `config.py` — env-driven; call `config.validate()` to surface issues at startup
- **Strategy combiner**: `strategy/strategy.py` — weights basic TA (40%) + advanced TA (30%) + sentiment (30%)
- **Basic TA**: `analysis/technical.py` — RSI/MACD/EMA/BB
- **Advanced TA**: `analysis/technical_analyzer/` — SR zones, Fibonacci, candlesticks, double top/bottom
- **Sentiment**: `analysis/sentiment.py` — X.com primary, CryptoPanic fallback, 30-min thread-safe cache
- **Risk**: `risk/risk_manager.py` — position sizing, daily loss gate, breakeven trigger
- **Exchanges**: `exchanges/binance_client.py` (ccxt spot + STOP_LOSS_LIMIT), `exchanges/mt5_client.py` (MetaTrader 5 native)
- **Persistence**: `utils/database.py` — SQLite `trades` and `daily_stats` tables
- **Telegram**: `notifications/telegram_notifier.py` — background daemon worker, non-blocking
- **Tests**: `tests/test_*.py` — 46 tests, run with `pytest tests/`

## Conventions

- Inline docs are bilingual (Mongolian / English) — keep both when editing
- Always use `from __future__ import annotations` in new modules
- Use `datetime.now(timezone.utc)` — never `utcnow()` (deprecated in 3.12+)
- Run `pytest tests/` after any change to `risk/`, `strategy/`, `analysis/`, or `utils/database.py`
- Logging: get a logger via `utils.logger.get_logger(name)` — never `logging.getLogger` directly

## Things that have bitten us

- **`pandas-ta` requires NumPy 2.x** — don't pin numpy<2
- **Pytest chdir** breaks file handlers — `utils.logger` already guards with `PYTEST_CURRENT_TEST` env var
- **`mt5.order_send()` can return `None`** on disconnect — always None-check before `.retcode`
- **`schedule` is single-threaded** — never put a blocking `time.sleep()` inside a scheduled callback. Use `schedule.every().hour.at(":01:30")` instead of sleeping until the candle closes
- **Sentiment double-penalty**: do not multiply position size by `sentiment_factor` in risk_manager — strategy.confidence already incorporates it
- **Symbol-aware constants**: pip values and breakeven triggers differ between EURUSD and XAUUSD — check `config.PIP_VALUES` and `config.BREAKEVEN_TRIGGER_POINTS`

## Run commands

```powershell
# Tests
pytest tests/

# Backtest
python backtest.py --symbol BTC/USDT --days 90 --sl 2 --tp 4

# Live
python main.py

# Disable file logging (used by CI)
$env:DISABLE_FILE_LOG="1"; python main.py
```

## Don't

- Don't commit `.env` (gitignored — keep it that way)
- Don't add `__pycache__/` to git
- Don't introduce a `time.sleep` longer than 30 sec in a scheduled job — it starves other jobs
- Don't catch exceptions silently in the trading loop without logging — orphan errors hide bugs
- Don't relax the `MAX_DAILY_LOSS` gate "just for testing" — leave it on
