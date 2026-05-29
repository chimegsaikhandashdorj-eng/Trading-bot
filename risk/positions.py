"""
Thread-safe in-memory registry of open positions.

The trading loop and the Telegram command listener live in different threads,
so direct dict access is racy. This wraps the dict with a single RLock and
exposes the operations the rest of the code actually needs.

Key invariant
-------------
At most ONE open position per `(symbol, exchange)` tuple. Attempts to register
a second position for the same pair are rejected — this is the safety net that
stops the bot from stacking BUYs every hour during a trend.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple


class PositionRegistry:
    """Thread-safe `dict[trade_id -> position]` with a per-symbol uniqueness guard."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._positions: Dict[int, Dict[str, Any]] = {}

    # ── Mutation ───────────────────────────────────────────────────────

    def try_add(self, trade_id: int, position: Dict[str, Any]) -> bool:
        """
        Insert a position. Returns False if `(symbol, exchange)` already has
        an open position — caller MUST handle this rather than overwriting.
        """
        symbol = position.get("symbol")
        exchange = position.get("exchange")
        with self._lock:
            for existing in self._positions.values():
                if existing.get("symbol") == symbol and existing.get("exchange") == exchange:
                    return False
            self._positions[trade_id] = position
            return True

    def remove(self, trade_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._positions.pop(trade_id, None)

    def update_field(self, trade_id: int, field: str, value: Any) -> None:
        with self._lock:
            pos = self._positions.get(trade_id)
            if pos is not None:
                pos[field] = value

    def reset(self) -> None:
        """Used by reconcile after a startup load."""
        with self._lock:
            self._positions.clear()

    # ── Queries ────────────────────────────────────────────────────────

    def has(self, symbol: str, exchange: str) -> bool:
        """Cheap guard for the duplicate-position bug."""
        with self._lock:
            return any(
                p.get("symbol") == symbol and p.get("exchange") == exchange
                for p in self._positions.values()
            )

    def get(self, trade_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            pos = self._positions.get(trade_id)
            return dict(pos) if pos is not None else None   # defensive copy

    def snapshot(self) -> List[Tuple[int, Dict[str, Any]]]:
        """Sorted (trade_id, copy) pairs — safe to iterate outside the lock."""
        with self._lock:
            return [(tid, dict(p)) for tid, p in sorted(self._positions.items())]

    def __len__(self) -> int:
        with self._lock:
            return len(self._positions)

    def __iter__(self) -> Iterator[int]:
        with self._lock:
            return iter(list(self._positions.keys()))
