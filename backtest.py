"""
Backtest хэрэгсэл — стратегийг түүхэн датаар шалгах
Жишээ: python backtest.py --symbol BTC/USDT --days 90
"""
import argparse
import pandas as pd
from exchanges.binance_client import BinanceClient
from analysis.technical import TechnicalAnalyzer
from utils.logger import get_logger

log = get_logger("Backtest")


def run_backtest(symbol: str, days: int = 30):
    client = BinanceClient()
    analyzer = TechnicalAnalyzer()

    limit = days * 24  # 1h candle
    df = client.get_ohlcv(symbol, "1h", min(limit, 1000))
    if df is None:
        log.error("Дата авч чадсангүй")
        return

    trades = []
    in_trade = None

    in_signal: str = ""
    in_entry: float = 0.0
    in_bar: int = 0

    for i in range(50, len(df)):
        window = pd.DataFrame(df.iloc[:i])
        signal = analyzer.analyze(window, symbol, "1h")
        if not signal:
            continue

        price = float(df.iloc[i]["open"])

        if in_trade is None and signal.signal in ("BUY", "SELL") and signal.strength >= 0.5:
            in_signal = signal.signal
            in_entry = price
            in_bar = i
            in_trade = {"signal": in_signal, "entry": in_entry, "bar": in_bar}

        elif in_trade and signal.signal != in_signal:
            pnl = (price - in_entry) if in_signal == "BUY" else (in_entry - price)
            trades.append({
                "entry": in_entry,
                "exit": price,
                "signal": in_signal,
                "pnl_pct": pnl / in_entry * 100,
                "bars": i - in_bar,
            })
            in_trade = None

    if not trades:
        log.info("Арилжаа олдсонгүй")
        return

    df_trades = pd.DataFrame(trades)
    winners = df_trades[df_trades["pnl_pct"] > 0]
    losers = df_trades[df_trades["pnl_pct"] <= 0]

    print(f"\n{'='*50}")
    print(f"  BACKTEST ҮЛДЭГДЭЛ: {symbol} ({days} хоног)")
    print(f"{'='*50}")
    print(f"  Нийт арилжаа:   {len(df_trades)}")
    print(f"  Ялсан:          {len(winners)} ({len(winners)/len(df_trades)*100:.1f}%)")
    print(f"  Ялагдсан:       {len(losers)}")
    print(f"  Нийт P&L:       {df_trades['pnl_pct'].sum():.2f}%")
    print(f"  Дундаж ашиг:    {winners['pnl_pct'].mean():.2f}%" if len(winners) else "")
    print(f"  Дундаж алдагдал:{losers['pnl_pct'].mean():.2f}%" if len(losers) else "")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading Bot Backtest")
    parser.add_argument("--symbol", default="BTC/USDT", help="Арилжааны хос (жнь: BTC/USDT)")
    parser.add_argument("--days", type=int, default=30, help="Хэдэн хоногийн дата шалгах")
    args = parser.parse_args()
    run_backtest(args.symbol, args.days)
