"""
TechnicalAnalyzer — 4 дэд модулийн нэгдсэн тархи

Оноог ингэж хуваарилна:
    S/R бүс       → max 0.40
    Fibonacci      → max 0.30  (S/R + golden zone нийцвэл)
    Свечний паттерн → max 0.30  (strength × 0.30)
    Chart pattern  → max 0.20  (confidence × 0.20) — нэмэгдэл оноо
    ─────────────────────────
    Нийт            ≈ 0–1.20  (normalize хийнэ)

Шийдвэр:
    buy_score  ≥ 0.50 → BUY
    sell_score ≥ 0.50 → SELL
    else              → NEUTRAL
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import pandas as pd

from analysis.technical_analyzer.support_resistance import SupportResistanceAnalyzer, SRLevels
from analysis.technical_analyzer.fibonacci import FibonacciAnalyzer, FibLevels
from analysis.technical_analyzer.candlestick import CandlestickAnalyzer, CandleResult
from analysis.technical_analyzer.chart_patterns import ChartPatternAnalyzer, PatternResult
from utils.logger import get_logger

log = get_logger("AdvancedTA")


@dataclass
class AdvancedTAScore:
    """
    Техникийн нэгдсэн нарийвчилсан шинжилгээний үр дүнг хадгалах дата класс.

    Attributes
    ----------
    signal : str
        Нэгдсэн шийдвэрийн дохио ("BUY" | "SELL" | "NEUTRAL")
    score : float
        Нормальчилсан нэгдсэн оноо (0.0 - 1.0)
    sr_zone : str
        Одоогийн үнийн дэмжлэг/эсэргүүцлийн бүсийн төлөв
    fib_in_golden : bool
        Үнэ Фибоначчийн алтан бүсэд байгаа эсэх
    candle_pattern : str
        Илэрсэн свечний паттерн
    chart_pattern : str
        Илэрсэн чартын паттерн
    sr_htf_ok : bool
        Том цаг (4h) дээрх S/R бүс зөрчилдөөгүй эсэх
    details : Dict[str, Any]
        Нарийвчилсан задаргаанууд болон тооцооллууд
    """
    signal: str
    score: float
    sr_zone: str
    fib_in_golden: bool
    candle_pattern: str
    chart_pattern: str
    sr_htf_ok: bool
    details: Dict[str, Any] = field(default_factory=dict)


def generate_ta_score(
    df_primary: pd.DataFrame,
    df_confirm: Optional[pd.DataFrame] = None,
    preliminary_signal: str = "BUY",
) -> AdvancedTAScore:
    """
    4 дэд модулийг ажиллуулж, зах зээлийн техникийн шинжилгээний нэгдсэн оноог бодож гаргах.
    IndexError болон дата төрөл, индексжүүлэлтийн алдаанаас бүрэн хамгаалагдсан.

    Parameters
    ----------
    df_primary : pd.DataFrame
        Үндсэн арилжаа хийх цагийн (жишээ нь 1h) OHLCV өгөгдөл
    df_confirm : Optional[pd.DataFrame], default None
        Баталгаажуулах том цагийн (жишээ нь 4h) OHLCV өгөгдөл
    preliminary_signal : str, default "BUY"
        RSI/MACD-ийн анхан шатны дохио ("BUY" эсвэл "SELL")

    Returns
    -------
    AdvancedTAScore
        Шинжилгээний нэгдсэн үр дүн, оноо
    """
    # ── Аюулгүй байдлын шалгалт ───────────────────────────────────────
    if df_primary is None or len(df_primary) < 20:
        log.warning("Шинжилгээ хийхэд үндсэн дата хангалтгүй эсвэл хоосон байна.")
        return AdvancedTAScore(
            signal="NEUTRAL",
            score=0.0,
            sr_zone="NEUTRAL",
            fib_in_golden=False,
            candle_pattern="NONE",
            chart_pattern="NONE",
            sr_htf_ok=True,
            details={
                "sr_score": 0.0,
                "fib_score": 0.0,
                "candle_score": 0.0,
                "chart_score": 0.0,
                "nearest_sup": None,
                "nearest_res": None,
                "fib_level": None,
                "candle_desc": "Дата хүрэлцэхгүй",
                "chart_desc": "Дата хүрэлцэхгүй",
                "htf_ok": True,
            }
        )

    try:
        current_price = float(df_primary["close"].iloc[-1])
    except (KeyError, IndexError) as e:
        log.error(f"Хаалтын үнийг авахад алдаа гарлаа: {e}")
        return AdvancedTAScore(
            signal="NEUTRAL",
            score=0.0,
            sr_zone="NEUTRAL",
            fib_in_golden=False,
            candle_pattern="NONE",
            chart_pattern="NONE",
            sr_htf_ok=True,
            details={}
        )

    # ── 1. Support / Resistance (Дэмжлэг/Эсэргүүцэл) ──────────────────────────
    sr_analyzer = SupportResistanceAnalyzer(df_primary)
    sr_levels = sr_analyzer.find_levels()
    sr_zone = sr_levels.zone

    sr_score = 0.0
    if sr_zone == "SUPPORT_ZONE" and preliminary_signal == "BUY":
        sr_score = 0.40
    elif sr_zone == "RESISTANCE_ZONE" and preliminary_signal == "SELL":
        sr_score = 0.40
    elif sr_zone == "NEUTRAL":
        sr_score = 0.10  # Шууд бүс дээр биш ч бусад дохиогоор арилжиж болно

    # ── 2. Fibonacci (Фибоначчи) ───────────────────────────────────────────
    fib_analyzer = FibonacciAnalyzer(df_primary)
    fib_levels = fib_analyzer.calculate_levels()
    fib_score = fib_analyzer.get_score(fib_levels, sr_zone)

    # ── 3. Candlestick Pattern (Свечний паттерн) ─────────────────────────
    candle_analyzer = CandlestickAnalyzer(df_primary)
    candle_result = candle_analyzer.detect_patterns()
    candle_score = candle_analyzer.get_score(candle_result, sr_zone, preliminary_signal)

    # ── 4. Chart Pattern (Чартын паттерн) ─────────────────────────────
    chart_analyzer = ChartPatternAnalyzer(df_primary)
    chart_result = chart_analyzer.detect_double_patterns()
    chart_score = chart_analyzer.get_score(chart_result, preliminary_signal)

    # ── 4h S/R Баталгаажуулалт ───────────────────────────────────────
    htf_ok = True
    if df_confirm is not None and len(df_confirm) >= 20:
        htf_sr = SupportResistanceAnalyzer(df_confirm)
        htf_levels = htf_sr.find_levels()
        htf_ok = sr_analyzer.confirm_with_htf(htf_levels, current_price, preliminary_signal)

    if not htf_ok:
        # Том цагийн бүс зөрчилдвөл дохионы оноог 50% бууруулна
        sr_score *= 0.5
        fib_score *= 0.5
        candle_score *= 0.5
        chart_score *= 0.5

    # ── Онооны нэгтгэл ба нормальчилал ──────────────────────────────
    buy_score = 0.0
    sell_score = 0.0

    if preliminary_signal == "BUY":
        buy_score = sr_score + fib_score + candle_score + chart_score
    elif preliminary_signal == "SELL":
        sell_score = sr_score + fib_score + candle_score + chart_score

    # Нэгдсэн хамгийн их боломжит оноо нь 1.20 орчим (нормальчилна)
    MAX_POSSIBLE = 1.20
    buy_score = round(min(buy_score / MAX_POSSIBLE, 1.0), 3)
    sell_score = round(min(sell_score / MAX_POSSIBLE, 1.0), 3)

    if buy_score >= 0.50:
        signal = "BUY"
        final_score = buy_score
    elif sell_score >= 0.50:
        signal = "SELL"
        final_score = sell_score
    else:
        signal = "NEUTRAL"
        final_score = max(buy_score, sell_score)

    log.info(
        f"AdvancedTA [{preliminary_signal}] → {signal} ({final_score:.2f}) | "
        f"SR={sr_zone} Fib={'gold' if fib_levels.in_golden_zone else '-'} "
        f"Candle={candle_result.pattern} Chart={chart_result.pattern} 4h={'ok' if htf_ok else 'X'}"
    )

    return AdvancedTAScore(
        signal=signal,
        score=final_score,
        sr_zone=sr_zone,
        fib_in_golden=fib_levels.in_golden_zone,
        candle_pattern=candle_result.pattern,
        chart_pattern=chart_result.pattern,
        sr_htf_ok=htf_ok,
        details={
            "sr_score": sr_score,
            "fib_score": fib_score,
            "candle_score": candle_score,
            "chart_score": chart_score,
            "nearest_sup": sr_levels.nearest_support,
            "nearest_res": sr_levels.nearest_resistance,
            "fib_level": fib_levels.nearest_level,
            "candle_desc": candle_result.description,
            "chart_desc": chart_result.description,
            "htf_ok": htf_ok,
        },
    )
