"""M1: symbols confirmed unavailable at the data source (delisted/invalid --
see migration 0013) must be excluded from the webapp's startup market-mover
refresh once, not retried silently on every subsequent refresh/restart.
"""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.tracking import db as trackdb
from patrick.webapp import alerts


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    with alerts._lock:
        alerts._cache.update({"gainers": [], "losers": [], "updated_at": None, "error": None})


def test_migration_seeds_the_nine_confirmed_unavailable_symbols():
    conn = trackdb.connect()
    try:
        excluded = {row["symbol"] for row in trackdb.list_excluded_symbols(conn)}
    finally:
        conn.close()
    assert excluded == {"LBS=F", "HYLD", "TBP", "GXG", "LVRK", "TERM", "^EVZ", "CYB", "BZF"}


def test_active_tickers_excludes_seeded_symbols_but_keeps_the_rest():
    active = alerts._active_tickers()
    assert "LBS=F" not in active
    assert "^EVZ" not in active
    # the rest of the ~300-ticker default universe is untouched
    assert len(active) == len(D.DEFAULT_UNIVERSE_YF_TICKERS) - 9
    assert set(D.DEFAULT_UNIVERSE_YF_TICKERS) - set(active) == {
        "LBS=F", "HYLD", "TBP", "GXG", "LVRK", "TERM", "^EVZ", "CYB", "BZF",
    }


def test_compute_once_never_passes_an_excluded_symbol_to_download_batch_across_restarts(monkeypatch):
    """Simulates two separate startups (two independent `_compute_once()`
    calls, each re-reading the exclusion list fresh from the DB, exactly as
    a real process restart would) -- an excluded symbol must not appear in
    either call's download list, and no code path re-adds it in between."""
    seen_ticker_lists = []

    def _fake_download_batch(tickers, start):
        seen_ticker_lists.append(list(tickers))
        return pd.DataFrame()  # empty -> _compute_once records an error and returns, which is fine here

    monkeypatch.setattr(alerts, "download_batch", _fake_download_batch)

    alerts._compute_once()
    alerts._compute_once()

    assert len(seen_ticker_lists) == 2
    for tickers in seen_ticker_lists:
        assert "LBS=F" not in tickers
        assert "^EVZ" not in tickers
        assert "HYLD" not in tickers


class _StopLoop(Exception):
    """Sentinel to unwind out of `_loop()`'s `while True` deterministically
    -- no real thread, no wall-clock race, nothing left running once the
    test function returns (a real background thread driving `_loop()`
    would keep calling the REAL `download_batch` against Yahoo Finance
    forever after `monkeypatch` undoes its patches at test teardown, since
    `_loop()` never stops on its own -- confirmed the hard way: an earlier
    version of this test did exactly that and hung the whole suite
    hammering the real API)."""


def test_loop_reapplies_the_exclusion_filter_on_every_periodic_cycle(monkeypatch):
    """Not just `_compute_once()` called twice by hand: drives the actual
    `_loop()` body (`while True: _compute_once(); sleep(REFRESH_SECONDS)`,
    the real background-thread target since `start_background_refresh()`)
    through several genuine periodic cycles, in-process and synchronously --
    `time.sleep` is replaced with a counter that raises `_StopLoop` once
    enough cycles have been observed, rather than actually sleeping and
    racing wall-clock time. Confirms the exclusion filter (read fresh from
    the DB inside `_active_tickers()` on every call, no in-memory
    memoization across cycles) holds on cycle 5 exactly as on cycle 1, not
    just "the first call after startup"."""
    seen_ticker_lists = []

    def _fake_download_batch(tickers, start):
        seen_ticker_lists.append(list(tickers))
        return pd.DataFrame()

    def _fake_sleep(seconds):
        if len(seen_ticker_lists) >= 5:
            raise _StopLoop

    monkeypatch.setattr(alerts, "download_batch", _fake_download_batch)
    monkeypatch.setattr(alerts.time, "sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        alerts._loop()

    assert len(seen_ticker_lists) == 5
    for cycle_num, tickers in enumerate(seen_ticker_lists, start=1):
        assert "LBS=F" not in tickers, f"cycle {cycle_num} leaked an excluded symbol"
        assert "^EVZ" not in tickers, f"cycle {cycle_num} leaked an excluded symbol"
