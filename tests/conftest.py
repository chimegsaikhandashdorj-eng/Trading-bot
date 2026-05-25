"""Shared pytest fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Project root on sys.path so `import config`, `import strategy.*` etc work
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file so they never collide."""
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def trending_up_df() -> pd.DataFrame:
    """200 candles trending upward — should produce a BUY-leaning signal."""
    rng = np.random.default_rng(42)
    n = 200
    base = np.linspace(100, 150, n)
    noise = rng.normal(0, 0.5, n)
    close = base + noise
    high = close + np.abs(rng.normal(0.3, 0.1, n))
    low = close - np.abs(rng.normal(0.3, 0.1, n))
    open_ = np.concatenate(([close[0]], close[:-1]))
    vol = rng.integers(1000, 5000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


@pytest.fixture
def trending_down_df() -> pd.DataFrame:
    """200 candles trending downward."""
    rng = np.random.default_rng(7)
    n = 200
    base = np.linspace(150, 100, n)
    noise = rng.normal(0, 0.5, n)
    close = base + noise
    high = close + np.abs(rng.normal(0.3, 0.1, n))
    low = close - np.abs(rng.normal(0.3, 0.1, n))
    open_ = np.concatenate(([close[0]], close[:-1]))
    vol = rng.integers(1000, 5000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


@pytest.fixture
def flat_df() -> pd.DataFrame:
    """No-trend dataframe — strategy should refuse to trade."""
    n = 200
    close = np.full(n, 100.0) + np.random.default_rng(0).normal(0, 0.05, n)
    high = close + 0.1
    low = close - 0.1
    open_ = close.copy()
    vol = np.full(n, 1000.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )
