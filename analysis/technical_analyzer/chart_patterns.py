import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from dataclasses import dataclass
from typing import Optional, Tuple

from utils.logger import get_logger

log = get_logger("ChartPattern")


@dataclass
class PatternResult:
    """
    Чартын паттерн шинжилгээний үр дүнг хадгалах дата класс.

    Attributes
    ----------
    pattern : str
        Илэрсэн паттерны нэр ("DOUBLE_BOTTOM" | "DOUBLE_TOP" | "NONE")
    signal : str
        Дохионы чиглэл ("BUY" | "SELL" | "NONE")
    confidence : float
        Паттерны итгэлцүүр (0.0 - 1.0)
    level : Optional[float]
        Паттерны орой/ёроолын дундаж үнэ
    description : str
        Хэрэглэгчид ойлгомжтой тайлбар
    """
    pattern: str
    signal: str
    confidence: float
    level: Optional[float]
    description: str


class ChartPatternAnalyzer:
    """
    Чартын паттернуудыг (Double Top, Double Bottom) орой/ёроолын харьцаа,
    neckline эвдрэл болон үнийн эргэлт (rejection)-ээр илрүүлэх класс.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        """
        ChartPatternAnalyzer үүсгэх.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV өгөгдлийг агуулсан DataFrame
        """
        self.df = df.copy()

    def _check_rejection(self, index: int, is_bottom: bool) -> Tuple[bool, float]:
        """
        Паттерны хоёр дахь орой/ёроол дээр үүссэн үнийн хүчтэй эргэлт (wick rejection)-ийг шалгах.

        Parameters
        ----------
        index : int
            Шалгах свечний индекс
        is_bottom : bool
            True бол ёроолын эргэлт (Double Bottom), False бол оройн эргэлт (Double Top)

        Returns
        -------
        Tuple[bool, float]
            (эргэлт_илэрсэн_эсэх, эргэлтийн_хүч)
        """
        # Индексийн аюулгүй байдлыг хангах
        if index < 0 or index >= len(self.df):
            return False, 0.0

        try:
            # Свеч болон түүний хажуугийн свечүүдийг шалгаж, хамгийн хүчтэй сүүлийг олно
            max_shadow_pct = 0.0
            rejection_found = False

            # index-1, index, index+1 свечүүдийг харна (аюулгүй хүрээнд)
            start_i = max(0, index - 1)
            end_i = min(len(self.df) - 1, index + 1)

            for i in range(start_i, end_i + 1):
                row = self.df.iloc[i]
                o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
                rng = h - l
                if rng <= 0:
                    continue

                body = abs(c - o)
                if is_bottom:
                    # Доод сүүл урт байх (худалдан авагчид үнийг дээш түлхсэн)
                    lower_shadow = min(o, c) - l
                    shadow_pct = lower_shadow / rng
                    # Сүүл нь биеэс 1.3 дахин урт эсвэл нийт хүрээний 35%-иас их бол эргэлт гэж үзнэ
                    if lower_shadow >= 1.3 * body or shadow_pct >= 0.35:
                        rejection_found = True
                        if shadow_pct > max_shadow_pct:
                            max_shadow_pct = shadow_pct
                else:
                    # Дээд сүүл урт байх (худалдагчид үнийг доош түлхсэн)
                    upper_shadow = h - max(o, c)
                    shadow_pct = upper_shadow / rng
                    # Сүүл нь биеэс 1.3 дахин урт эсвэл нийт хүрээний 35%-иас их бол эргэлт гэж үзнэ
                    if upper_shadow >= 1.3 * body or shadow_pct >= 0.35:
                        rejection_found = True
                        if shadow_pct > max_shadow_pct:
                            max_shadow_pct = shadow_pct

            return rejection_found, float(max_shadow_pct)
        except Exception as e:
            log.error(f"Rejection шалгахад алдаа гарлаа: {e}")
            return False, 0.0

    def detect_double_patterns(self) -> PatternResult:
        """
        Double Bottom болон Double Top паттернуудыг илрүүлэх.

        Returns
        -------
        PatternResult
            Илэрсэн паттерны үр дүн
        """
        if self.df is None or len(self.df) < 20:
            return PatternResult("NONE", "NONE", 0.0, None, "Дата хүрэлцэхгүй (хамгийн багадаа 20 свеч шаардлагатай)")

        db = self._detect_double_bottom()
        if db.pattern != "NONE":
            return db
        return self._detect_double_top()

    # ── Double Bottom (Хоёр дахь ёроол) ─────────────────────────────────────

    def _detect_double_bottom(self) -> PatternResult:
        """
        Double Bottom (Хоёр дахь ёроол) паттернийг нарийвчлан илрүүлэх логик.
        """
        try:
            lows = self.df["low"].values.astype(np.float64)
            closes = self.df["close"].values.astype(np.float64)
        except Exception as e:
            log.error(f"Double Bottom өгөгдөл бэлтгэхэд алдаа гарлаа: {e}")
            return PatternResult("NONE", "NONE", 0.0, None, f"Өгөгдлийн алдаа: {e}")

        price_level = np.mean(lows) if len(lows) > 0 else 1.0
        prominence = price_level * 0.001

        try:
            trough_idx, _ = find_peaks(-lows, distance=8, prominence=prominence)
        except Exception as e:
            log.error(f"find_peaks trough олоход алдаа: {e}")
            trough_idx = np.array([])

        if len(trough_idx) < 2:
            return PatternResult("NONE", "NONE", 0.0, None, "Ёроолын тоо хангалтгүй")

        # Хамгийн сүүлийн 2 ёроолыг авна
        t1, t2 = int(trough_idx[-2]), int(trough_idx[-1])
        low1, low2 = lows[t1], lows[t2]

        # 1. Хоёр ёроолын үнийн харьцааг шалгах (зөрүү 0.5%-иас ихгүй байх)
        similarity = abs(low1 - low2) / max(low1, low2)
        if similarity > 0.005:
            return PatternResult("NONE", "NONE", 0.0, None,
                                 f"Ёроолуудын үнийн зөрүү хэт их: {similarity:.3%}")

        # 2. Хоёр ёроолын хооронд Neckline оргил байгааг шалгах
        between_highs = self.df["high"].values[t1:t2]
        if len(between_highs) == 0:
            return PatternResult("NONE", "NONE", 0.0, None, "Ёроолуудын хооронд лаа байхгүй")
        neckline = float(between_highs.max())
        pattern_level = float((low1 + low2) / 2)

        # 3. Үнийн эргэлт (wick rejection) шалгах
        rejection_ok, reject_strength = self._check_rejection(t2, is_bottom=True)

        # 4. Neckline Breakout шалгах (хоёр дахь ёроолоос хойш үнэ neckline-ийг давж хаагдсан эсэх)
        after_closes = closes[t2 + 1:]
        neckline_broken = len(after_closes) > 0 and float(after_closes[-1]) > neckline

        # 5. Итгэлцүүр (Confidence) бодох:
        # - Үнийн ижил төлөв: max 0.50
        # - Үнийн хүчтэй эргэлт (rejection): max 0.20
        # - Neckline breakout: max 0.30
        similarity_score = (1.0 - similarity / 0.005) * 0.50
        rejection_score = 0.20 if rejection_ok else 0.0
        breakout_score = 0.30 if neckline_broken else 0.0

        confidence = round(similarity_score + rejection_score + breakout_score, 3)
        confidence = min(max(confidence, 0.0), 1.0)

        # Хэт сул паттернийг алгасна
        if confidence < 0.45:
            return PatternResult("NONE", "NONE", 0.0, None,
                                 f"Double Bottom сул байна (confidence={confidence:.2f})")

        desc = (f"Double Bottom @ {pattern_level:.5f} | similarity={(1-similarity/0.005):.1%} | "
                f"rejection={'тийм' if rejection_ok else 'үгүй'} ({reject_strength:.1%}) | "
                f"breakout={'тийм' if neckline_broken else 'үгүй'}")
        log.info(desc)

        return PatternResult(
            pattern="DOUBLE_BOTTOM",
            signal="BUY",
            confidence=confidence,
            level=pattern_level,
            description=desc,
        )

    # ── Double Top (Хоёр дахь орой) ─────────────────────────────────────────

    def _detect_double_top(self) -> PatternResult:
        """
        Double Top (Хоёр дахь орой) паттернийг нарийвчлан илрүүлэх логик.
        """
        try:
            highs = self.df["high"].values.astype(np.float64)
            closes = self.df["close"].values.astype(np.float64)
        except Exception as e:
            log.error(f"Double Top өгөгдөл бэлтгэхэд алдаа гарлаа: {e}")
            return PatternResult("NONE", "NONE", 0.0, None, f"Өгөгдлийн алдаа: {e}")

        price_level = np.mean(highs) if len(highs) > 0 else 1.0
        prominence = price_level * 0.001

        try:
            peak_idx, _ = find_peaks(highs, distance=8, prominence=prominence)
        except Exception as e:
            log.error(f"find_peaks peak олоход алдаа: {e}")
            peak_idx = np.array([])

        if len(peak_idx) < 2:
            return PatternResult("NONE", "NONE", 0.0, None, "Оройн тоо хангалтгүй")

        p1, p2 = int(peak_idx[-2]), int(peak_idx[-1])
        high1, high2 = highs[p1], highs[p2]

        # 1. Хоёр оройн үнийн харьцааг шалгах (зөрүү 0.5%-иас ихгүй байх)
        similarity = abs(high1 - high2) / max(high1, high2)
        if similarity > 0.005:
            return PatternResult("NONE", "NONE", 0.0, None,
                                 f"Оройнуудын үнийн зөрүү хэт их: {similarity:.3%}")

        # 2. Хоёр оройн хооронд Neckline ёроол байгааг шалгах
        between_lows = self.df["low"].values[p1:p2]
        if len(between_lows) == 0:
            return PatternResult("NONE", "NONE", 0.0, None, "Оройнуудын хооронд лаа байхгүй")
        neckline = float(between_lows.min())
        pattern_level = float((high1 + high2) / 2)

        # 3. Үнийн эргэлт (wick rejection) шалгах
        rejection_ok, reject_strength = self._check_rejection(p2, is_bottom=False)

        # 4. Neckline Breakout шалгах (хоёр дахь оройгоос хойш үнэ neckline-оос доош хаагдсан эсэх)
        after_closes = closes[p2 + 1:]
        neckline_broken = len(after_closes) > 0 and float(after_closes[-1]) < neckline

        # 5. Итгэлцүүр (Confidence) бодох
        similarity_score = (1.0 - similarity / 0.005) * 0.50
        rejection_score = 0.20 if rejection_ok else 0.0
        breakout_score = 0.30 if neckline_broken else 0.0

        confidence = round(similarity_score + rejection_score + breakout_score, 3)
        confidence = min(max(confidence, 0.0), 1.0)

        if confidence < 0.45:
            return PatternResult("NONE", "NONE", 0.0, None,
                                 f"Double Top сул байна (confidence={confidence:.2f})")

        desc = (f"Double Top @ {pattern_level:.5f} | similarity={(1-similarity/0.005):.1%} | "
                f"rejection={'тийм' if rejection_ok else 'үгүй'} ({reject_strength:.1%}) | "
                f"breakout={'тийм' if neckline_broken else 'үгүй'}")
        log.info(desc)

        return PatternResult(
            pattern="DOUBLE_TOP",
            signal="SELL",
            confidence=confidence,
            level=pattern_level,
            description=desc,
        )

    def get_score(self, result: PatternResult, expected_signal: str) -> float:
        """
        Чартын паттерны оноог тооцож өгөх (max 0.20).

        Parameters
        ----------
        result : PatternResult
            Паттерн илрүүлэлтийн үр дүн
        expected_signal : str
            Шүүлт хийх анхан шатны дохио ("BUY" | "SELL")

        Returns
        -------
        float
            Бодож гаргасан нэмэлт оноо (0.0 - 0.20)
        """
        if result.signal == "NONE":
            return 0.0
        if result.signal != expected_signal:
            return 0.0
        return round(result.confidence * 0.20, 3)
