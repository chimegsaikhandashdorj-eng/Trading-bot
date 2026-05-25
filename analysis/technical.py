"""
Үндсэн техникийн шинжилгээний модуль.

Үзүүлэлтүүд: RSI, MACD (Golden/Death Cross), EMA 20/50/200, Bollinger Bands.
Цахим шинжилгээний `technical_analyzer` багцаас тусдаа, гүн уламжлалт техникийн оноог гаргана.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

import config
from utils.logger import get_logger

log = get_logger("Technical")


@dataclass
class TechnicalSignal:
    """
    Үндсэн техникийн шинжилгээний үр дүн.

    Attributes
    ----------
    symbol : str
        Хосын нэр (жнь "BTC/USDT")
    timeframe : str
        Шинжилгээ хийсэн хугацаа (жнь "1h")
    signal : str
        "BUY" | "SELL" | "NEUTRAL"
    strength : float
        Сигналын хүч 0.0-1.0
    rsi : float
        RSI утга
    macd_signal : str
        "BUY" | "SELL" | "NEUTRAL"
    ma_trend : str
        "UP" | "DOWN" | "SIDEWAYS"
    bb_position : str
        "UPPER" | "LOWER" | "MIDDLE"
    current_price : float
        Хамгийн сүүлийн хаалтын үнэ
    details : dict
        Нэмэлт мэдээлэл (EMA, BB, оноо)
    """
    symbol: str
    timeframe: str
    signal: str
    strength: float
    rsi: float
    macd_signal: str
    ma_trend: str
    bb_position: str
    current_price: float
    details: Dict[str, Any] = field(default_factory=dict)


def _safe_get(row: pd.Series, key: str, default: Any = None) -> Any:
    """Свечний row-аас утга авах: NaN бол default буцаана."""
    try:
        val = row.get(key, default)
    except Exception:
        return default
    if val is None:
        return default
    try:
        if isinstance(val, float) and math.isnan(val):
            return default
    except Exception:
        pass
    return val


class TechnicalAnalyzer:
    """
    RSI + MACD + EMA + Bollinger Bands-д суурилсан үндсэн TA шинжилгээ.

    Хэрэглэх жишээ
    --------------
    >>> ta = TechnicalAnalyzer()
    >>> signal = ta.analyze(df, "BTC/USDT", "1h")
    >>> if signal and signal.signal == "BUY":
    ...     print(f"Strength: {signal.strength}")
    """

    MIN_BARS_REQUIRED: int = 50

    def analyze(
        self, df: pd.DataFrame, symbol: str, timeframe: str
    ) -> Optional[TechnicalSignal]:
        """
        Үндсэн TA сигнал гаргах.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV дата (хамгийн багадаа 50 свеч)
        symbol : str
            Хосын нэр
        timeframe : str
            Шинжилгээний хугацааны нэр

        Returns
        -------
        Optional[TechnicalSignal]
            Сигнал боловсорсон бол үр дүн, эс бөгөөс None
        """
        if df is None or len(df) < self.MIN_BARS_REQUIRED:
            log.warning(
                f"{symbol} дата хүрэлцэхгүй "
                f"({0 if df is None else len(df)} < {self.MIN_BARS_REQUIRED})"
            )
            return None

        try:
            df = df.copy()
            df.ta.rsi(length=config.RSI_PERIOD, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.ema(length=20, append=True)
            df.ta.ema(length=50, append=True)
            df.ta.ema(length=200, append=True)
            df.ta.bbands(length=20, std=2, append=True)

            # IndexError-оос хамгаалах
            if len(df) < 2:
                log.warning(f"{symbol} индикатор тооцсоны дараа дата хүрэлцэхгүй")
                return None

            last = df.iloc[-1]
            prev = df.iloc[-2]

            # ── RSI ────────────────────────────────────────────────────────
            rsi_col = f"RSI_{config.RSI_PERIOD}"
            rsi = float(_safe_get(last, rsi_col, 50.0))

            if rsi < config.RSI_OVERSOLD:
                rsi_signal = "BUY"
                rsi_score = (config.RSI_OVERSOLD - rsi) / max(config.RSI_OVERSOLD, 1)
            elif rsi > config.RSI_OVERBOUGHT:
                rsi_signal = "SELL"
                denom = max(100 - config.RSI_OVERBOUGHT, 1)
                rsi_score = (rsi - config.RSI_OVERBOUGHT) / denom
            else:
                rsi_signal = "NEUTRAL"
                rsi_score = 0.0

            # ── MACD ───────────────────────────────────────────────────────
            # Golden Cross (BUY): MACD доороос дээш огтлох
            # Death Cross (SELL): MACD дээрээс доош огтлох
            macd_col, sig_col, hist_col = "MACD_12_26_9", "MACDs_12_26_9", "MACDh_12_26_9"
            macd_now = float(_safe_get(last, macd_col, 0.0))
            macd_prev = float(_safe_get(prev, macd_col, 0.0))
            sig_now = float(_safe_get(last, sig_col, 0.0))
            sig_prev = float(_safe_get(prev, sig_col, 0.0))

            if macd_now > sig_now and macd_prev <= sig_prev:
                macd_signal = "BUY"          # Golden Cross
            elif macd_now < sig_now and macd_prev >= sig_prev:
                macd_signal = "SELL"         # Death Cross
            else:
                hist = float(_safe_get(last, hist_col, 0.0))
                macd_signal = "BUY" if hist > 0 else "SELL" if hist < 0 else "NEUTRAL"

            # ── EMA Trend ──────────────────────────────────────────────────
            ema20 = _safe_get(last, "EMA_20")
            ema50 = _safe_get(last, "EMA_50")
            ema200 = _safe_get(last, "EMA_200")

            if ema20 and ema50 and ema200:
                if ema20 > ema50 > ema200:
                    ma_trend = "UP"
                elif ema20 < ema50 < ema200:
                    ma_trend = "DOWN"
                else:
                    ma_trend = "SIDEWAYS"
            else:
                ma_trend = "SIDEWAYS"

            # ── Bollinger Bands ────────────────────────────────────────────
            bb_upper = _safe_get(last, "BBU_20_2.0")
            bb_lower = _safe_get(last, "BBL_20_2.0")
            bb_mid = _safe_get(last, "BBM_20_2.0")
            price = float(_safe_get(last, "close", 0.0))

            if bb_upper and bb_lower and bb_mid and price > 0:
                if price > bb_upper:
                    bb_pos = "UPPER"
                elif price < bb_lower:
                    bb_pos = "LOWER"
                else:
                    bb_pos = "MIDDLE"
            else:
                bb_pos = "MIDDLE"

            # ── Combined scoring ───────────────────────────────────────────
            buy_score = 0.0
            sell_score = 0.0

            if rsi_signal == "BUY":
                buy_score += 0.3 + rsi_score * 0.1
            elif rsi_signal == "SELL":
                sell_score += 0.3 + rsi_score * 0.1

            if macd_signal == "BUY":
                buy_score += 0.3
            elif macd_signal == "SELL":
                sell_score += 0.3

            if ma_trend == "UP":
                buy_score += 0.2
            elif ma_trend == "DOWN":
                sell_score += 0.2

            if bb_pos == "LOWER":
                buy_score += 0.2
            elif bb_pos == "UPPER":
                sell_score += 0.2

            if buy_score > sell_score and buy_score >= 0.5:
                signal = "BUY"
                strength = min(buy_score, 1.0)
            elif sell_score > buy_score and sell_score >= 0.5:
                signal = "SELL"
                strength = min(sell_score, 1.0)
            else:
                signal = "NEUTRAL"
                strength = 0.0

            log.info(
                f"{symbol} [{timeframe}] -> {signal} (strength={strength:.2f}) | "
                f"RSI={rsi:.1f} MACD={macd_signal} MA={ma_trend} BB={bb_pos}"
            )

            return TechnicalSignal(
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                strength=strength,
                rsi=rsi,
                macd_signal=macd_signal,
                ma_trend=ma_trend,
                bb_position=bb_pos,
                current_price=price,
                details={
                    "ema20": ema20, "ema50": ema50, "ema200": ema200,
                    "bb_upper": bb_upper, "bb_lower": bb_lower,
                    "buy_score": buy_score, "sell_score": sell_score,
                },
            )
        except IndexError as e:
            log.error(f"{symbol} IndexError техникийн шинжилгээнд: {e}")
            return None
        except Exception as e:
            log.error(f"{symbol} техникийн шинжилгээ алдаа: {e}")
            return None
