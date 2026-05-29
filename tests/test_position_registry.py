"""PositionRegistry — thread-safety + uniqueness invariant."""
from __future__ import annotations

import threading

from risk.positions import PositionRegistry


def _pos(symbol="BTC/USDT", exchange="binance", side="buy", entry=50000.0):
    return {"symbol": symbol, "exchange": exchange, "side": side, "entry": entry}


def test_try_add_inserts_first():
    r = PositionRegistry()
    assert r.try_add(1, _pos()) is True
    assert len(r) == 1


def test_try_add_rejects_duplicate_symbol_exchange():
    """Core invariant — second BUY on same pair must be refused."""
    r = PositionRegistry()
    assert r.try_add(1, _pos()) is True
    assert r.try_add(2, _pos()) is False
    assert len(r) == 1


def test_different_exchanges_same_symbol_allowed():
    """Same symbol on different venues = different positions."""
    r = PositionRegistry()
    r.try_add(1, _pos(exchange="binance"))
    r.try_add(2, _pos(exchange="mt5", symbol="BTC/USDT"))
    assert len(r) == 2


def test_different_symbols_same_exchange_allowed():
    r = PositionRegistry()
    r.try_add(1, _pos(symbol="BTC/USDT"))
    r.try_add(2, _pos(symbol="ETH/USDT"))
    assert len(r) == 2


def test_has_returns_correct_boolean():
    r = PositionRegistry()
    assert not r.has("BTC/USDT", "binance")
    r.try_add(1, _pos())
    assert r.has("BTC/USDT", "binance")
    assert not r.has("BTC/USDT", "mt5")


def test_remove_returns_position():
    r = PositionRegistry()
    r.try_add(1, _pos())
    removed = r.remove(1)
    assert removed is not None
    assert removed["symbol"] == "BTC/USDT"
    assert len(r) == 0
    # Remove allows re-adding the same symbol later
    assert r.try_add(2, _pos()) is True


def test_remove_missing_returns_none():
    r = PositionRegistry()
    assert r.remove(999) is None


def test_update_field_changes_position():
    r = PositionRegistry()
    r.try_add(1, _pos())
    r.update_field(1, "breakeven_moved", True)
    snap = r.get(1)
    assert snap is not None
    assert snap["breakeven_moved"] is True


def test_snapshot_returns_defensive_copies():
    """Mutating snapshot result must not affect registry state."""
    r = PositionRegistry()
    r.try_add(1, _pos())
    snap = r.snapshot()
    snap[0][1]["entry"] = 0
    assert r.get(1)["entry"] == 50000.0


def test_concurrent_try_add_only_one_succeeds():
    """50 threads racing to add the same (symbol, exchange) → 1 winner."""
    r = PositionRegistry()
    results = []

    def add(tid: int) -> None:
        results.append(r.try_add(tid, _pos()))

    threads = [threading.Thread(target=add, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert len(r) == 1


def test_concurrent_iter_during_mutation_safe():
    """`snapshot` while another thread is removing must not raise."""
    r = PositionRegistry()
    for i in range(20):
        r.try_add(i, _pos(symbol=f"COIN{i}/USDT"))

    errors = []

    def reader():
        try:
            for _ in range(100):
                snap = r.snapshot()
                _ = [p["symbol"] for _, p in snap]
        except Exception as exc:
            errors.append(exc)

    def writer():
        try:
            for i in range(20):
                r.remove(i)
        except Exception as exc:
            errors.append(exc)

    rt = threading.Thread(target=reader)
    wt = threading.Thread(target=writer)
    rt.start()
    wt.start()
    rt.join()
    wt.join()
    assert errors == []


def test_reset_clears_all():
    r = PositionRegistry()
    for i in range(5):
        r.try_add(i, _pos(symbol=f"X{i}"))
    r.reset()
    assert len(r) == 0
