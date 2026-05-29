"""
Trading Bot — Forex / Gold / BTC / ETH

Stack
-----
- **Binance** (ccxt) for spot crypto trading
- **MetaTrader 5** for forex & XAU
- **X.com / CryptoPanic** for sentiment confirmation
- **pandas-ta + TA-Lib** for technical analysis
- **SQLite** for trade persistence
- **Telegram** for notifications

The bot evaluates each symbol once per closed candle (`:01:30` past the hour
so that exchange-side bars have time to settle). Breakeven SL moves and
broker-side close reconciliation run on their own cadences so a slow
analysis job never starves them.
"""
from __future__ import annotations

import signal
import sys
import time
from typing import Any, Dict, Optional

import schedule

import config
from exchanges.binance_client import BinanceClient
from exchanges.mt5_client import MT5Client
from notifications.health_server import HealthServer
from notifications.telegram_commands import TelegramCommandListener
from notifications.telegram_notifier import TelegramNotifier
from notifications.watchdog import Watchdog
from risk.positions import PositionRegistry
from risk.risk_manager import RiskManager
from strategy.strategy import CombinedStrategy
from utils.database import (
    close_trade, get_open_trades, mark_trade_orphan, open_trade,
)
from utils.logger import get_logger

log = get_logger("Main")


