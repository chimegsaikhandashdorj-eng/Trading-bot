import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any

from utils.logger import get_logger

log = get_logger("Candle")

try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False
    log.warning("TA-Lib is not installed. Falling back to high-precision manual pattern recognition.")


@dataclass
class CandleResult:
    """
    Свечний паттерн шинжилгээний үр дүнг хадгалах дата класс.

    Attributes
    ----------
    pattern : str
        Илэрсэн паттерны нэр (Жишээ нь: 'MORNING_STAR', 'BULLISH_ENGULFING', 'NONE' гэх мэт)
    signal : str
        Дохионы чиглэл ('BULLISH_CANDLE' | 'BEARISH_CANDLE' | 'NONE')
    strength : float
        Дохионы хүч (0.0 - 1.0)
    description : str
        Хэрэглэгчид ойлгомжтой тайлбар
    """
    pattern: str
    signal: str
    strength: float
    description: str


class CandlestickAnalyzer:
    """
    Свечний паттернүүдийг TA-Lib болон математик дүрмээр таних класс.
    Steve Nison-ий 'Japanese Candlestick Charting Techniques' номонд тулгуурласан.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        """
        CandlestickAnalyzer-ийг үүсгэх.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV багануудыг агуулсан DataFrame
        """
        self.df = df.copy()

    @staticmethod
    def _metrics(o: float, h: float, l: float, c: float) -> Dict[str, Any]:
        """
        Нэг свечний үндсэн математик хэмжүүрүүдийг тооцоолох.

        Parameters
        ----------
        o : float
            Нээлтийн үнэ (Open)
        h : float
            Дээд үнэ (High)
        l : float
            Доод үнэ (Low)
        c : float
            Хаалтын үнэ (Close)

        Returns
        -------
        Dict[str, Any]
            Свечний бие, сүүл, чиглэлийн мэдээлэл
        """
        body = abs(c - o)
        candle_rng = h - l
        lower_sh = min(o, c) - l
        upper_sh = h - max(o, c)
        body_pct = body / candle_rng if candle_rng > 0 else 0.0
        return {
            "body": body,
            "rng": candle_rng,
            "lower": lower_sh,
            "upper": upper_sh,
            "body_pct": body_pct,
            "bullish": (c > o),
        }

    # ── Гар аргаар паттерн шалгах хэсэг (Fallback & Advanced) ──────────────

    def _manual_morning_star(self, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> bool:
        """
        Гар аргаар Morning Star (Өглөөний од) паттерн шалгах.

        Parameters
        ----------
        opens, highs, lows, closes : np.ndarray
            Нээлт, орой, ёроол, хаалтын үнийн массивууд
        """
        # Сүүлийн 3 хаагдсан свеч:
        # [-4] нь 1-р свеч (bearish)
        # [-3] нь 2-р свеч (small body, gap down)
        # [-2] нь 3-р свеч (bullish, closes into candle 1)
        o1, h1, l1, c1 = opens[-4], highs[-4], lows[-4], closes[-4]
        o2, h2, l2, c2 = opens[-3], highs[-3], lows[-3], closes[-3]
        o3, h3, l3, c3 = opens[-2], highs[-2], lows[-2], closes[-2]

        m1 = self._metrics(o1, h1, l1, c1)
        m2 = self._metrics(o2, h2, l2, c2)
        m3 = self._metrics(o3, h3, l3, c3)

        is_c1_bearish = not m1["bullish"] and m1["body_pct"] > 0.4
        is_c2_small = m2["body_pct"] < 0.3
        is_c3_bullish = m3["bullish"] and m3["body_pct"] > 0.4

        # 2 дахь свеч нь 1-р свечний хаалтаас доогуур нээгдсэн эсэх
        gaps_down = max(o2, c2) < c1

        # 3 дахь свечний хаалт 1-р свечний биеийн 50%-иас дээш орсон эсэх
        closes_halfway = c3 >= (c1 + 0.5 * m1["body"])

        return is_c1_bearish and is_c2_small and is_c3_bullish and (gaps_down or closes_halfway)

    def _manual_evening_star(self, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> bool:
        """
        Гар аргаар Evening Star (Үдшийн од) паттерн шалгах.

        Parameters
        ----------
        opens, highs, lows, closes : np.ndarray
            Нээлт, орой, ёроол, хаалтын үнийн массивууд
        """
        o1, h1, l1, c1 = opens[-4], highs[-4], lows[-4], closes[-4]
        o2, h2, l2, c2 = opens[-3], highs[-3], lows[-3], closes[-3]
        o3, h3, l3, c3 = opens[-2], highs[-2], lows[-2], closes[-2]

        m1 = self._metrics(o1, h1, l1, c1)
        m2 = self._metrics(o2, h2, l2, c2)
        m3 = self._metrics(o3, h3, l3, c3)

        is_c1_bullish = m1["bullish"] and m1["body_pct"] > 0.4
        is_c2_small = m2["body_pct"] < 0.3
        is_c3_bearish = not m3["bullish"] and m3["body_pct"] > 0.4

        # 2 дахь свеч нь 1-р свечний хаалтаас дээгүүр нээгдсэн эсэх
        gaps_up = min(o2, c2) > c1

        # 3 дахь свечний хаалт 1-р свечний биеийн 50%-иас доош орсон эсэх
        closes_halfway = c3 <= (c1 - 0.5 * m1["body"])

        return is_c1_bullish and is_c2_small and is_c3_bearish and (gaps_up or closes_halfway)

    def _hammer(self, m: Dict[str, Any]) -> bool:
        """Hammer (Бух Молот): доод сүүл >= 2x бие, дээд сүүл <= бие."""
        return (
            m["body"] > 0
            and m["lower"] >= 2.0 * m["body"]
            and m["upper"] <= m["body"]
            and m["body_pct"] < 0.4
        )

    def _inverted_hammer(self, m: Dict[str, Any]) -> bool:
        """Урвуу Hammer: дээд сүүл >= 2x бие, доод сүүл <= бие."""
        return (
            m["body"] > 0
            and m["upper"] >= 2.0 * m["body"]
            and m["lower"] <= m["body"]
            and m["body_pct"] < 0.4
        )

    def _shooting_star(self, m: Dict[str, Any]) -> bool:
        """Shooting Star (Буух одон): дээд сүүл >= 2x бие, баавгайн свеч."""
        return self._inverted_hammer(m) and not m["bullish"]

    def _doji(self, m: Dict[str, Any]) -> bool:
        """Doji: бие нь нийт хэлбэлзлийн 5%-иас бага."""
        return m["body_pct"] < 0.05 and m["rng"] > 0

    def _bullish_engulfing(self, prev: Dict[str, Any], curr: Dict[str, Any],
                           prev_c: float, prev_o: float,
                           curr_c: float, curr_o: float) -> bool:
        """Бух залгиулалт: одоогийн ногоон бие өмнөхийн улаан биеийг бүрэн хамрана."""
        return (
            not prev["bullish"]
            and curr["bullish"]
            and curr_o <= prev_c
            and curr_c >= prev_o
            and curr["body"] > prev["body"]
        )

    def _bearish_engulfing(self, prev: Dict[str, Any], curr: Dict[str, Any],
                           prev_c: float, prev_o: float,
                           curr_c: float, curr_o: float) -> bool:
        """Баавгай залгиулалт: одоогийн улаан бие өмнөхийн ногоон биеийг бүрэн хамрана."""
        return (
            prev["bullish"]
            and not curr["bullish"]
            and curr_o >= prev_c
            and curr_c <= prev_o
            and curr["body"] > prev["body"]
        )

    # ── Гол шинжилгээний функц ──────────────────────────────────────────────

    def detect_patterns(self) -> CandleResult:
        """
        Хамгийн сүүлийн хаагдсан свеч дээр TA-Lib болон гар аргаар паттерн таних.
        IndexError болон дата төрлийн зөрчлөөс бүрэн хамгаалагдсан.

        Returns
        -------
        CandleResult
            Илэрсэн паттерны үр дүн
        """
        # Хамгаалалт: 3 свечний паттерн шалгахад дор хаяж 4 свеч хэрэгтэй
        # (хамгийн сүүлчийн хаагдаагүй свеч [-1]-ийг алгасаад, [-2], [-3], [-4]-ийг шалгана)
        if self.df is None or len(self.df) < 4:
            return CandleResult("NONE", "NONE", 0.0, "Дата хүрэлцэхгүй (хамгийн багадаа 4 свеч шаардлагатай)")

        # Өгөгдлийн төрлийг хөрвүүлэх (TA-Lib болон numpy-д зориулж float64 болгоно)
        try:
            opens = self.df["open"].values.astype(np.float64)
            highs = self.df["high"].values.astype(np.float64)
            lows = self.df["low"].values.astype(np.float64)
            closes = self.df["close"].values.astype(np.float64)
        except KeyError as e:
            log.error(f"DataFrame-д шаардлагатай багана байхгүй байна: {e}")
            return CandleResult("NONE", "NONE", 0.0, f"Баганын алдаа: {e}")
        except Exception as e:
            log.error(f"Өгөгдлийг хөрвүүлэхэд алдаа гарлаа: {e}")
            return CandleResult("NONE", "NONE", 0.0, f"Хөрвүүлэлтийн алдаа: {e}")

        # Сүүлийн хаагдсан свечүүдийг авах
        curr_row = self.df.iloc[-2]
        prev_row = self.df.iloc[-3]

        co, ch, cl, cc = float(curr_row["open"]), float(curr_row["high"]), float(curr_row["low"]), float(curr_row["close"])
        po, ph, pl, pc = float(prev_row["open"]), float(prev_row["high"]), float(prev_row["low"]), float(prev_row["close"])

        curr_m = self._metrics(co, ch, cl, cc)
        prev_m = self._metrics(po, ph, pl, pc)

        # ── Volume Баталгаажуулалт ──────────────────────────────────────
        vol_ok = True
        if "volume" in self.df.columns:
            lookback_vol = min(len(self.df), 20)
            avg_vol = self.df["volume"].tail(lookback_vol).mean()
            curr_vol = float(self.df["volume"].iloc[-2])
            vol_ok = (curr_vol >= avg_vol * 0.8) if avg_vol > 0 else True

        # ── 1. TA-Lib-ээр 3 свечний паттерн шалгах ───────────────────────────
        if HAS_TALIB:
            try:
                # Morning Star шалгах
                morning_stars = talib.CDLMORNINGSTAR(opens, highs, lows, closes)
                if morning_stars[-2] > 0:
                    return CandleResult("MORNING_STAR", "BULLISH_CANDLE", 0.95,
                                        "Morning Star — Эргэлтийн маш хүчтэй 3-свечний Бух паттерн")

                # Evening Star шалгах
                evening_stars = talib.CDLEVENINGSTAR(opens, highs, lows, closes)
                if evening_stars[-2] < 0:
                    return CandleResult("EVENING_STAR", "BEARISH_CANDLE", 0.95,
                                        "Evening Star — Эргэлтийн маш хүчтэй 3-свечний Баавгай паттерн")

                # Бусад TA-Lib паттерн шалгалт (Бух/Баавгай залгиулалт)
                engulfings = talib.CDLENGULFING(opens, highs, lows, closes)
                if engulfings[-2] > 0 and vol_ok:
                    return CandleResult("BULLISH_ENGULFING", "BULLISH_CANDLE", 0.90,
                                        "Bullish Engulfing (TA-Lib) — Хүчтэй Бух залгиулалт")
                elif engulfings[-2] < 0 and vol_ok:
                    return CandleResult("BEARISH_ENGULFING", "BEARISH_CANDLE", 0.90,
                                        "Bearish Engulfing (TA-Lib) — Хүчтэй Баавгай залгиулалт")

                # Hammer (Молот)
                if talib.CDLHAMMER(opens, highs, lows, closes)[-2] > 0:
                    return CandleResult("HAMMER", "BULLISH_CANDLE", 0.75,
                                        "Hammer (TA-Lib) — Дэмжлэг дээрх эргэлтийн дохио")

                # Shooting Star
                if talib.CDLSHOOTINGSTAR(opens, highs, lows, closes)[-2] > 0:
                    return CandleResult("SHOOTING_STAR", "BEARISH_CANDLE", 0.75,
                                        "Shooting Star (TA-Lib) — Эсэргүүцэл дээрх эргэлтийн дохио")

                # Inverted Hammer
                if talib.CDLINVERTEDHAMMER(opens, highs, lows, closes)[-2] > 0:
                    return CandleResult("INV_HAMMER", "BULLISH_CANDLE", 0.55,
                                        "Inverted Hammer (TA-Lib) — Урвуу молот")

                # Doji
                if talib.CDLDOJI(opens, highs, lows, closes)[-2] > 0:
                    return CandleResult("DOJI", "NONE", 0.30,
                                        "Doji (TA-Lib) — Тодорхойгүй, чиглэл эргэж магадгүй")

            except Exception as e:
                log.error(f"TA-Lib паттерн илрүүлэлтэд алдаа гарлаа: {e}. Fallback руу шилжиж байна.")

        # ── 2. Гар аргаар паттерн шалгах (TA-Lib байхгүй эсвэл алдаа гарсан үед) ─
        if self._manual_morning_star(opens, highs, lows, closes):
            return CandleResult("MORNING_STAR", "BULLISH_CANDLE", 0.95,
                                "Morning Star (Manual) — Эргэлтийн маш хүчтэй 3-свечний Бух паттерн")

        if self._manual_evening_star(opens, highs, lows, closes):
            return CandleResult("EVENING_STAR", "BEARISH_CANDLE", 0.95,
                                "Evening Star (Manual) — Эргэлтийн маш хүчтэй 3-свечний Баавгай паттерн")

        if self._bullish_engulfing(prev_m, curr_m, pc, po, cc, co) and vol_ok:
            return CandleResult("BULLISH_ENGULFING", "BULLISH_CANDLE", 0.90,
                                "Bullish Engulfing (Manual) — Хүчтэй Бух залгиулалт")

        if self._bearish_engulfing(prev_m, curr_m, pc, po, cc, co) and vol_ok:
            return CandleResult("BEARISH_ENGULFING", "BEARISH_CANDLE", 0.90,
                                "Bearish Engulfing (Manual) — Хүчтэй Баавгай залгиулалт")

        if self._hammer(curr_m):
            return CandleResult("HAMMER", "BULLISH_CANDLE", 0.75,
                                "Hammer (Manual) — Дэмжлэг дээрх эргэлтийн дохио")

        if self._shooting_star(curr_m):
            return CandleResult("SHOOTING_STAR", "BEARISH_CANDLE", 0.75,
                                "Shooting Star (Manual) — Эсэргүүцэл дээрх эргэлтийн дохио")

        if self._inverted_hammer(curr_m) and curr_m["bullish"]:
            return CandleResult("INV_HAMMER", "BULLISH_CANDLE", 0.55,
                                "Inverted Hammer (Manual) — Урвуу молот")

        if self._doji(curr_m):
            return CandleResult("DOJI", "NONE", 0.30,
                                "Doji (Manual) — Тодорхойгүй, чиглэл эргэж магадгүй")

        return CandleResult("NONE", "NONE", 0.0, "Тодорхой паттерн илрээгүй")

    def get_score(self, result: CandleResult, sr_zone: str, expected_signal: str) -> float:
        """
        Свечний оноог бодож гаргах (max 0.30).
        Паттерн нь Дэмжлэг/Эсэргүүцлийн бүстэй болон анхны дохиотой тохирвол бүрэн оноо авна.

        Parameters
        ----------
        result : CandleResult
            Свечний шинжилгээний үр дүн
        sr_zone : str
            Дэмжлэг/Эсэргүүцлийн бүсийн төлөв ("SUPPORT_ZONE" | "RESISTANCE_ZONE" | "NEUTRAL")
        expected_signal : str
            Шүүлт хийх анхан шатны дохио ("BUY" | "SELL")

        Returns
        -------
        float
            Бодож гаргасан оноо (0.0 - 0.30)
        """
        if result.signal == "NONE":
            return 0.0

        direction_match = (
            (expected_signal == "BUY" and result.signal == "BULLISH_CANDLE") or
            (expected_signal == "SELL" and result.signal == "BEARISH_CANDLE")
        )
        if not direction_match:
            return 0.0

        base = result.strength * 0.30  # Max боломжит оноо нь 0.30

        # Бүстэй тохирч байгаа эсэх баталгаажуулалт
        zone_match = (
            (result.signal == "BULLISH_CANDLE" and sr_zone == "SUPPORT_ZONE") or
            (result.signal == "BEARISH_CANDLE" and sr_zone == "RESISTANCE_ZONE")
        )
        return base if zone_match else base * 0.5
