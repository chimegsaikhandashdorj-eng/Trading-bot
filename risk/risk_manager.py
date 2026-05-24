from dataclasses import dataclass
import config
from utils.logger import get_logger
from utils.database import init_db, get_daily_loss, get_daily_stats

log = get_logger("RiskManager")

# Захиалга орох үнийн зөрүүний дээд хязгаар (0.1%)
SLIPPAGE_TOLERANCE = 0.001


@dataclass
class TradeDecision:
    allowed: bool
    reason: str
    position_size: float
    sl_points: int
    tp_points: int


class RiskManager:
    def __init__(self):
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
        # Өдрийн алдагдал DB-ээс татна → restart-д тэсвэртэй
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

        # Sentiment-ийг strategy.confidence-д аль хэдийн оруулсан тул энд double-penalty болгохгүй
        # (хуучин: sentiment_factor=0.5 → risk_amount хэт бага болгож байсан)
        risk_amount = (
            balance * (config.MAX_RISK_PER_TRADE / 100)
            * technical_strength
        )

        if is_forex:
            sl_points = 100
            tp_points = 200          # 1:2 R:R
            pip_value = config.PIP_VALUES.get(symbol, 10.0)
            # 1 standard lot-ийн SL-д хүрэх $ алдагдал = sl_points/10 (pip) × pip_value
            sl_dollar_per_lot = (sl_points / 10) * pip_value
            if sl_dollar_per_lot <= 0:
                return TradeDecision(
                    allowed=False,
                    reason=f"{symbol}: pip_value тохиргоо буруу",
                    position_size=0, sl_points=0, tp_points=0,
                )
            lot_size = round(risk_amount / sl_dollar_per_lot, 2)
            lot_size = max(0.01, min(lot_size, 10.0))
            position_size = lot_size
        else:
            sl_points = 0
            tp_points = 0
            if current_price <= 0:
                return TradeDecision(
                    allowed=False, reason="Үнэ 0 эсвэл сөрөг",
                    position_size=0, sl_points=0, tp_points=0,
                )
            position_size = round(risk_amount / current_price, 6)
            position_size = max(0.0001, position_size)

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
        self, side: str, entry_price: float, current_price: float, point: float,
        symbol: str = "EURUSD",
    ) -> bool:
        """Тухайн symbol-ийн trigger хүртэл ашиг хүрсэн үед SL-г breakeven дээр шилжүүлнэ."""
        if point <= 0:
            return False
        profit_points = (
            (current_price - entry_price) / point if side == "buy"
            else (entry_price - current_price) / point
        )
        trigger = config.BREAKEVEN_TRIGGER_POINTS.get(symbol, 1000)
        return profit_points >= trigger

    @staticmethod
    def slippage_ok(expected_price: float, actual_price: float) -> bool:
        """Бодит fill үнэ хүлээгдсэн үнээс 0.1%-иас илүү зөрвөл буцаана."""
        if expected_price == 0:
            return False
        return abs(actual_price - expected_price) / expected_price <= SLIPPAGE_TOLERANCE

    def get_daily_stats(self) -> dict:
        return get_daily_stats()
