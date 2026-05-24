from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from analysis.technical import TechnicalAnalyzer, TechnicalSignal
from analysis.technical_analyzer import generate_ta_score, AdvancedTAScore
from analysis.sentiment import SentimentAnalyzer, SentimentSignal
from utils.logger import get_logger

log = get_logger("Strategy")

#
# Оноог хуваарилах жин
#   RSI / MACD / EMA / BB  →  40%
#   S/R + Fib + Candle      →  30%
#   X.com Sentiment         →  30%
#


@dataclass
class CombinedSignal:
    symbol: str
    final_signal: str       # "BUY" | "SELL" | "NEUTRAL"
    confidence: float       # 0.0 – 1.0
    technical: TechnicalSignal
    advanced_ta: AdvancedTAScore
    sentiment: Optional[SentimentSignal]
    reason: str
    score_breakdown: dict = field(default_factory=dict)


class CombinedStrategy:
    def __init__(self):
        self.basic_ta  = TechnicalAnalyzer()
        self.sentiment = SentimentAnalyzer()

    def evaluate(
        self,
        df_primary:  pd.DataFrame,
        df_confirm:  Optional[pd.DataFrame],
        symbol:      str,
        tf_primary:  str = "1h",
        tf_confirm:  str = "4h",
    ) -> Optional[CombinedSignal]:

        # ── 1. RSI / MACD / EMA / BB (40%) ─────────────────────────────
        basic = self.basic_ta.analyze(df_primary, symbol, tf_primary)
        if not basic or basic.signal == "NEUTRAL":
            return None

        # Timeframe баталгаажуулалт
        basic_4h = self.basic_ta.analyze(df_confirm, symbol, tf_confirm) if df_confirm is not None else None
        if basic_4h and basic_4h.signal not in (basic.signal, "NEUTRAL"):
            log.info(f"{symbol}: {tf_primary}/{tf_confirm} timeframe зөрчилдлөө — skip")
            return None

        basic_score = basic.strength * 0.40

        # ── 2. Advanced TA: S/R + Fib + Candle + Chart (30%) ───────────
        adv = generate_ta_score(df_primary, df_confirm, basic.signal)

        # Advanced TA нь basic-ийн сигналтай зөрчилдвөл буцна
        if adv.signal not in (basic.signal, "NEUTRAL"):
            log.info(
                f"{symbol}: Advanced TA ({adv.signal}) ↔ Basic TA ({basic.signal}) "
                f"зөрчилдлөө — skip"
            )
            return None

        adv_score = adv.score * 0.30

        # ── 3. Sentiment (30%) ─────────────────────────────────────────
        sent = self.sentiment.analyze(symbol)
        sent_score, sent_reason = self._sentiment_score(basic.signal, sent)

        # ── 4. Нэгдсэн confidence ──────────────────────────────────────
        confidence = round(
            min(basic_score + adv_score + sent_score, 1.0), 3
        )

        reason = self._build_reason(basic, adv, sent, sent_reason)

        if confidence < 0.55:
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
                "advanced_ta": round(adv_score,   3),
                "sentiment":   round(sent_score,  3),
            },
        )

    # ── Туслах функцүүд ────────────────────────────────────────────────────

    def _sentiment_score(self, signal: str, sent: Optional[SentimentSignal]) -> tuple:
        if not sent:
            return 0.05, "sentiment байхгүй"

        matches     = (signal == "BUY"  and sent.sentiment == "BULLISH") or \
                      (signal == "SELL" and sent.sentiment == "BEARISH")
        contradicts = (signal == "BUY"  and sent.sentiment == "BEARISH") or \
                      (signal == "SELL" and sent.sentiment == "BULLISH")

        if matches:
            return 0.30, f"X.com нийцлээ ({sent.sentiment})"
        if contradicts:
            return -0.10, f"X.com зөрчилдлөө ({sent.sentiment})"
        return 0.05, f"X.com тодорхойгүй ({sent.sentiment})"

    def _build_reason(self, basic: TechnicalSignal, adv: AdvancedTAScore,
                      sent: Optional[SentimentSignal], sent_reason: str) -> str:
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
