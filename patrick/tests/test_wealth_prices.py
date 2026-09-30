"""Price provider of the patrimoine pages (`wealth/prices.py`): the P&L
follows the last close -- yfinance through a short cache, never a stale
data-lake snapshot or a week-old cached answer, never a cached empty
answer, the lake only as the offline fallback."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.wealth import prices


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    return tmp_path


class _Store:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    def exists(self, key):
        return key in self.frames

    def load(self, key):
        return self.frames[key]


def _yf(calls: list, answers: dict):
    def download(symbol, start, auto_adjust, progress):
        calls.append((symbol, auto_adjust))
        close = answers.get(symbol, pd.Series(dtype=float))
        return pd.DataFrame({"Close": close})
    return download


DAYS = pd.bdate_range("2026-09-21", periods=8)
FRESH = pd.Series(range(20, 28), index=DAYS, dtype=float)
STALE_LAKE = {"raw_ALDAT.PA": pd.DataFrame({"ALDAT.PA": [10.0, 11.0]}, index=DAYS[:2])}


def test_fresh_quote_wins_over_a_stale_lake_snapshot(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(prices.yf, "download", _yf(calls, {"ALDAT.PA": FRESH}))
    get = prices.make_provider(store=_Store(STALE_LAKE))
    assert get("ALDAT.PA").iloc[-1] == 27.0
    assert calls == [("ALDAT.PA", False)]  # raw closes: dividends are ledger income


def test_quote_is_cached_briefly_and_empty_answers_never(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(prices.yf, "download", _yf(calls, {"ALDAT.PA": FRESH}))
    prices.fetch_latest("ALDAT.PA")
    prices.fetch_latest("ALDAT.PA")
    assert calls == [("ALDAT.PA", False)]
    assert prices.fetch_latest("ALDAT.PA", max_age_days=0) is not None and len(calls) == 2

    assert prices.fetch_latest("NOT.LISTED") is None
    assert prices.fetch_latest("NOT.LISTED") is None
    assert [c for c in calls if c[0] == "NOT.LISTED"] == [("NOT.LISTED", False)] * 2


def test_lake_is_the_offline_fallback(isolated, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("offline")

    monkeypatch.setattr(prices.yf, "download", boom)
    get = prices.make_provider(store=_Store(STALE_LAKE))
    assert get("ALDAT.PA").iloc[-1] == 11.0
    assert prices.make_provider(store=_Store({}), allow_network=False)("ALDAT.PA") is None
    assert get("DAT:2026-01-01:0.03") is None