class TradingBot:
    """Composition root — wires exchanges, strategy, risk, notifier."""

    def __init__(self) -> None:
        log.info("=" * 60)
        log.info("Trading Bot starting...")
        log.info("=" * 60)

        # Surface configuration issues immediately
        for warning in config.validate(strict=False):
            log.warning(f"config: {warning}")

        self.binance = BinanceClient()
        self.mt5 = MT5Client()
        self.strategy = CombinedStrategy()
        self.risk = RiskManager()
        self.notifier = TelegramNotifier()
        self.watchdog = Watchdog(self.notifier)
        self.health = HealthServer(
            self, host=config.HEALTH_HOST, port=config.HEALTH_PORT
        )
        self.health.start()
        self.tg_commands = TelegramCommandListener(self)
        self.tg_commands.start()

        # Thread-safe registry — accessed by scheduler + Telegram listener
        self.open_positions: PositionRegistry = PositionRegistry()
        self._paused: bool = False
        self._stop = False

        self.reconcile_positions()
        self.notifier.send("Trading Bot started!")

    # ── Reconciliation ───────────────────────────────────────────────────

    def reconcile_positions(self) -> None:
        """
        On startup, sync the in-memory `open_positions` dict with what the
        broker actually holds. Trades the DB thinks are open but the broker
        no longer has are marked 'orphan' (we missed the close event).
        """
        try:
            self._reconcile_mt5()
            self._reconcile_binance()
        except Exception as exc:
            log.error(f"reconcile_positions failed: {exc}")

    def _reconcile_mt5(self) -> None:
        # Don't touch DB rows if we can't reach the broker — they might be
        # legitimately open and we'd wrongly mark them orphan.
        if not self.mt5.connected:
            log.warning("MT5 not connected — skipping MT5 reconciliation")
            return
        broker_tickets = {p.ticket for p in self.mt5.get_open_positions()}
        for trade in get_open_trades(exchange="mt5"):
            db_ticket_str = trade.get("ticket")
            if not db_ticket_str:
                continue
            try:
                db_ticket = int(db_ticket_str)
            except (TypeError, ValueError):
                continue
            if db_ticket in broker_tickets:
                self.open_positions.try_add(trade["id"], {
                    "symbol":   trade["symbol"],
                    "side":     trade["side"],
                    "entry":    trade["entry_price"],
                    "ticket":   db_ticket,
                    "point":    self.mt5.get_point(trade["symbol"]),
                    "exchange": "mt5",
                    "breakeven_moved": False,
                })
                log.info(
                    f"Reconciled MT5 position: id={trade['id']} "
                    f"{trade['symbol']} ticket={db_ticket}"
                )
            else:
                mark_trade_orphan(trade["id"])
                log.warning(
                    f"Marked orphan: id={trade['id']} {trade['symbol']} "
                    f"ticket={db_ticket} (no broker match)"
                )

    def _reconcile_binance(self) -> None:
        """
        Binance spot has no "position" — only balances and open orders. We
        load DB-open trades into memory so they keep their SL/TP context. The
        SL order is what actually closes the trade; `sync_closed_positions`
        polls open orders to detect when SL fires.
        """
        for trade in get_open_trades(exchange="binance"):
            self.open_positions.try_add(trade["id"], {
                "symbol":   trade["symbol"],
                "side":     trade["side"],
                "entry":    trade["entry_price"],
                "exchange": "binance",
                "sl_order_id": trade.get("sl_order_id"),
            })
            log.info(
                f"Reconciled Binance trade: id={trade['id']} "
                f"{trade['symbol']} side={trade['side']}"
            )

    # ── Crypto (Binance) ──────────────────────────────────────────────────

    def run_crypto(self) -> None:
        if self._paused:
            log.info("Bot paused — skipping crypto analysis")
            return
        log.info("-- Crypto analysis starting --")
        balance = self.binance.get_balance("USDT")

        for symbol in config.CRYPTO_SYMBOLS:
            try:
                self._evaluate_crypto_symbol(symbol, balance)
            except Exception as exc:
                log.error(f"{symbol} error: {exc}")
                self.notifier.notify_error(f"{symbol}: {exc}")

    def _evaluate_crypto_symbol(self, symbol: str, balance: float) -> None:
        # ── Duplicate-position guard ─────────────────────────────────────
        # Without this, the bot stacks BUYs every hour during a trend → N×
        # risk and N× drawdown on reversal. This is the single most
        # capital-destructive bug in the original code.
        if self.open_positions.has(symbol, "binance"):
            log.info(f"{symbol}: already have an open Binance position — skip")
            return

        df_1h = self.binance.get_ohlcv(symbol, config.TIMEFRAME_PRIMARY, 200)
        df_4h = self.binance.get_ohlcv(symbol, config.TIMEFRAME_CONFIRM, 200)
        if df_1h is None:
            return

        signal_out = self.strategy.evaluate(
            df_1h, df_4h, symbol,
            config.TIMEFRAME_PRIMARY, config.TIMEFRAME_CONFIRM,
        )
        if not signal_out:
            return

        ticker = self.binance.get_ticker(symbol)
        price = ticker["last"] if ticker else signal_out.technical.current_price

        decision = self.risk.evaluate_trade(
            symbol=symbol,
            signal=signal_out.final_signal,
            balance=balance,
            current_price=price,
            technical_strength=signal_out.technical.strength,
            sentiment_confirmed=(
                signal_out.sentiment.confirm_trade if signal_out.sentiment else False
            ),
            is_forex=False,
        )

        sent_str = signal_out.sentiment.sentiment if signal_out.sentiment else "N/A"
        self.notifier.notify_signal(
            symbol, signal_out.final_signal, price,
            signal_out.confidence, sent_str, signal_out.reason,
        )

        if not decision.allowed:
            log.warning(f"{symbol} trade denied: {decision.reason}")
            return

        side = "buy" if signal_out.final_signal == "BUY" else "sell"
        order = self.binance.place_order(symbol, side, decision.position_size)
        if not order:
            return

        fill_price = order.get("average") or price
        if not self.risk.slippage_ok(price, fill_price):
            log.warning(f"{symbol} slippage хэтэрсэн: {price} vs {fill_price}")
            self.notifier.notify_error(f"{symbol} slippage too high")

        sl_pct = config.CRYPTO_SL_PCT / 100
        tp_pct = config.CRYPTO_TP_PCT / 100
        if side == "buy":
            sl_price = round(fill_price * (1 - sl_pct), 2)
            tp_price = round(fill_price * (1 + tp_pct), 2)
        else:
            sl_price = round(fill_price * (1 + sl_pct), 2)
            tp_price = round(fill_price * (1 - tp_pct), 2)

        # ── Critical: SL placement must succeed before we book the trade ──
        sl_order = self.binance.place_stop_loss(
            symbol, side, decision.position_size, sl_price
        )
        if sl_order is None:
            msg = (
                f"⛔ CRITICAL: {symbol} entry filled but SL placement FAILED — "
                f"closing position to avoid unprotected exposure."
            )
            log.critical(msg)
            self.notifier.notify_error(msg)
            # Emergency close — opposite-side market order to flatten
            opposite = "sell" if side == "buy" else "buy"
            self.binance.place_order(symbol, opposite, decision.position_size)
            return

        trade_id = open_trade(symbol, side, fill_price, decision.position_size, "binance")
        self.open_positions.try_add(trade_id, {
            "symbol": symbol, "side": side,
            "entry": fill_price, "exchange": "binance",
            "sl": sl_price, "tp": tp_price,
            "sl_order_id": sl_order.get("id"),
            "volume": decision.position_size,
        })
        self.notifier.notify_trade(
            symbol, signal_out.final_signal, fill_price,
            decision.position_size, sl_price, tp_price,
        )

    # ── Forex / Gold (MT5) ────────────────────────────────────────────────

    def run_forex(self) -> None:
        if self._paused:
            log.info("Bot paused — skipping forex analysis")
            return
        if not self.mt5.connected:
            log.warning("MT5 not connected, skipping forex")
            return
        if not self.mt5.is_market_open():
            log.info("Forex market closed (weekend/holiday) — skipping")
            return

        log.info("-- Forex/Gold analysis starting --")
        balance = self.mt5.get_balance()

        for symbol in config.FOREX_SYMBOLS:
            try:
                self._evaluate_forex_symbol(symbol, balance)
            except Exception as exc:
                log.error(f"{symbol} error: {exc}")
                self.notifier.notify_error(f"{symbol}: {exc}")

    def _evaluate_forex_symbol(self, symbol: str, balance: float) -> None:
        # Duplicate-position guard (see crypto evaluator for rationale)
        if self.open_positions.has(symbol, "mt5"):
            log.info(f"{symbol}: already have an open MT5 position — skip")
            return

        if not self.mt5.is_spread_ok(symbol):
            return

        df_1h = self.mt5.get_ohlcv(symbol, config.TIMEFRAME_PRIMARY, 200)
        df_4h = self.mt5.get_ohlcv(symbol, config.TIMEFRAME_CONFIRM, 200)
        if df_1h is None:
            return

        signal_out = self.strategy.evaluate(
            df_1h, df_4h, symbol,
            config.TIMEFRAME_PRIMARY, config.TIMEFRAME_CONFIRM,
        )
        if not signal_out:
            return

        tick = self.mt5.get_current_price(symbol)
        price = tick["last"] if tick else signal_out.technical.current_price

        decision = self.risk.evaluate_trade(
            symbol=symbol,
            signal=signal_out.final_signal,
            balance=balance,
            current_price=price,
            technical_strength=signal_out.technical.strength,
            sentiment_confirmed=(
                signal_out.sentiment.confirm_trade if signal_out.sentiment else False
            ),
            is_forex=True,
        )

        sent_str = signal_out.sentiment.sentiment if signal_out.sentiment else "N/A"
        self.notifier.notify_signal(
            symbol, signal_out.final_signal, price,
            signal_out.confidence, sent_str, signal_out.reason,
        )

        if not decision.allowed:
            log.warning(f"{symbol} trade denied: {decision.reason}")
            return

        order = self.mt5.place_order(
            symbol=symbol,
            order_type=signal_out.final_signal.lower(),
            volume=decision.position_size,
            sl_points=decision.sl_points,
            tp_points=decision.tp_points,
        )
        if not order:
            return

        fill_price = order["price"]
        if not self.risk.slippage_ok(price, fill_price):
            log.warning(f"{symbol} slippage: expected={price:.5f} got={fill_price:.5f}")

        trade_id = open_trade(
            symbol, signal_out.final_signal.lower(),
            fill_price, decision.position_size,
            "mt5", str(order["ticket"]),
        )
        self.open_positions.try_add(trade_id, {
            "symbol": symbol,
            "side":   signal_out.final_signal.lower(),
            "entry":  fill_price,
            "ticket": order["ticket"],
            "point":  order["point"],
            "exchange": "mt5",
            "breakeven_moved": False,
        })
        self.notifier.notify_trade(
            symbol, signal_out.final_signal, fill_price, decision.position_size,
            order["sl"], order["tp"],
        )

    # ── Breakeven мониторинг ──────────────────────────────────────────────

    def check_breakeven(self) -> None:
        """Move SL to entry once price has run far enough into profit."""
        for trade_id, pos in self.open_positions.snapshot():
            if pos.get("exchange") != "mt5" or pos.get("breakeven_moved"):
                continue
            tick = self.mt5.get_current_price(pos["symbol"])
            if not tick:
                continue
            current = tick["last"]
            should_be = self.risk.should_move_to_breakeven(
                pos["side"], pos["entry"], current,
                pos.get("point", 0.00001), pos["symbol"],
            )
            if should_be:
                moved = self.mt5.move_sl_to_breakeven(pos["ticket"], pos["entry"])
                if moved:
                    self.open_positions.update_field(trade_id, "breakeven_moved", True)
                    self.notifier.send(
                        f"Breakeven set: {pos['symbol']} ticket={pos['ticket']}"
                    )

    # ── Хаагдсан позицүүдийг бүртгэх ─────────────────────────────────────

    def sync_closed_positions(self) -> None:
        """Detect broker-side closures and write the realized P&L to the DB."""
        self._sync_mt5_closures()
        self._sync_binance_closures()

    def _sync_mt5_closures(self) -> None:
        if not self.mt5.connected:
            return
        try:
            open_tickets = {p.ticket for p in self.mt5.get_open_positions()}
        except Exception as exc:
            log.error(f"sync_mt5_closures: cannot fetch positions: {exc}")
            return

        for trade_id, pos in self.open_positions.snapshot():
            if pos.get("exchange") != "mt5":
                continue
            ticket = pos.get("ticket")
            if not ticket or ticket in open_tickets:
                continue
            pnl = self.mt5.get_closed_position_pnl(ticket) or 0.0
            close_trade(trade_id, pnl)
            self.notifier.notify_close(pos["symbol"], pnl)
            log.info(f"Position closed: {pos['symbol']} ticket={ticket} pnl={pnl:+.2f}")
            self.open_positions.remove(trade_id)

    def _sync_binance_closures(self) -> None:
        """
        Binance spot has no position concept. We track the SL order — when it
        no longer appears as an *open* order it has filled (SL hit) and the
        trade is closed. P&L is computed from entry vs. SL price (worst case);
        TP-hit closures are caught the same way because TP would also have
        been an open order. If we didn't place a TP, ticker price is used.
        """
        for trade_id, pos in self.open_positions.snapshot():
            if pos.get("exchange") != "binance":
                continue
            sl_order_id = pos.get("sl_order_id")
            if not sl_order_id:
                continue
            try:
                open_orders = self.binance.get_open_orders(pos["symbol"])
            except Exception as exc:
                log.error(f"sync_binance_closures: open_orders failed: {exc}")
                continue
            still_open = any(str(o.get("id")) == str(sl_order_id) for o in open_orders)
            if still_open:
                continue
            # SL order vanished → assume filled. Use SL price as worst-case exit.
            exit_price = pos.get("sl", pos["entry"])
            entry = pos["entry"]
            volume = pos.get("volume", 0.0)
            sign = 1 if pos["side"] == "buy" else -1
            pnl = sign * (exit_price - entry) * volume
            close_trade(trade_id, pnl)
            self.notifier.notify_close(pos["symbol"], pnl)
            log.info(
                f"Binance closure: {pos['symbol']} entry={entry} "
                f"exit≈{exit_price} pnl={pnl:+.2f}"
            )
            self.open_positions.remove(trade_id)

    # ── Health check ──────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """Lightweight health snapshot, used by tests and external monitors."""
        return {
            "binance_connected": self.binance is not None,
            "mt5_connected": self.mt5.connected,
            "telegram_enabled": self.notifier.enabled,
            "open_positions": len(self.open_positions),
        }

    # ── Өдрийн тайлан ─────────────────────────────────────────────────────

    def daily_report(self) -> None:
        stats = self.risk.get_daily_stats()
        crypto_bal = self.binance.get_balance("USDT")
        mt5_bal = self.mt5.get_balance() if self.mt5.connected else 0.0
        total_balance = crypto_bal + mt5_bal
        self.notifier.notify_daily_report(
            total_balance, stats["total_pnl"], stats["trade_count"]
        )
        log.info(
            f"Daily report | crypto=${crypto_bal:.2f} mt5=${mt5_bal:.2f} | "
            f"pnl={stats['total_pnl']:+.2f} | trades={stats['trade_count']}"
        )

    # ── Scheduler ─────────────────────────────────────────────────────────

    def run(self) -> None:
        log.info("Configuring scheduler...")

        # Hourly run at :01:30 — past the candle close, no manual blocking sleep
        schedule.every().hour.at(":01:30").do(self._tick_and_run, self.run_crypto)
        schedule.every().hour.at(":01:30").do(self._tick_and_run, self.run_forex)

        schedule.every(5).minutes.do(self._tick_and_run, self.check_breakeven)
        schedule.every(2).minutes.do(self._tick_and_run, self.sync_closed_positions)
        schedule.every().day.at("23:55").do(self._tick_and_run, self.daily_report)

        # Optional immediate analysis cycle so first signals don't wait an hour
        log.info("Running initial analysis...")
        self.run_crypto()
        self.run_forex()

        log.info("Bot running. Press Ctrl+C to stop.")
        while not self._stop:
            schedule.run_pending()
            time.sleep(15)

    def _tick_and_run(self, fn) -> None:
        """Tick the watchdog, then run `fn`. Swallow exceptions per-job."""
        self.watchdog.tick()
        try:
            fn()
        except Exception as exc:
            log.error(f"Scheduled job {fn.__name__} failed: {exc}")

    # ── Control surface (used by Telegram /commands and tests) ──────────

    def pause(self) -> None:
        """Stop opening new positions. Existing positions remain managed."""
        self._paused = True
        log.warning("Bot paused — no new entries will be taken")

    def resume(self) -> None:
        """Resume opening new positions."""
        self._paused = False
        log.info("Bot resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def status_snapshot(self) -> Dict[str, Any]:
        """Compact runtime status — used by /status and /health."""
        stats = self.risk.get_daily_stats()
        return {
            "paused": self._paused,
            "binance_connected": self.binance is not None,
            "mt5_connected": self.mt5.connected,
            "open_positions": len(self.open_positions),
            "daily_pnl": stats["total_pnl"],
            "daily_trades": stats["trade_count"],
        }

    def stop(self) -> None:
        log.info("Shutdown requested")
        self._stop = True
        try:
            self.tg_commands.stop()
        except Exception:
            pass
        try:
            self.health.stop()
        except Exception:
            pass
        try:
            self.watchdog.stop()
        except Exception:
            pass
        try:
            self.notifier.shutdown()
        except Exception:
            pass
        try:
            self.mt5.disconnect()
        except Exception:
            pass


def _install_signal_handlers(bot: TradingBot) -> None:
    def _handler(signum, _frame):
        log.info(f"Received signal {signum} — exiting cleanly")
        bot.stop()
    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    bot: Optional[TradingBot] = None
    try:
        bot = TradingBot()
        _install_signal_handlers(bot)
        bot.run()
        return 0
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
        return 0
    except Exception as exc:
        log.critical(f"Critical error: {exc}", exc_info=True)
        return 1
    finally:
        if bot is not None:
            bot.stop()


if __name__ == "__main__":
    sys.exit(main())
