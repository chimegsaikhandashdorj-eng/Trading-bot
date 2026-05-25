import pandas as pd
from dataclasses import dataclass
from typing import Optional, Tuple, Dict

from utils.logger import get_logger

log = get_logger("Fibonacci")

# Стандарт Фибоначчийн уналтын түвшнүүд
FIB_RATIOS: Dict[str, float] = {
    "0.236": 0.236,
    "0.382": 0.382,
    "0.500": 0.500,
    "0.618": 0.618,  # Алтан харьцаа
    "0.786": 0.786,
}

# Алтан бүс: 50%–61.8% (хамгийн хүчтэй уналтын дэмжлэг)
GOLDEN_ZONE_LOW: float = 0.500
GOLDEN_ZONE_HIGH: float = 0.618


@dataclass
class FibLevels:
    """
    Фибоначчийн шинжилгээний үр дүнг хадгалах дата класс.

    Attributes
    ----------
    swing_high : float
        Тодорхойлсон дээд цэг (High)
    swing_low : float
        Тодорхойлсон доод цэг (Low)
    trend : str
        Одоогийн чиглэл ("UP" | "DOWN" | "SIDEWAYS")
    levels : Dict[str, float]
        Фибоначчийн харьцаануудад тохирох үнийн түвшнүүд
    golden_zone_low : float
        Алтан бүсийн доод хязгаар
    golden_zone_high : float
        Алтан бүсийн дээд хязгаар
    in_golden_zone : bool
        Одоогийн үнэ Алтан бүсэд байгаа эсэх
    nearest_level : Optional[str]
        Үнэд хамгийн ойр байгаа Фибоначчийн харьцааны нэр
    nearest_price : Optional[float]
        Үнэд хамгийн ойр байгаа Фибоначчийн үнэ
    """
    swing_high: float
    swing_low: float
    trend: str
    levels: Dict[str, float]
    golden_zone_low: float
    golden_zone_high: float
    in_golden_zone: bool
    nearest_level: Optional[str]
    nearest_price: Optional[float]


class FibonacciAnalyzer:
    """
    Фибоначчийн уналтын түвшнүүдийг (Fibonacci Retracement) тооцоолж,
    алтан бүс болон бусад түвшний үнэлгээг гаргах класс.
    """

    def __init__(self, df: pd.DataFrame, lookback: int = 50) -> None:
        """
        FibonacciAnalyzer үүсгэх.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV өгөгдлийг агуулсан DataFrame
        lookback : int, default 50
            Хамгийн сүүлийн хэдэн свечнийг шинжлэх хугацаа (lookback window)
        """
        self.df = df.copy()
        self.lookback = lookback

    def calculate_levels(self) -> FibLevels:
        """
        Сүүлийн swing high/low-оор Фибоначчийн уналтын түвшнүүдийг тооцно.
        IndexError хамгаалалттай.

        Returns
        -------
        FibLevels
            Фибоначчийн тооцоолсон түвшнүүдийн үр дүн
        """
        # Дата хүрэлцэхгүй бол хоосон үр дүн буцаана
        if self.df is None or len(self.df) < 10:
            log.warning("Fibonacci тооцоолоход дата хангалтгүй байна.")
            return FibLevels(
                swing_high=0.0,
                swing_low=0.0,
                trend="SIDEWAYS",
                levels={},
                golden_zone_low=0.0,
                golden_zone_high=0.0,
                in_golden_zone=False,
                nearest_level=None,
                nearest_price=None,
            )

        try:
            lookback_len = min(len(self.df), self.lookback)
            window = self.df.tail(lookback_len)
            high = float(window["high"].max())
            low = float(window["low"].min())
            diff = high - low

            # Трендийн чиглэл: сүүлийн 10 свечний хаалтын чиглэл
            recent_len = min(len(self.df), 10)
            recent_close = self.df["close"].tail(recent_len)
            trend = "UP" if recent_close.iloc[-1] > recent_close.iloc[0] else "DOWN"

            # Уналтын (Retracement) түвшнүүд: high-аас доош
            levels = {
                name: round(high - ratio * diff, 5)
                for name, ratio in FIB_RATIOS.items()
            }

            current = float(self.df["close"].iloc[-1])
            golden_low = round(high - GOLDEN_ZONE_HIGH * diff, 5)
            golden_high = round(high - GOLDEN_ZONE_LOW * diff, 5)
            in_golden = golden_low <= current <= golden_high

            nearest_name, nearest_price = self._nearest_level(current, levels)

            if in_golden:
                log.info(f"Fib: Алтан бүс [{golden_low:.5f} — {golden_high:.5f}] | price={current:.5f}")

            return FibLevels(
                swing_high=high,
                swing_low=low,
                trend=trend,
                levels=levels,
                golden_zone_low=golden_low,
                golden_zone_high=golden_high,
                in_golden_zone=in_golden,
                nearest_level=nearest_name,
                nearest_price=nearest_price,
            )
        except Exception as e:
            log.error(f"Fibonacci тооцоолоход алдаа гарлаа: {e}")
            return FibLevels(
                swing_high=0.0,
                swing_low=0.0,
                trend="SIDEWAYS",
                levels={},
                golden_zone_low=0.0,
                golden_zone_high=0.0,
                in_golden_zone=False,
                nearest_level=None,
                nearest_price=None,
            )

    def _nearest_level(self, price: float, levels: Dict[str, float]) -> Tuple[Optional[str], Optional[float]]:
        """
        Үнэд хамгийн ойр байгаа Фибоначчийн түвшний мэдээллийг олох.

        Parameters
        ----------
        price : float
            Одоогийн үнэ
        levels : Dict[str, float]
            Фибоначчийн бүх түвшний толь (dict)

        Returns
        -------
        Tuple[Optional[str], Optional[float]]
            (хамгийн_ойр_түвшний_нэр, хамгийн_ойр_түвшний_үнэ)
        """
        if not levels:
            return None, None

        min_dist = float("inf")
        name: Optional[str] = None
        lvl: Optional[float] = None
        for n, p in levels.items():
            d = abs(price - p)
            if d < min_dist:
                min_dist, name, lvl = d, n, p
        return name, lvl

    def get_score(self, fib: FibLevels, sr_zone: str) -> float:
        """
        Фибоначчийн үнэлгээг гаргах (max 0.30).

        Parameters
        ----------
        fib : FibLevels
            Фибоначчийн шинжилгээний үр дүн
        sr_zone : str
            Дэмжлэг/Эсэргүүцлийн бүсийн төлөв ("SUPPORT_ZONE" | "RESISTANCE_ZONE" | "NEUTRAL")

        Returns
        -------
        float
            Бодож гаргасан нэмэлт оноо (0.0 - 0.30)
        """
        if fib.swing_high == 0.0 and fib.swing_low == 0.0:
            return 0.0

        # Алтан бүс + Дэмжлэг бүс нийцвэл -> 0.30
        if fib.in_golden_zone and sr_zone == "SUPPORT_ZONE":
            return 0.30
        # Зөвхөн алтан бүсэд байвал -> 0.15
        if fib.in_golden_zone:
            return 0.15
        # 0.382 түвшин + Дэмжлэг бүс тохирвол -> 0.20
        if fib.nearest_level == "0.382" and sr_zone == "SUPPORT_ZONE":
            return 0.20
        return 0.0
