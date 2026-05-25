"""
MetaTrader 5 client wrapper for forex / gold trading.

Encapsulates the native `MetaTrader5` package so the rest of the bot
sees plain Python types. All public methods are None-safe — they return
sensible defaults on disconnect or invalid input rather than raising.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

import config
from utils.logger import get_logger

log = get_logger("MT5")

try:
    import MetaTrader5 as _mt5_mod  # pyrefly: ignore
    mt5: Any = _mt5_mod
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False
    log.warning("MetaTrader5 суулгаагүй байна. MT5 функц ажиллахгүй.")

# MT5 timeframe constants — duplicated here so callers don't need to import mt5.
MT5_TIMEFRAMES: Dict[str, int] = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "30m": 30,
    "1h":  16385,
    "4h":  16388,
    "1d":  16408,
}

# Symbol-specific maximum spread (in broker points). Wider than this → skip trade.
MAX_SPREAD_POINTS: Dict[str, int] = {
    "EURUSD": 30,
    "GBPUSD": 40,
    "USDJPY": 30,
    "XAUUSD": 500,   # Gold-ийн spread өндөр байдаг
}
DEFAULT_MAX_SPREAD: int = 50


class MT5Client:
    """MetaTrader 5 wrapper. Use `connected` to check session status."""

    def __init__(self) -> None:
        self.connected: bool = False
        if not MT5_AVAILABLE:
            log.warning("MT5 library байхгүй тул MT5 клиент ажиллахгүй")
            return
        self._connect()

    def _connect(self) -> bool:
        """Initialize MT5 and log into the broker. Returns True on success."""
        if not mt5.initialize():
            log.error("MT5 initialize хийж чадсангүй")
            return False
        result = mt5.login(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        if result:
            info = mt5.account_info()
            if info:
                log.info(f"MT5 холбогдлоо | Баланс: {info.balance} {info.currency}")
            self.connected = True
        else:
            log.error(f"MT5 нэвтрэх алдаа: {mt5.last_error()}")
        return self.connected

    # ── Market schedule ──────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Forex is closed Saturday 22:00 UTC through Sunday + first 5 min of Monday."""
        now = datetime.now(timezone.utc)
        weekday = now.weekday()   # Monday=0 ... Sunday=6

        if weekday == 6:
            log.info("Ням гараг — Forex зах зээл хаалттай")
            return False
        if weekday == 5 and now.hour >= 22:
            log.info("Бямба 22:00+ UTC — Forex зах зээл хаагдаж байна")
            return False
        if weekday == 0 and now.hour == 0 and now.minute < 5:
            log.info("Даваа гараг нээлтийн минутууд — хүлээж байна")
            return False
        return True

    # ── Spread ───────────────────────────────────────────────────────────

    def get_spread(self, symbol: str) -> int:
        """Current spread in broker points. 9999 sentinel on error."""
        if not self.connected:
            return 9999
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if not tick or not info or info.point <= 0:
            return 9999
        return round((tick.ask - tick.bid) / info.point)

    def is_spread_ok(self, symbol: str) -> bool:
        """True iff current spread is at or below the per-symbol threshold."""
        spread = self.get_spread(symbol)
        max_spread = MAX_SPREAD_POINTS.get(symbol, DEFAULT_MAX_SPREAD)
        if spread > max_spread:
            log.warning(f"{symbol} spread хэт өндөр: {spread} > {max_spread} points")
            return False
        return True

    # ── Account / market data ────────────────────────────────────────────

    def get_balance(self) -> float:
        """
        Account equity (balance + floating P&L of open positions).

        We return equity rather than raw balance because risk sizing must
        reflect what would be left after closing all positions, not just
        the deposit ledger.
        """
        if not self.connected:
            return 0.0
        info = mt5.account_info()
        if not info:
            return 0.0
        return float(getattr(info, "equity", info.balance))

    def get_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 200
    ) -> Optional[pd.DataFrame]:
        """Recent OHLCV bars as a UTC-indexed DataFrame, or None on error."""
        if not self.connected:
            return None
        tf = MT5_TIMEFRAMES.get(timeframe, 16385)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, limit)
        if rates is None:
            log.error(f"OHLCV авах алдаа ({symbol}): {mt5.last_error()}")
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(columns={"time": "timestamp", "tick_volume": "volume"}, inplace=True)
        df.set_index("timestamp", inplace=True)
        return pd.DataFrame(df[["open", "high", "low", "close", "volume"]])

    def get_current_price(self, symbol: str) -> Optional[Dict[str, float]]:
        """Mid-price + bid/ask, or None if the symbol is unavailable."""
        if not self.connected:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {"bid": tick.bid, "ask": tick.ask, "last": (tick.bid + tick.ask) / 2}

    def get_point(self, symbol: str) -> float:
        """Broker's "point" size for `symbol` (0.00001 for EURUSD, 0.01 for XAUUSD)."""
        if not self.connected:
            return 0.00001
        info = mt5.symbol_info(symbol)
        return info.point if info else 0.00001

    # ── Order placement ──────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl_points: int = 100,
        tp_points: int = 200,
    ) -> Optional[Dict[str, Any]]:
        """
        Place a market order with broker-side SL and TP.

        Returns a dict with `ticket`, `price`, `volume`, `sl`, `tp`, `point`
        on success, or None on any failure (logged).
        """
        if not self.connected:
            return None
        if not self.is_spread_ok(symbol):
            log.warning(f"{symbol}: Spread хэт өндөр тул захиалга өгсөнгүй")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            log.error(f"Tick мэдээлэл авах алдаа: {symbol}")
            return None

        info = mt5.symbol_info(symbol)
        if not info:
            log.error(f"symbol_info алдаа: {symbol}")
            return None
        point = info.point

        if order_type == "buy":
            price = tick.ask
            sl = price - sl_points * point
            tp = price + tp_points * point
            action_type = mt5.ORDER_TYPE_BUY
        else:
            price = tick.bid
            sl = price + sl_points * point
            tp = price - tp_points * point
            action_type = mt5.ORDER_TYPE_SELL

        request = {
            "action":        mt5.TRADE_ACTION_DEAL,
            "symbol":        symbol,
            "volume":        volume,
            "type":          action_type,
            "price":         price,
            "sl":            sl,
            "tp":            tp,
            "deviation":     20,
            "magic":         234000,
            "comment":       "TradingBot",
            "type_time":     mt5.ORDER_TIME_GTC,
            "type_filling":  mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            log.error(f"order_send None буцаалаа ({symbol}): {mt5.last_error()}")
            return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            log.error(f"Захиалга алдаа [{result.retcode}]: {result.comment}")
            return None
        log.info(
            f"MT5 захиалга: {order_type} {volume} {symbol} @ {price:.5f} | "
            f"SL={sl:.5f} TP={tp:.5f}"
        )
        return {
            "ticket": result.order,
            "price":  price,
            "volume": volume,
            "sl":     sl,
            "tp":     tp,
            "point":  point,
        }

    def move_sl_to_breakeven(self, ticket: int, entry_price: float) -> bool:
        """
        Move the SL of an open position to its entry price.

        Idempotent: if SL is already at or beyond breakeven, returns False
        without sending an order.
        """
        if not self.connected:
            return False
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        # SL аль хэдийн breakeven эсвэл ашиг талд байвал дахин өөрчлөхгүй
        if pos.type == 0 and pos.sl >= entry_price:
            return False
        if pos.type == 1 and pos.sl <= entry_price and pos.sl != 0:
            return False

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl":       entry_price,
            "tp":       pos.tp,
        }
        result = mt5.order_send(request)
        if result is None:
            log.error(f"Breakeven SL: order_send None ({ticket}): {mt5.last_error()}")
            return False
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"Ticket {ticket}: SL breakeven {entry_price:.5f} дээр шилжлээ")
            return True
        log.error(f"Breakeven SL алдаа [{result.retcode}]: {result.comment}")
        return False

    def close_position(self, ticket: int) -> bool:
        """Market-close an open position. Returns True if the broker confirmed."""
        if not self.connected:
            return False
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            log.error(f"close_position: tick авч чадсангүй ({pos.symbol})")
            return False
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "position":  ticket,
            "symbol":    pos.symbol,
            "volume":    pos.volume,
            "type":      close_type,
            "price":     price,
            "deviation": 20,
            "magic":     234000,
            "comment":   "TradingBot close",
        }
        result = mt5.order_send(request)
        if result is None:
            log.error(f"close_position: order_send None ({ticket})")
            return False
        return result.retcode == mt5.TRADE_RETCODE_DONE

    def get_open_positions(self) -> List[Any]:
        """All currently open positions for this account. Empty list on error."""
        if not self.connected:
            return []
        positions = mt5.positions_get()
        return list(positions) if positions else []

    def get_closed_position_pnl(self, ticket: int) -> Optional[float]:
        """
        Realized P&L for a closed position (sum of profit + commission + swap).

        Returns None if the position is still open or no deals are found.
        """
        if not self.connected:
            return None
        from_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        deals = mt5.history_deals_get(
            from_date, datetime.now(timezone.utc), position=ticket
        )
        if not deals:
            return None
        return sum(
            float(d.profit) + float(d.commission) + float(d.swap) for d in deals
        )

    def disconnect(self) -> None:
        """Tear down the MT5 session. Safe to call repeatedly."""
        if MT5_AVAILABLE:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self.connected = False
        log.info("MT5 холболт тасарлаа")
