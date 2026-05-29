"""
Backtest engine — replays a strategy bar-by-bar with SL / TP / signal-flip exits.

Usage
-----
    python backtest.py --symbol BTC/USDT --days 90
    python backtest.py --symbol ETH/USDT --days 30 --sl 2 --tp 4

Outputs
-------
- Per-trade ledger (entry, exit, R-multiple, bars held)
- Aggregate stats: win-rate, profit factor, max drawdown, Sharpe
- Equity curve printed as ASCII sparkline + final summary

The engine walks the dataframe with a rolling lookback window so the strategy
only ever sees data up to (but not including) the current bar — no lookahead.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from typing import List, Optional


import config
from analysis.technical import TechnicalAnalyzer
from exchanges.binance_client import BinanceClient
from utils.logger import get_logger

log = get_logger("Backtest")


@dataclass
class Trade:
    """Single round-trip in the backtest."""
    signal: str
    entry_bar: int
    entry: float
    exit_bar: int
    exit: float
    exit_reason: str          # "sl" | "tp" | "signal_flip" | "eod"
    pnl_pct: float            # entry-relative %
    bars: int

    @property
    def is_winner(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class BacktestResult:
    """Aggregate metrics across an entire backtest run."""
    symbol: str
    days: int
    trades: List[Trade] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def winners(self) -> List[Trade]:
        return [t for t in self.trades if t.is_winner]

    @property
    def losers(self) -> List[Trade]:
        return [t for t in self.trades if not t.is_winner]

    @property
    def win_rate(self) -> float:
        return len(self.winners) / self.n if self.n else 0.0

    @property
    def total_return_pct(self) -> float:
        return sum(t.pnl_pct for t in self.trades)

    @property
    def avg_winner(self) -> float:
        w = self.winners
        return sum(t.pnl_pct for t in w) / len(w) if w else 0.0

    @property
    def avg_loser(self) -> float:
        l = self.losers
        return sum(t.pnl_pct for t in l) / len(l) if l else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pct for t in self.winners)
        gross_loss = abs(sum(t.pnl_pct for t in self.losers))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def max_drawdown_pct(self) -> float:
        equity, peak, max_dd = 0.0, 0.0, 0.0
        for t in self.trades:
            equity += t.pnl_pct
            peak = max(peak, equity)
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def sharpe(self) -> float:
        """Simple per-trade Sharpe (mean / stdev). Not annualized."""
        if self.n < 2:
            return 0.0
        returns = [t.pnl_pct for t in self.trades]
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        sd = math.sqrt(var)
        return mean / sd if sd > 0 else 0.0


def _ascii_equity_curve(trades: List[Trade], width: int = 40) -> str:
    """Tiny sparkline so the user has a visual feel for the run."""
    if not trades:
        return ""
    cum = []
    equity = 0.0
    for t in trades:
        equity += t.pnl_pct
        cum.append(equity)
    lo, hi = min(cum), max(cum)
    if hi == lo:
        return "▁" * min(len(cum), width)
    ramp = "▁▂▃▄▅▆▇█"
    step = max(1, len(cum) // width)
    sampled = cum[::step][:width]
    chars = []
    for v in sampled:
        idx = int((v - lo) / (hi - lo) * (len(ramp) - 1))
        chars.append(ramp[idx])
    return "".join(chars)


def run_backtest(
    symbol: str,
    days: int = 30,
    sl_pct: float = 2.0,
    tp_pct: float = 4.0,
    lookback: int = 200,
    timeframe: str = "1h",
) -> Optional[BacktestResult]:
    """
    Bar-by-bar backtest. Each trade exits on whichever happens first:
    stop-loss, take-profit, or an opposing strategy signal.
    """
    client = BinanceClient()
    analyzer = TechnicalAnalyzer()

    bars_needed = days * 24   # 1h candles
    df = client.get_ohlcv(symbol, timeframe, min(bars_needed, 1000))
    if df is None or len(df) < lookback:
        log.error(f"Дата хүрэлцэхгүй: {symbol}")
        return None

    result = BacktestResult(symbol=symbol, days=days)
    open_trade: Optional[Trade] = None

    for i in range(lookback, len(df) - 1):
        # The strategy only sees bars [0, i). Entry/exit happen on bar i.
        window = df.iloc[:i].copy()
        signal = analyzer.analyze(window, symbol, timeframe)
        bar = df.iloc[i]
        bar_open = float(bar["open"])
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        # ── Manage open trade first ───────────────────────────────────────
        if open_trade is not None:
            # Pass bar_open so gap fills are priced realistically (not at SL price)
            sl_hit, tp_hit, exit_price, reason = _check_exit(
                open_trade, bar_open, bar_high, bar_low, sl_pct, tp_pct
            )
            if sl_hit or tp_hit:
                _finalize(open_trade, i, exit_price, reason)
                result.trades.append(open_trade)
                open_trade = None
                continue   # don't enter on the same bar

            # Signal flip exit
            if signal and signal.signal in ("BUY", "SELL") and signal.signal != open_trade.signal:
                _finalize(open_trade, i, bar_open, "signal_flip")
                result.trades.append(open_trade)
                open_trade = None
                # fall through — open a new trade this bar

        # ── Enter on fresh signal ─────────────────────────────────────────
        if open_trade is None and signal and signal.signal in ("BUY", "SELL") and signal.strength >= 0.5:
            open_trade = Trade(
                signal=signal.signal,
                entry_bar=i,
                entry=bar_open,
                exit_bar=i,
                exit=bar_open,
                exit_reason="open",
                pnl_pct=0.0,
                bars=0,
            )

    # End-of-data: close any open trade at the last close
    if open_trade is not None:
        last = df.iloc[-1]
        _finalize(open_trade, len(df) - 1, float(last["close"]), "eod")
        result.trades.append(open_trade)

    _print_report(result, sl_pct, tp_pct)
    return result


def _check_exit(
    trade: Trade,
    bar_open: float,
    high: float,
    low: float,
    sl_pct: float,
    tp_pct: float,
):
    """
    Determine whether the bar's range crossed SL or TP.

    Realism guarantees
    ------------------
    * Pessimistic when both SL and TP are inside one bar — SL wins.
    * **Gap fills** are priced at `bar_open`, not at the trigger price.
      Backtests that ignore this consistently over-estimate Sharpe
      because gap-down fills on BUY positions hurt more than `sl_price`.
    """
    sl_frac = sl_pct / 100
    tp_frac = tp_pct / 100
    if trade.signal == "BUY":
        sl_price = trade.entry * (1 - sl_frac)
        tp_price = trade.entry * (1 + tp_frac)
        # GAP DOWN: open already below SL → fill at open (worse than sl_price)
        if bar_open <= sl_price:
            return True, False, bar_open, "sl_gap"
        # GAP UP: open already above TP → fill at open (better than tp_price)
        if bar_open >= tp_price:
            return False, True, bar_open, "tp_gap"
        sl_hit = low <= sl_price
        tp_hit = high >= tp_price
        if sl_hit:
            return True, False, sl_price, "sl"
        if tp_hit:
            return False, True, tp_price, "tp"
    else:  # SELL
        sl_price = trade.entry * (1 + sl_frac)
        tp_price = trade.entry * (1 - tp_frac)
        # GAP UP: open already above SL → fill at open (worse)
        if bar_open >= sl_price:
            return True, False, bar_open, "sl_gap"
        # GAP DOWN: open already below TP → fill at open (better)
        if bar_open <= tp_price:
            return False, True, bar_open, "tp_gap"
        sl_hit = high >= sl_price
        tp_hit = low <= tp_price
        if sl_hit:
            return True, False, sl_price, "sl"
        if tp_hit:
            return False, True, tp_price, "tp"
    return False, False, 0.0, ""


def _finalize(trade: Trade, exit_bar: int, exit_price: float, reason: str) -> None:
    trade.exit_bar = exit_bar
    trade.exit = exit_price
    trade.exit_reason = reason
    trade.bars = exit_bar - trade.entry_bar
    raw = (exit_price - trade.entry) if trade.signal == "BUY" else (trade.entry - exit_price)
    trade.pnl_pct = raw / trade.entry * 100


def _print_report(r: BacktestResult, sl_pct: float, tp_pct: float) -> None:
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {r.symbol}  ({r.days} days, SL={sl_pct}% TP={tp_pct}%)")
    print(f"{'='*60}")
    if not r.n:
        print("  Арилжаа олдсонгүй")
        return
    print(f"  Нийт арилжаа:      {r.n}")
    print(f"  Win rate:          {r.win_rate:.1%}  ({len(r.winners)}W / {len(r.losers)}L)")
    print(f"  Нийт өгөөж:        {r.total_return_pct:+.2f}%")
    print(f"  Profit factor:     {r.profit_factor:.2f}")
    print(f"  Max drawdown:      {r.max_drawdown_pct:.2f}%")
    print(f"  Sharpe (per-trade):{r.sharpe:.2f}")
    print(f"  Avg winner:        {r.avg_winner:+.2f}%")
    print(f"  Avg loser:         {r.avg_loser:+.2f}%")
    exits = {}
    for t in r.trades:
        exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
    print(f"  Exit breakdown:    {dict(exits)}")
    print(f"  Equity curve:      {_ascii_equity_curve(r.trades)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading Bot Backtest")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--sl", type=float, default=config.CRYPTO_SL_PCT)
    parser.add_argument("--tp", type=float, default=config.CRYPTO_TP_PCT)
    parser.add_argument("--timeframe", default="1h")
    args = parser.parse_args()
    run_backtest(args.symbol, args.days, args.sl, args.tp, timeframe=args.timeframe)
