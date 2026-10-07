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
    """Univers réduit (feature/universe-reduction) : des 9 symboles exclus
    seedés par la migration 0013, LBS=F était le dernier encore présent dans
    D.DEFAULT_UNIVERSE_YF_TICKERS ; il en est retiré le 2026-09-26 (plus
    aucune cotation Yahoo). Les 8 autres appartenaient à des groupes
    entièrement retirés. L'exclusion M1 reste en place pour tout univers
    explicite (config YAML) qui les listerait encore -- calculé
    dynamiquement plutôt que réaffirmé en dur."""
    active = alerts._active_tickers()
    seeded_excluded = {"LBS=F", "HYLD", "TBP", "GXG", "LVRK", "TERM", "^EVZ", "CYB", "BZF"}
    assert "LBS=F" not in active
    still_in_universe = seeded_excluded & set(D.DEFAULT_UNIVERSE_YF_TICKERS)
    assert still_in_universe == set(), (
        "précondition du test invalide : le jeu de tickers seedés comme exclus "
        "présents dans l'univers réduit a changé, ce test doit être revu"
    )
    # The ranked pool is every selectable yfinance target (a superset of the
    # default feature pool): nothing of the default pool is lost, and no
    # seeded-excluded symbol is present anywhere in it.
    assert set(D.DEFAULT_UNIVERSE_YF_TICKERS) - set(active) == still_in_universe
    assert not seeded_excluded & set(active)


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


def test_movers_rank_every_selectable_yfinance_target_not_just_the_feature_pool():
    """« Plus fortes variations » proposait des symboles cliquables : le
    classement doit donc couvrir TOUS les tickers yfinance sélectionnables au
    lancement (univers réduit + actions + extension vérifiée), pas
    seulement le pool de features par défaut (24 symboles)."""
    from patrick.webapp import forms

    active = set(alerts._active_tickers())
    selectable = {s for s, _, src in forms.TARGET_CHOICES if src == "yfinance"} - D.BAD_TICKERS
    assert active == selectable
    assert len(active) > 4 * len(D.DEFAULT_UNIVERSE_YF_TICKERS)
    # un titre individuel, une action française de l'extension, un ETF, une action allemande
    assert {"AMZN", "MC.PA", "XLK", "SAP.DE", "TSLA"} <= active
    # le fonds FRED n'est pas téléchargeable chez Yahoo
    assert "VIXCLS" not in active
    assert alerts._label_for("MC.PA") == "LVMH"
    assert alerts._label_for("INCONNU") == "INCONNU"


def test_compute_once_ranks_all_downloaded_symbols_and_reports_coverage(monkeypatch):
    tickers = alerts._active_tickers()
    days = pd.bdate_range("2026-09-01", periods=12)
    data = {alerts.clean_symbol(t): [100.0] * 12 for t in tickers}
    data[alerts.clean_symbol("TSLA")] = [100.0] * 6 + [100.0, 105.0, 110.0, 115.0, 120.0, 130.0]
    data[alerts.clean_symbol("SAP.DE")] = [100.0] * 6 + [100.0, 95.0, 90.0, 85.0, 80.0, 70.0]
    frame = pd.DataFrame(data, index=days)
    del_cols = [alerts.clean_symbol("XLK")]
    frame = frame.drop(columns=del_cols)  # a symbol Yahoo silently failed to serve
    monkeypatch.setattr(alerts, "download_batch", lambda t, s: frame)

    alerts._compute_once()
    out = alerts.get_cached()

    assert out["gainers"][0]["symbol"] == "TSLA" and out["gainers"][0]["label"] != "TSLA"
    assert out["losers"][0]["symbol"] == "SAP.DE"
    assert out["n_requested"] == len(tickers)
    assert out["n_ranked"] == len(tickers) - 1


def test_trailing_all_nan_row_is_dropped_before_the_forward_fill(monkeypatch):
    """Une ligne finale entièrement vide (séance en cours) ne doit pas être
    recopiée depuis la veille : elle raccourcirait d'une séance la fenêtre
    des 5 jours de TOUS les symboles."""
    days = pd.bdate_range("2026-09-01", periods=8)
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
    frame = pd.DataFrame({"TSLA": prices + [float("nan")]}, index=days)
    monkeypatch.setattr(alerts, "_active_tickers", lambda: ["TSLA"])
    monkeypatch.setattr(alerts, "download_batch", lambda t, s: frame)

    alerts._compute_once()

    # last real row = 110, five rows earlier = 100 -> +10 %
    assert alerts.get_cached()["gainers"][0]["pct"] == 10.0
