import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any

from utils.logger import get_logger

log = get_logger("SR")


@dataclass
class SRLevels:
    """
    Дэмжлэг болон Эсэргүүцлийн түвшин, бүсүүдийг хадгалах дата класс.
    Хуучин кодтой 100% нийцтэй бөгөөд ахисан түвшний бүсийн мэдээллийг нэмж хадгална.

    Attributes
    ----------
    support : np.ndarray
        Дэмжлэгийн түвшнүүдийн дундаж үнийн массив
    resistance : np.ndarray
        Эсэргүүцлийн түвшнүүдийн дундаж үнийн массив
    nearest_support : Optional[float]
        Одоогийн үнэд хамгийн ойр байгаа дэмжлэгийн дундаж үнэ
    nearest_resistance : Optional[float]
        Одоогийн үнэд хамгийн ойр байгаа эсэргүүцлийн дундаж үнэ
    zone : str
        Одоогийн үнийн бүсийн байдал ("SUPPORT_ZONE" | "RESISTANCE_ZONE" | "NEUTRAL")
    support_zones : List[Tuple[float, float]]
        Дэмжлэгийн бүсүүдийн [доод, дээд] хязгааруудын жагсаалт
    resistance_zones : List[Tuple[float, float]]
        Эсэргүүцлийн бүсүүдийн [доод, дээд] хязгааруудын жагсаалт
    """
    support: np.ndarray
    resistance: np.ndarray
    nearest_support: Optional[float]
    nearest_resistance: Optional[float]
    zone: str
    support_zones: List[Tuple[float, float]] = field(default_factory=list)
    resistance_zones: List[Tuple[float, float]] = field(default_factory=list)


