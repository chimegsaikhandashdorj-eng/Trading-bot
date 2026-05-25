"""
Risk management for entry sizing, daily-loss gating, and breakeven moves.

The risk layer sits between the strategy (which decides direction & confidence)
and the exchange (which executes orders). It guarantees:

1. Daily loss is bounded by `config.MAX_DAILY_LOSS` — re-read from SQLite on
   every call so it survives restarts.
2. Position size scales linearly with technical strength and is capped at
   `MAX_RISK_PER_TRADE` % of equity.
3. Forex sizing uses symbol-aware pip values (XAUUSD ≠ EURUSD).
4. Slippage exceeding 0.1% is flagged.
5. Breakeven trigger thresholds are symbol-aware (gold needs a wider move).
"""
from __future__ import annotations

from dataclasses import dataclass

import config
from utils.database import get_daily_loss, get_daily_stats, init_db
from utils.logger import get_logger

log = get_logger("RiskManager")

# Maximum acceptable slippage between expected and fill price (0.1%)
SLIPPAGE_TOLERANCE: float = 0.001


@dataclass
class TradeDecision:
    """
    Result of running a candidate trade through the risk gate.

    Attributes
    ----------
    allowed:
        False means the trade was rejected and `position_size` is 0.
    reason:
        Human-readable explanation (logged + sent to Telegram).
    position_size:
        Units to send to the exchange — BTC for crypto, lots for forex.
    sl_points / tp_points:
        Broker points for MT5. Crypto uses % SL set in `main.py`.
    """
    allowed: bool
    reason: str
    position_size: float
    sl_points: int
    tp_points: int


class RiskManager:
    """Stateless risk decision engine backed by a SQLite ledger."""

    def __init__(self) -> None:
        init_db()
        log.info("RiskManager: SQLite persistence идэвхжлээ")

    def evaluate_trade(
        self,
        symbol: str,
        signal: str,
        balance: float,
        current_price: float,
        technical_strength: float,
        sentiment_confirmed: bool,
        is_forex: bool = False,
    ) -> TradeDecision:
        """
        Decide whether to allow a candidate trade and, if so, at what size.

        Parameters
        ----------
        symbol:
            Trading pair (e.g. "BTC/USDT", "EURUSD").
        signal:
            "BUY" | "SELL" — direction from the strategy.
        balance:
            Current equity in USD (or USDT for crypto).
        current_price:
            Last known price — used to convert risk $ into units.
        technical_strength:
            0.0–1.0 from the basic TA layer; scales position size linearly.
        sentiment_confirmed:
            True if X.com / CryptoPanic agreed with the technical direction.
            Currently unused for sizing (strategy.confidence already weighs it)
            but kept for logging / future use.
        is_forex:
            True ⇒ size in lots using `config.PIP_VALUES`. False ⇒ size in
            base units of the crypto pair.

        Returns
        -------
        TradeDecision
        """
        # Daily loss gate — read from DB so restarts don't reset the limit
        daily_loss = get_daily_loss()
        max_daily = balance * (config.MAX_DAILY_LOSS / 100)
        if daily_loss >= max_daily:
            return TradeDecision(
                allowed=False,
                reason=f"Өдрийн алдагдлын хязгаар хүрлээ ({daily_loss:.2f}/{max_daily:.2f})",
                position_size=0, sl_points=0, tp_points=0,
            )

        if technical_strength < 0.5:
            return TradeDecision(
                allowed=False,
                reason=f"Техникийн сигнал хүч хангалтгүй ({technical_strength:.2f} < 0.5)",
                position_size=0, sl_points=0, tp_points=0,
            )

        # Risk budget: % of balance scaled by signal strength.
        # Sentiment is NOT applied here — strategy.confidence already incorporated it.
        risk_amount = balance * (config.MAX_RISK_PER_TRADE / 100) * technical_strength

        if is_forex:
            sl_points = 100
            tp_points = 200          # 1:2 R:R
            pip_value = config.PIP_VALUES.get(symbol, 10.0)
            sl_dollar_per_lot = (sl_points / 10) * pip_value
            if sl_dollar_per_lot <= 0:
                return TradeDecision(
                    allowed=False,
                    reason=f"{symbol}: pip_value тохиргоо буруу",
                    position_size=0, sl_points=0, tp_points=0,
                )
            lot_size = round(risk_amount / sl_dollar_per_lot, 2)
            position_size = max(0.01, min(lot_size, 10.0))
        else:
            sl_points = 0
            tp_points = 0
            if current_price <= 0:
                return TradeDecision(
                    allowed=False, reason="Үнэ 0 эсвэл сөрөг",
                    position_size=0, sl_points=0, tp_points=0,
                )
            position_size = max(0.0001, round(risk_amount / current_price, 6))

        log.info(
            f"{symbol} {signal} → size={position_size} | "
            f"risk=${risk_amount:.2f} | sentiment_ok={sentiment_confirmed}"
        )
        return TradeDecision(
            allowed=True,
            reason="Нөхцөл хангагдсан",
            position_size=position_size,
            sl_points=sl_points,
            tp_points=tp_points,
        )

    def should_move_to_breakeven(
        self,
        side: str,
        entry_price: float,
        current_price: float,
        point: float,
        symbol: str = "EURUSD",
    ) -> bool:
        """
        Whether profit has run far enough to move SL to breakeven.

        Trigger is symbol-aware via `config.BREAKEVEN_TRIGGER_POINTS`
        because gold's "point" is $0.01 while EURUSD's is 0.00001.
        """
        if point <= 0:
            return False
        if side == "buy":
            profit_points = (current_price - entry_price) / point
        else:
            profit_points = (entry_price - current_price) / point
        trigger = config.BREAKEVEN_TRIGGER_POINTS.get(symbol, 1000)
        return profit_points >= trigger

    @staticmethod
    def slippage_ok(expected_price: float, actual_price: float) -> bool:
        """Return True iff the fill price is within `SLIPPAGE_TOLERANCE` of expected."""
        if expected_price <= 0:
            return False
        return abs(actual_price - expected_price) / expected_price <= SLIPPAGE_TOLERANCE

    def get_daily_stats(self) -> dict:
        """Today's aggregate P&L, trade count, and win count."""
        return get_daily_stats()
