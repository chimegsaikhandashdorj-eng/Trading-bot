import time
import requests
import tweepy
from dataclasses import dataclass
from typing import Optional
import config
from utils.logger import get_logger

log = get_logger("Sentiment")

# Cache: символ тутамд 30 минут кэш хадгална (rate limit хэмнэх)
_CACHE_TTL = 1800
_cache: dict[str, tuple[float, "SentimentSignal"]] = {}

POSITIVE_WORDS = [
    "bullish", "bull", "buy", "long", "rally", "breakout",
    "support", "bounce", "green", "gains", "higher", "uptrend",
    "surge", "strong", "accumulate", "hodl", "growth", "pump",
]
NEGATIVE_WORDS = [
    "bearish", "bear", "sell", "short", "crash", "dump", "drop",
    "resistance", "breakdown", "correction", "red", "loss", "lower",
    "downtrend", "decline", "weak", "fear", "warning", "panic",
]

# Spam/bot tweet-г илрүүлэх үгс
SPAM_PATTERNS = [
    "airdrop", "giveaway", "free crypto", "dm me", "whatsapp",
    "telegram.me", "t.me/", "join now", "100x", "1000x",
    "guaranteed profit", "signal group",
]

# X.com-д шаардагдах хамгийн бага дагагч тоо
MIN_FOLLOWERS = 1000


@dataclass
class SentimentSignal:
    symbol: str
    sentiment: str      # "BULLISH", "BEARISH", "NEUTRAL"
    score: float        # -1.0 to 1.0
    tweet_count: int
    positive_count: int
    negative_count: int
    confirm_trade: bool
    source: str         # "x.com" | "cryptopanic" | "cache" | "none"