class SupportResistanceAnalyzer:
    """
    Зах зээлийн дэмжлэг, эсэргүүцлийн түвшнүүдийг олж, ATR-д суурилсан динамик үнийн бүс үүсгэх класс.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        """
        SupportResistanceAnalyzer үүсгэх.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV өгөгдлийг агуулсан DataFrame
        """
        self.df = df.copy()

    def _calculate_atr(self, period: int = 14) -> float:
        """
        Сүүлийн үеийн ATR (Average True Range)-ийг тооцож хэлбэлзлийг олох.
        IndexError болон дата дутуу байхаас хамгаалагдсан.

        Parameters
        ----------
        period : int, default 14
            ATR бодоход ашиглах үе

        Returns
        -------
        float
            Бодож гаргасан ATR утга (эсвэл fallback утга)
        """
        if len(self.df) < 2:
            return 1.0

        try:
            high = self.df["high"]
            low = self.df["low"]
            close = self.df["close"]
            close_prev = close.shift(1)

            tr1 = high - low
            tr2 = (high - close_prev).abs()
            tr3 = (low - close_prev).abs()

            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            lookback = min(len(self.df), period)
            atr = tr.rolling(window=lookback).mean().iloc[-1]

            if pd.isna(atr) or atr == 0:
                atr = float(self.df["close"].iloc[-1] * 0.002)
            return float(atr)
        except Exception as e:
            log.error(f"ATR тооцоолоход алдаа гарлаа: {e}")
            return float(self.df["close"].iloc[-1] * 0.002)

    def _cluster_zones(self, levels: np.ndarray, atr: float, tol: float = 0.002) -> List[Tuple[float, float, float]]:
        """
        Ойрхон түвшнүүдийг нэгтгэж, ATR-д суурилсан бүсүүдийг (low, high, mid) үүсгэнэ.

        Parameters
        ----------
        levels : np.ndarray
            Оргил/ёроолын үнийн түвшнүүд
        atr : float
            Хэлбэлзлийг тодорхойлох ATR утга
        tol : float, default 0.002
            Нэгтгэх зөвшөөрөгдөх дээд хэмжээ (0.2%)

        Returns
        -------
        List[Tuple[float, float, float]]
            Бүсийн [(доод, дээд, дундаж), ...] утгууд
        """
        if len(levels) == 0:
            return []

        sorted_lvls = np.sort(levels)
        clusters: List[List[float]] = []
        current_cluster = [float(sorted_lvls[0])]

        for lvl in sorted_lvls[1:]:
            if abs(lvl - current_cluster[-1]) / current_cluster[-1] <= tol:
                current_cluster.append(float(lvl))
            else:
                clusters.append(current_cluster)
                current_cluster = [float(lvl)]
        clusters.append(current_cluster)

        zones: List[Tuple[float, float, float]] = []
        for cluster in clusters:
            mid = float(np.mean(cluster))
            # Бүсийн өргөн: оргилуудын тарах хүрээ эсвэл 0.25 * ATR (аль их нь)
            cluster_range = max(cluster) - min(cluster)
            half_width = max(cluster_range / 2.0, 0.25 * atr)

            low = mid - half_width
            high = mid + half_width
            zones.append((low, high, mid))

        return zones

    def find_levels(self, distance: int = 10) -> SRLevels:
        """
        Сүүлийн свечүүдээс дэмжлэг, эсэргүүцлийн бүсийг олж тодорхойлох.

        Parameters
        ----------
        distance : int, default 10
            scipy.signal.find_peaks функцийн хоорондын зай

        Returns
        -------
        SRLevels
            Бүх тооцсон S/R бүс болон түвшнүүдийн үр дүн
        """
        # Свечний өгөгдөл хангалтгүй бол хоосон үр дүн буцаана
        if self.df is None or len(self.df) < 15:
            log.warning("S/R тооцоолоход дата хангалтгүй байна.")
            return SRLevels(
                support=np.array([]),
                resistance=np.array([]),
                nearest_support=None,
                nearest_resistance=None,
                zone="NEUTRAL"
            )

        try:
            highs = self.df["high"].values.astype(np.float64)
            lows = self.df["low"].values.astype(np.float64)
            current = float(self.df["close"].iloc[-1])
        except Exception as e:
            log.error(f"Өгөгдөл авахад алдаа гарлаа: {e}")
            return SRLevels(
                support=np.array([]),
                resistance=np.array([]),
                nearest_support=None,
                nearest_resistance=None,
                zone="NEUTRAL"
            )

        price_mean = np.mean(highs) if len(highs) > 0 else 1.0
        prominence = price_mean * 0.001

        try:
            peak_idx, _ = find_peaks(highs, distance=distance, prominence=prominence)
            trough_idx, _ = find_peaks(-lows, distance=distance, prominence=prominence)
        except Exception as e:
            log.error(f"find_peaks ажиллуулахад алдаа гарлаа: {e}")
            peak_idx, trough_idx = np.array([]), np.array([])

        atr = self._calculate_atr()

        # Ойрхон цэгүүдийг нэгтгэн бүс үүсгэх
        res_zones = self._cluster_zones(highs[peak_idx], atr)
        sup_zones = self._cluster_zones(lows[trough_idx], atr)

        # Дундаж түвшнүүд (хуучин кодтой 100% нийцүүлэхэд хэрэгтэй)
        resistance_mids = np.array([z[2] for z in res_zones])
        support_mids = np.array([z[2] for z in sup_zones])

        # Одоогийн үнэ аль нэг бүсэд байгаа эсэхийг шалгах
        zone = self._check_zone(current, sup_zones, res_zones)

        # Ойр байгаа түвшнүүдийг хайх
        nearest_sup = self._nearest_below(current, support_mids)
        nearest_res = self._nearest_above(current, resistance_mids)

        return SRLevels(
            support=support_mids,
            resistance=resistance_mids,
            nearest_support=nearest_sup,
            nearest_resistance=nearest_res,
            zone=zone,
            support_zones=[(z[0], z[1]) for z in sup_zones],
            resistance_zones=[(z[0], z[1]) for z in res_zones]
        )

    def _check_zone(self, price: float, support: Any, resistance: Any, tol_pct: float = 0.001) -> str:
        """
        Одоогийн үнэ дэмжлэг эсвэл эсэргүүцлийн бүсийн дотор байгааг шалгах.
        Энэ функц нь list[tuple] болон np.ndarray оролтыг хоёуланг нь дэмждэг (уян хатан байдал).

        Parameters
        ----------
        price : float
            Шалгах үнэ (Одоогийн хаалтын үнэ)
        support : Any
            Дэмжлэгийн бүсүүдийн жагсаалт эсвэл түвшнүүдийн массив
        resistance : Any
            Эсэргүүцлийн бүсүүдийн жагсаалт эсвэл түвшнүүдийн массив
        tol_pct : float, default 0.001
            Хуучин хэлбэрээр шалгахад ашиглах хувь (0.1%)

        Returns
        -------
        str
            Үр дүн ("SUPPORT_ZONE" | "RESISTANCE_ZONE" | "NEUTRAL")
        """
        # Ахисан түвшний бүсийн жагсаалт шалгалт (list of tuples/lists)
        if isinstance(support, list) and len(support) > 0 and isinstance(support[0], (tuple, list)):
            for zone in support:
                low, high = zone[0], zone[1]
                if low <= price <= high:
                    return "SUPPORT_ZONE"
            for zone in resistance:
                low, high = zone[0], zone[1]
                if low <= price <= high:
                    return "RESISTANCE_ZONE"
            return "NEUTRAL"

        # Хуучин дан шугамын шалгалт (fallback)
        tol = price * tol_pct
        if isinstance(support, (np.ndarray, list)):
            if any(abs(price - s) <= tol for s in support):
                return "SUPPORT_ZONE"
        if isinstance(resistance, (np.ndarray, list)):
            if any(abs(price - r) <= tol for r in resistance):
                return "RESISTANCE_ZONE"
        return "NEUTRAL"

    def _nearest_below(self, price: float, levels: np.ndarray) -> Optional[float]:
        """Өгөгдсөн үнээс доош байгаа хамгийн ойрын түвшинг олох."""
        below = [float(l) for l in levels if l < price]
        return max(below) if below else None

    def _nearest_above(self, price: float, levels: np.ndarray) -> Optional[float]:
        """Өгөгдсөн үнээс дээш байгаа хамгийн ойрын түвшинг олох."""
        above = [float(l) for l in levels if l > price]
        return min(above) if above else None

    def confirm_with_htf(self, htf_levels: SRLevels, current_price: float, signal: str) -> bool:
        """
        Том цагийн (4h) дэмжлэг/эсэргүүцэл нь 1h дохиог зөрчиж байгаа эсэхийг шалгах.

        Parameters
        ----------
        htf_levels : SRLevels
            Том цагийн үеийн S/R үр дүн
        current_price : float
            Одоогийн үнэ
        signal : str
            Орох дохионы чиглэл ("BUY" | "SELL")

        Returns
        -------
        bool
            Дохио баталгаажсан эсэх
        """
        if signal == "BUY":
            # 4h эсэргүүцэлд хэт ойртсон үед BUY хийхийг хориглоно
            if htf_levels.nearest_resistance:
                dist_pct = (htf_levels.nearest_resistance - current_price) / current_price
                if dist_pct < 0.003:  # 0.3%-иас бага зайтай бол алгасна
                    log.info(f"4h resistance хэт ойрхон ({dist_pct:.3%}) — BUY баталгаажсангүй")
                    return False
        elif signal == "SELL":
            # 4h дэмжлэгт хэт ойртсон үед SELL хийхийг хориглоно
            if htf_levels.nearest_support:
                dist_pct = (current_price - htf_levels.nearest_support) / current_price
                if dist_pct < 0.003:  # 0.3%-иас бага зайтай бол алгасна
                    log.info(f"4h support хэт ойрхон ({dist_pct:.3%}) — SELL баталгаажсангүй")
                    return False
        return True
