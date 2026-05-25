"""
Weighted strategy combiner.

Aggregates three independent layers into a single trade decision:

| Layer                        | Weight |
|------------------------------|--------|
| Basic TA (RSI/MACD/EMA/BB)   | 40%    |
| Advanced TA (SR/Fib/Candle)  | 30%    |
| X.com sentiment              | 30%    |

A trade fires only when:
1. Basic TA produces a non-NEUTRAL signal with strength ≥ 0.5
2. The 4h confirm timeframe does not contradict the 1h direction
3. Advanced TA does not contradict the basic signal
4. The combined confidence ≥ 0.55
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

from analysis.sentiment import SentimentAnalyzer, SentimentSignal
from analysis.technical import TechnicalAnalyzer, TechnicalSignal
from analysis.technical_analyzer import AdvancedTAScore, generate_ta_score
from utils.logger import get_logger

log = get_logger("Strategy")


@dataclass
class CombinedSignal:
    """Final output handed to the risk manager."""
    symbol: str
    final_signal: str       # "BUY" | "SELL" | "NEUTRAL"
    confidence: float       # 0.0–1.0
    technical: TechnicalSignal
    advanced_ta: AdvancedTAScore
    sentiment: Optional[SentimentSignal]
    reason: str
    score_breakdown: Dict[str, float] = field(default_factory=dict)


class CombinedStrategy:
    """Three-layer ensemble strategy."""

    # Minimum combined confidence to emit a tradeable signal
    CONFIDENCE_THRESHOLD: float = 0.55

    # Per-layer max contributions — must sum to ≤ 1.0
    BASIC_WEIGHT: float = 0.40
    ADVANCED_WEIGHT: float = 0.30
    SENTIMENT_WEIGHT: float = 0.30

    def __init__(self) -> None:
        self.basic_ta = TechnicalAnalyzer()
        self.sentiment = SentimentAnalyzer()

    def evaluate(
        self,
        df_primary: pd.DataFrame,
        df_confirm: Optional[pd.DataFrame],
        symbol: str,
        tf_primary: str = "1h",
        tf_confirm: str = "4h",
    ) -> Optional[CombinedSignal]:
        """
        Run all three layers and return a tradeable signal or None.

        Returns None whenever any of the following is true:
        - Basic TA is NEUTRAL or too weak
        - 1h and 4h directions contradict
        - Advanced TA contradicts basic TA
        - Combined confidence below `CONFIDENCE_THRESHOLD`
        """
        # ── 1. Basic TA (RSI/MACD/EMA/BB) ──────────────────────────────
        basic = self.basic_ta.analyze(df_primary, symbol, tf_primary)
        if not basic or basic.signal == "NEUTRAL":
            return None

        # Multi-timeframe confirmation
        basic_4h = (
            self.basic_ta.analyze(df_confirm, symbol, tf_confirm)
            if df_confirm is not None else None
        )
        if basic_4h and basic_4h.signal not in (basic.signal, "NEUTRAL"):
            log.info(f"{symbol}: {tf_primary}/{tf_confirm} timeframe зөрчилдлөө — skip")
            return None

        basic_score = basic.strength * self.BASIC_WEIGHT

        # ── 2. Advanced TA (SR + Fib + Candle + Chart) ─────────────────
        adv = generate_ta_score(df_primary, df_confirm, basic.signal)
        if adv.signal not in (basic.signal, "NEUTRAL"):
            log.info(
                f"{symbol}: Advanced TA ({adv.signal}) ↔ Basic TA ({basic.signal}) "
                f"зөрчилдлөө — skip"
            )
            return None

        adv_score = adv.score * self.ADVANCED_WEIGHT

        # ── 3. Sentiment ───────────────────────────────────────────────
        sent = self.sentiment.analyze(symbol)
        sent_score, sent_reason = self._sentiment_score(basic.signal, sent)

        # ── 4. Combined confidence ─────────────────────────────────────
        confidence = round(min(basic_score + adv_score + sent_score, 1.0), 3)
        reason = self._build_reason(basic, adv, sent, sent_reason)

        if confidence < self.CONFIDENCE_THRESHOLD:
            log.info(f"{symbol}: confidence хэт бага ({confidence:.2f}) — skip")
            return None

        log.info(
            f"{symbol} FINAL: {basic.signal} | conf={confidence:.2f} | "
            f"basic={basic_score:.2f} adv={adv_score:.2f} sent={sent_score:.2f}"
        )
        return CombinedSignal(
            symbol=symbol,
            final_signal=basic.signal,
            confidence=confidence,
            technical=basic,
            advanced_ta=adv,
            sentiment=sent,
            reason=reason,
            score_breakdown={
                "basic_ta":    round(basic_score, 3),
                "advanced_ta": round(adv_score, 3),
                "sentiment":   round(sent_score, 3),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────────

    def _sentiment_score(
        self, signal: str, sent: Optional[SentimentSignal]
    ) -> Tuple[float, str]:
        """
        Map sentiment agreement to a numeric contribution (max 0.30).

        Contradicting sentiment subtracts 0.10 to discourage fighting the crowd.
        """
        if not sent:
            return 0.05, "sentiment байхгүй"

        matches = (
            (signal == "BUY" and sent.sentiment == "BULLISH")
            or (signal == "SELL" and sent.sentiment == "BEARISH")
        )
        contradicts = (
            (signal == "BUY" and sent.sentiment == "BEARISH")
            or (signal == "SELL" and sent.sentiment == "BULLISH")
        )
        if matches:
            return self.SENTIMENT_WEIGHT, f"X.com нийцлээ ({sent.sentiment})"
        if contradicts:
            return -0.10, f"X.com зөрчилдлөө ({sent.sentiment})"
        return 0.05, f"X.com тодорхойгүй ({sent.sentiment})"

    def _build_reason(
        self,
        basic: TechnicalSignal,
        adv: AdvancedTAScore,
        sent: Optional[SentimentSignal],
        sent_reason: str,
    ) -> str:
        """Compact human-readable summary of all contributing indicators."""
        parts = [
            f"RSI={basic.rsi:.0f}",
            f"MACD={basic.macd_signal}",
            f"MA={basic.ma_trend}",
            f"SR={adv.sr_zone}",
        ]
        if adv.fib_in_golden:
            parts.append("Fib=GOLD")
        if adv.candle_pattern != "NONE":
            parts.append(f"Candle={adv.candle_pattern}")
        if adv.chart_pattern != "NONE":
            parts.append(f"Chart={adv.chart_pattern}")
        parts.append(sent_reason)
        return " | ".join(parts)
