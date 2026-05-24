import ccxt
import pandas as pd
from typing import Any, Dict, List, Optional
import config
from utils.logger import get_logger

log = get_logger("Binance")

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}


class BinanceClient:
    def __init__(self):
        self.exchange = ccxt.binance({
            "apiKey": config.BINANCE_API_KEY,
            "secret": config.BINANCE_SECRET_KEY,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        if config.BINANCE_TESTNET:
            self.exchange.set_sandbox_mode(True)
        log.info("Binance клиент холбогдлоо")

    def get_balance(self, currency: str = "USDT") -> float:
        try:
            balance: Any = self.exchange.fetch_balance()
            return float(balance["free"].get(currency, 0.0))
        except Exception as e:
            log.error(f"Баланс авах алдаа: {e}")
            return 0.0

    def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> Optional[pd.DataFrame]:
        try:
            data = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            log.error(f"OHLCV авах алдаа ({symbol}): {e}")
            return None

    def _min_amount(self, symbol: str) -> float:
        """Binance market нь хосын minimum amount-ийг буцаана."""
        try:
            market = self.exchange.market(symbol)
            return float(market.get("limits", {}).get("amount", {}).get("min", 0.0001))
        except Exception:
            return 0.0001

    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            return dict(self.exchange.fetch_ticker(symbol))
        except Exception as e:
            log.error(f"Ticker авах алдаа ({symbol}): {e}")
            return None

    def place_order(self, symbol: str, side: str, amount: float,
                    order_type: str = "market", price: Optional[float] = None) -> Optional[Dict[str, Any]]:
        try:
            side_literal = "buy" if side.lower() == "buy" else "sell"
            # Minimum amount шалгах — Binance reject хийхээс сэргийлнэ
            min_amt = self._min_amount(symbol)
            if amount < min_amt:
                log.warning(f"{symbol} amount ({amount}) < min ({min_amt}) — алгасав")
                return None

            if order_type == "market":
                order = self.exchange.create_order(symbol, "market", side_literal, amount)
            else:
                order = self.exchange.create_order(symbol, "limit", side_literal, amount, price)
            log.info(f"Захиалга өгөгдлөө: {side} {amount} {symbol} @ {price or 'market'}")
            return order
        except Exception as e:
            log.error(f"Захиалга өгөх алдаа ({symbol} {side} {amount}): {e}")
            return None

    def place_stop_loss(self, symbol: str, side: str, amount: float,
                        stop_price: float) -> Optional[Dict[str, Any]]:
        """Position-ын эсрэг тал руу stop-market захиалга байршуулна."""
        try:
            opposite = "sell" if side.lower() == "buy" else "buy"
            order = self.exchange.create_order(
                symbol, "STOP_LOSS_LIMIT", opposite, amount, stop_price,
                {"stopPrice": stop_price, "timeInForce": "GTC"}
            )
            log.info(f"SL захиалга: {symbol} {opposite} {amount} @ {stop_price}")
            return order
        except Exception as e:
            log.error(f"SL захиалга алдаа ({symbol}): {e}")
            return None

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            self.exchange.cancel_order(order_id, symbol)
            log.info(f"Захиалга цуцлагдлаа: {order_id}")
            return True
        except Exception as e:
            log.error(f"Цуцлах алдаа: {e}")
            return False

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            orders: Any = self.exchange.fetch_open_orders(symbol)
            return [dict(o) for o in orders]
        except Exception as e:
            log.error(f"Нээлттэй захиалга авах алдаа: {e}")
            return []
