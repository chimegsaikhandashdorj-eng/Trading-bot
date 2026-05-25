"""
SQLite persistence for trade records and daily P&L aggregation.

The bot is single-process so a plain `sqlite3` connection per call is
adequate. `daily_stats` is updated atomically via ON CONFLICT so two
concurrent close-events cannot lose updates.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

log = get_logger("Database")

DB_PATH: str = "data/trades.db"


def _conn() -> sqlite3.Connection:
    """Return a SQLite connection with row factory + ensured parent dir."""
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if missing. Safe to call repeatedly."""
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT    NOT NULL,
                side        TEXT    NOT NULL,
                entry_price REAL    NOT NULL,
                volume      REAL    NOT NULL,
                pnl         REAL    DEFAULT 0,
                status      TEXT    DEFAULT 'open',
                exchange    TEXT    NOT NULL,
                ticket      TEXT,
                opened_at   TEXT    NOT NULL,
                closed_at   TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date        TEXT    PRIMARY KEY,
                total_pnl   REAL    DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                win_count   INTEGER DEFAULT 0
            )
        """)
        conn.commit()
    log.info("SQLite database бэлэн: %s", DB_PATH)


def open_trade(
    symbol: str,
    side: str,
    price: float,
    volume: float,
    exchange: str,
    ticket: Optional[str] = None,
) -> int:
    """
    Insert a new open trade and return its DB id.

    Caller is expected to retain the id and pass it back to `close_trade`
    when the broker closes the position (SL/TP hit or manual close).
    """
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (symbol, side, entry_price, volume, exchange, ticket, opened_at)
               VALUES (?,?,?,?,?,?,?)""",
            (symbol, side, price, volume, exchange, ticket,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid or 0


def close_trade(trade_id: int, pnl: float) -> None:
    """
    Mark a trade closed and atomically roll its P&L into today's daily_stats.

    The ON CONFLICT clause guarantees two near-simultaneous closes can't
    overwrite each other's totals.
    """
    today = date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            "UPDATE trades SET pnl=?, status='closed', closed_at=? WHERE id=?",
            (pnl, datetime.now(timezone.utc).isoformat(), trade_id),
        )
        conn.execute(
            """
            INSERT INTO daily_stats (date, total_pnl, trade_count, win_count)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_pnl   = total_pnl   + excluded.total_pnl,
                trade_count = trade_count + 1,
                win_count   = win_count   + excluded.win_count
            """,
            (today, pnl, 1 if pnl > 0 else 0),
        )
        conn.commit()


def get_daily_loss(target_date: Optional[str] = None) -> float:
    """
    Today's net loss as a positive number. Returns 0 if the day was net-positive.

    Used by `RiskManager` to enforce the daily-loss circuit breaker, so the
    answer must survive process restarts (hence DB-backed, not in-memory).
    """
    d = target_date or date.today().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT total_pnl FROM daily_stats WHERE date=?", (d,)
        ).fetchone()
    if not row:
        return 0.0
    return abs(min(float(row["total_pnl"]), 0.0))


def get_daily_stats(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Full row for the requested date (defaults to today). Empty default if missing."""
    d = target_date or date.today().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE date=?", (d,)
        ).fetchone()
    if not row:
        return {"date": d, "total_pnl": 0.0, "trade_count": 0, "win_count": 0}
    return dict(row)