class SentimentAnalyzer:
    def __init__(self):
        self.x_client = None
        self._init_x_client()

    def _init_x_client(self):
        if not config.X_BEARER_TOKEN:
            log.warning("X.com Bearer Token тохируулаагүй. X.com sentiment ажиллахгүй.")
            return
        try:
            self.x_client = tweepy.Client(
                bearer_token=config.X_BEARER_TOKEN,
                consumer_key=config.X_API_KEY,
                consumer_secret=config.X_API_SECRET,
                access_token=config.X_ACCESS_TOKEN,
                access_token_secret=config.X_ACCESS_SECRET,
                wait_on_rate_limit=True,
            )
            log.info("X.com клиент холбогдлоо")
        except Exception as e:
            log.error(f"X.com холболт алдаа: {e}")

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _get_cached(self, symbol: str) -> Optional["SentimentSignal"]:
        if symbol not in _cache:
            return None
        cached_time, signal = _cache[symbol]
        if time.time() - cached_time < _CACHE_TTL:
            log.info(f"{symbol} кэшээс sentiment ашиглав ({int((time.time()-cached_time)/60)} мин өмнөх)")
            return signal
        del _cache[symbol]
        return None

    def _set_cache(self, symbol: str, signal: "SentimentSignal"):
        _cache[symbol] = (time.time(), signal)

    # ── Текст оноо ────────────────────────────────────────────────────────────

    def _score_text(self, text: str) -> float:
        t = text.lower()
        if any(spam in t for spam in SPAM_PATTERNS):
            return 0.0   # spam tweet → 0 оноо
        pos = sum(1 for w in POSITIVE_WORDS if w in t)
        neg = sum(1 for w in NEGATIVE_WORDS if w in t)
        total = pos + neg
        return 0.0 if total == 0 else (pos - neg) / total

    def _score_to_signal(self, score: float) -> str:
        if score > 0.15:
            return "BULLISH"
        if score < -0.15:
            return "BEARISH"
        return "NEUTRAL"

    # ── X.com ─────────────────────────────────────────────────────────────────

    def _analyze_x(self, symbol: str, max_results: int = 30) -> Optional["SentimentSignal"]:
        if not self.x_client:
            return None

        keywords = config.SENTIMENT_KEYWORDS.get(symbol, [symbol])
        # Verified болон олон дагагчтай account-уудын tweet л авах
        query = (
            "(" + " OR ".join(f'"{kw}"' for kw in keywords[:3]) + ")"
            + " lang:en -is:retweet -is:reply"
        )

        try:
            response = self.x_client.search_recent_tweets(
                query=query,
                max_results=min(max_results, 100),
                tweet_fields=["text", "public_metrics"],
                expansions=["author_id"],
                user_fields=["public_metrics", "verified"],
            )
            if not response.data:
                return None

            # Author мэдээлэл хэрэглэгчийн ID-аар харьцуулах
            users = {}
            if response.includes and "users" in response.includes:
                for u in response.includes["users"]:
                    users[u.id] = u

            total_score, pos_count, neg_count, used = 0.0, 0, 0, 0

            for tweet in response.data:
                # Хэрэглэгчийн spam / follower шүүлтүүр
                author = users.get(tweet.author_id) if tweet.author_id else None
                if author:
                    followers = (author.public_metrics or {}).get("followers_count", 0)
                    if followers < MIN_FOLLOWERS:
                        continue  # бага дагагчтай account алгас

                score = self._score_text(tweet.text)
                if score == 0.0:
                    continue  # spam эсвэл тодорхойгүй

                # Like-тай tweet-д илүү жин (max 5x)
                metrics = tweet.public_metrics or {}
                weight = min(1 + metrics.get("like_count", 0) / 200, 5.0)
                total_score += score * weight
                used += 1
                if score > 0:
                    pos_count += 1
                else:
                    neg_count += 1

            if used == 0:
                return None

            avg_score = total_score / used
            sentiment = self._score_to_signal(avg_score)
            log.info(f"{symbol} X.com: {sentiment} ({avg_score:.3f}) | шүүгдсэн tweet={used}")
            return SentimentSignal(
                symbol=symbol, sentiment=sentiment, score=avg_score,
                tweet_count=used, positive_count=pos_count,
                negative_count=neg_count,
                confirm_trade=sentiment != "NEUTRAL",
                source="x.com",
            )
        except tweepy.errors.TooManyRequests:
            log.warning(f"X.com rate limit хүрлээ — CryptoPanic руу шилжинэ")
            return None
        except Exception as e:
            log.error(f"X.com алдаа ({symbol}): {e}")
            return None

    # ── CryptoPanic (Crypto fallback) ─────────────────────────────────────────

    def _analyze_cryptopanic(self, symbol: str) -> Optional["SentimentSignal"]:
        """CryptoPanic API — crypto мэдээний sentiment (үнэгүй tier байдаг)."""
        api_key = getattr(config, "CRYPTOPANIC_API_KEY", "")
        if not api_key:
            return None

        # Symbol-г CryptoPanic-ийн формат руу хөрвүүлэх
        cp_symbol = symbol.replace("/USDT", "").replace("XAUUSD", "XAU")
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&currencies={cp_symbol}&filter=hot"

        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json().get("results", [])
            if not data:
                return None

            total_score, pos_count, neg_count = 0.0, 0, 0
            for item in data[:20]:
                votes = item.get("votes", {})
                # CryptoPanic-т эерэг/сөрөг санал шууд байдаг
                pos = votes.get("positive", 0)
                neg = votes.get("negative", 0)
                total = pos + neg
                if total == 0:
                    score = self._score_text(item.get("title", ""))
                else:
                    score = (pos - neg) / total
                total_score += score
                if score > 0:
                    pos_count += 1
                elif score < 0:
                    neg_count += 1

            avg_score = total_score / len(data[:20])
            sentiment = self._score_to_signal(avg_score)
            log.info(f"{symbol} CryptoPanic: {sentiment} ({avg_score:.3f})")
            return SentimentSignal(
                symbol=symbol, sentiment=sentiment, score=avg_score,
                tweet_count=len(data[:20]), positive_count=pos_count,
                negative_count=neg_count,
                confirm_trade=sentiment != "NEUTRAL",
                source="cryptopanic",
            )
        except Exception as e:
            log.error(f"CryptoPanic алдаа ({symbol}): {e}")
            return None

    # ── Гол функц ─────────────────────────────────────────────────────────────

    def analyze(self, symbol: str) -> SentimentSignal:
        # 1. Кэш шалгах
        cached = self._get_cached(symbol)
        if cached:
            return cached

        # 2. X.com оролдох
        result = self._analyze_x(symbol)

        # 3. X.com амжилтгүй бол CryptoPanic fallback
        if result is None:
            result = self._analyze_cryptopanic(symbol)

        # 4. Бүгд амжилтгүй бол neutral
        if result is None:
            result = self._neutral_signal(symbol)

        self._set_cache(symbol, result)
        return result

    def _neutral_signal(self, symbol: str) -> SentimentSignal:
        return SentimentSignal(
            symbol=symbol, sentiment="NEUTRAL", score=0.0,
            tweet_count=0, positive_count=0, negative_count=0,
            confirm_trade=False, source="none",
        )
