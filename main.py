"""
Trading Bot - Forex/Gold/BTC/ETH
Binance (crypto) + MT5 (forex/gold) + X.com sentiment + Technical Analysis
"""
import time
import schedule
from datetime import datetime, timezone

import config
from exchanges.binance_client import BinanceClient
from exchanges.mt5_client import MT5Client
from strategy.strategy import CombinedStrategy
from risk.risk_manager import RiskManager
from notifications.telegram_notifier import TelegramNotifier
from utils.database import open_trade, close_trade
from utils.logger import get_logger

log = get_logger("Main")


class TradingBot:
    def __init__(self):
        log.info("=" * 60)
        log.info("Trading Bot starting...")
        log.info("=" * 60)
        self.binance = BinanceClient()
        self.mt5 = MT5Client()
        self.strategy = CombinedStrategy()
        self.risk = RiskManager()
        self.notifier = TelegramNotifier()

        # Нээлттэй арилжааны тэмдэглэл {ticket/id: {symbol, side, entry, ...}}
        self.open_positions: dict = {}

        self.notifier.send("Trading Bot started!")

    # ── Crypto (Binance) ──────────────────────────────────────────────────────

    def run_crypto(self):
        log.info("-- Crypto analysis starting --")
        balance = self.binance.get_balance("USDT")

        for symbol in config.CRYPTO_SYMBOLS:
            try:
                df_1h = self.binance.get_ohlcv(symbol, config.TIMEFRAME_PRIMARY, 200)
                df_4h = self.binance.get_ohlcv(symbol, config.TIMEFRAME_CONFIRM, 200)
                if df_1h is None:
                    continue

                signal = self.strategy.evaluate(
                    df_1h, df_4h, symbol,
                    config.TIMEFRAME_PRIMARY, config.TIMEFRAME_CONFIRM
                )
                if not signal:
                    continue

                ticker = self.binance.get_ticker(symbol)
                price = ticker["last"] if ticker else signal.technical.current_price

                decision = self.risk.evaluate_trade(
                    symbol=symbol,
                    signal=signal.final_signal,
                    balance=balance,
                    current_price=price,
                    technical_strength=signal.technical.strength,
                    sentiment_confirmed=signal.sentiment.confirm_trade if signal.sentiment else False,
                    is_forex=False,
                )

                sent_str = signal.sentiment.sentiment if signal.sentiment else "N/A"
                self.notifier.notify_signal(
                    symbol, signal.final_signal, price,
                    signal.confidence, sent_str, signal.reason
                )

                if not decision.allowed:
                    log.warning(f"{symbol} trade denied: {decision.reason}")
                    continue

                side = "buy" if signal.final_signal == "BUY" else "sell"
                order = self.binance.place_order(symbol, side, decision.position_size)
                if order:
                    # Slippage шалгах
                    fill_price = order.get("average") or price
                    if not self.risk.slippage_ok(price, fill_price):
                        log.warning(f"{symbol} slippage хэтэрсэн: {price} vs {fill_price}")
                        self.notifier.notify_error(f"{symbol} slippage too high")

                    # Stop-loss байрлуулах — заавал!
                    sl_pct = config.CRYPTO_SL_PCT / 100
                    tp_pct = config.CRYPTO_TP_PCT / 100
                    if side == "buy":
                        sl_price = round(fill_price * (1 - sl_pct), 2)
                        tp_price = round(fill_price * (1 + tp_pct), 2)
                    else:
                        sl_price = round(fill_price * (1 + sl_pct), 2)
                        tp_price = round(fill_price * (1 - tp_pct), 2)
                    self.binance.place_stop_loss(symbol, side, decision.position_size, sl_price)

                    trade_id = open_trade(symbol, side, fill_price, decision.position_size, "binance")
                    self.open_positions[trade_id] = {
                        "symbol": symbol, "side": side,
                        "entry": fill_price, "exchange": "binance",
                        "sl": sl_price, "tp": tp_price,
                    }
                    self.notifier.notify_trade(
                        symbol, signal.final_signal, fill_price,
                        decision.position_size, sl_price, tp_price,
                    )

            except Exception as e:
                log.error(f"{symbol} error: {e}")
                self.notifier.notify_error(f"{symbol}: {e}")

    # ── Forex / Gold (MT5) ────────────────────────────────────────────────────

    def run_forex(self):
        # Амралтын өдөр MT5-аас алдаа авахгүйн тулд шалгана
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
                # Spread хэт өндөр үед алгасна
                if not self.mt5.is_spread_ok(symbol):
                    continue

                df_1h = self.mt5.get_ohlcv(symbol, config.TIMEFRAME_PRIMARY, 200)
                df_4h = self.mt5.get_ohlcv(symbol, config.TIMEFRAME_CONFIRM, 200)
                if df_1h is None:
                    continue

                signal = self.strategy.evaluate(
                    df_1h, df_4h, symbol,
                    config.TIMEFRAME_PRIMARY, config.TIMEFRAME_CONFIRM
                )
                if not signal:
                    continue

                tick = self.mt5.get_current_price(symbol)
                price = tick["last"] if tick else signal.technical.current_price

                decision = self.risk.evaluate_trade(
                    symbol=symbol,
                    signal=signal.final_signal,
                    balance=balance,
                    current_price=price,
                    technical_strength=signal.technical.strength,
                    sentiment_confirmed=signal.sentiment.confirm_trade if signal.sentiment else False,
                    is_forex=True,
                )

                sent_str = signal.sentiment.sentiment if signal.sentiment else "N/A"
                self.notifier.notify_signal(
                    symbol, signal.final_signal, price,
                    signal.confidence, sent_str, signal.reason
                )

                if not decision.allowed:
                    log.warning(f"{symbol} trade denied: {decision.reason}")
                    continue

                order = self.mt5.place_order(
                    symbol=symbol,
                    order_type=signal.final_signal.lower(),
                    volume=decision.position_size,
                    sl_points=decision.sl_points,
                    tp_points=decision.tp_points,
                )
                if order:
                    fill_price = order["price"]
                    if not self.risk.slippage_ok(price, fill_price):
                        log.warning(f"{symbol} slippage: expected={price:.5f} got={fill_price:.5f}")

                    trade_id = open_trade(
                        symbol, signal.final_signal.lower(),
                        fill_price, decision.position_size,
                        "mt5", str(order["ticket"])
                    )
                    self.open_positions[trade_id] = {
                        "symbol": symbol,
                        "side":   signal.final_signal.lower(),
                        "entry":  fill_price,
                        "ticket": order["ticket"],
                        "point":  order["point"],
                        "exchange": "mt5",
                        "breakeven_moved": False,
                    }
                    self.notifier.notify_trade(
                        symbol, signal.final_signal, fill_price, decision.position_size,
                        order["sl"], order["tp"]
                    )

            except Exception as e:
                log.error(f"{symbol} error: {e}")
                self.notifier.notify_error(f"{symbol}: {e}")

    # ── Breakeven мониторинг ──────────────────────────────────────────────────

    def check_breakeven(self):
        """MT5 нээлттэй байрлалуудад ашиг хүрэхэд SL-г breakeven дээр тавина."""
        for trade_id, pos in list(self.open_positions.items()):
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
                    pos["breakeven_moved"] = True
                    self.notifier.send(
                        f"Breakeven set: {pos['symbol']} ticket={pos['ticket']}"
                    )

    # ── Хаагдсан позицүүдийг бүртгэх ─────────────────────────────────────────

    def sync_closed_positions(self):
        """MT5 дээр SL/TP-ээр хаагдсан позицүүдийг шалгаж DB-д хаалт бүртгэнэ."""
        if not self.mt5.connected:
            return
        open_tickets = {p.ticket for p in self.mt5.get_open_positions()}
        for trade_id, pos in list(self.open_positions.items()):
            if pos.get("exchange") != "mt5":
                continue
            ticket = pos.get("ticket")
            if ticket and ticket not in open_tickets:
                # Уг ticket брокер дээр хаагдсан → P&L татна
                pnl = self.mt5.get_closed_position_pnl(ticket) or 0.0
                close_trade(trade_id, pnl)
                self.notifier.notify_close(pos["symbol"], pnl)
                log.info(f"Position closed: {pos['symbol']} ticket={ticket} pnl={pnl:+.2f}")
                del self.open_positions[trade_id]

    # ── Өдрийн тайлан ─────────────────────────────────────────────────────────

    def daily_report(self):
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

    # ── Scheduler ─────────────────────────────────────────────────────────────

    def run(self):
        log.info("Configuring scheduler...")

        # Цаг бүрийн шинжилгээг :01:30-д ажиллуулах (свеч хаагдаад 90 сек)
        # → scheduler-ийг блоклохгүй, breakeven болон бусад job-ууд тасралтгүй ажиллана
        for minute in (":01",):
            schedule.every().hour.at(f"{minute}:30").do(self.run_crypto)
            schedule.every().hour.at(f"{minute}:30").do(self.run_forex)

        # 5 минут тутамд breakeven шалгана
        schedule.every(5).minutes.do(self.check_breakeven)
        # 2 минут тутамд хаагдсан позицүүдийг бүртгэх
        schedule.every(2).minutes.do(self.sync_closed_positions)

        # Өдрийн тайлан 23:55
        schedule.every().day.at("23:55").do(self.daily_report)

        # Эхний ажиллуулалт (одоогийн свеч хаагдахыг хүлээхгүй)
        log.info("Running initial analysis...")
        self.run_crypto()
        self.run_forex()

        log.info("Bot running. Press Ctrl+C to stop.")
        while True:
            schedule.run_pending()
            time.sleep(15)


if __name__ == "__main__":
    try:
        bot = TradingBot()
        bot.run()
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
    except Exception as e:
        log.critical(f"Critical error: {e}")
        raise
