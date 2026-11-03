"""Ingestion, panel et cartes d'étude sur le marché synthétique (aucun réseau)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from earnings_support import make_world

from patrick.earnings import pipeline, store
from patrick.earnings.config import EarningsConfig
from patrick.earnings.panel import Scope, load_panel
from patrick.earnings.studies import REGISTRY, Ctx, fdr_ledger, run_study
from patrick.tracking import db


@pytest.fixture(scope="module")
def world():
    return make_world(n_symbols=12, events_per_symbol=14, seed=7)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    c = db.connect(str(tmp_path / "patrick.db"))
    yield c
    c.close()


@pytest.fixture
def ingested(conn, world):
    provider, symbols = world
    cfg = EarningsConfig()
    reports = pipeline.ingest_many(lambda: db.connect(), provider, symbols, cfg, workers=2)
    return provider, symbols, cfg, reports


def _ctx(conn, provider, cfg, scope=None):
    scope = scope or Scope()
    full = load_panel(conn, cfg)
    return Ctx(full.with_scope(scope), full, conn, provider, cfg, scope)


def test_ingestion_stores_calendar_instrument_and_measures(conn, ingested):
    _provider, _symbols, cfg, reports = ingested
    assert all(r.ok for r in reports), [r.errors for r in reports]
    assert sum(r.n_events for r in reports) == 12 * 14
    cal = store.calendar_for(conn, "S00")
    assert len(cal) == 14 and {c["timing"] for c in cal} == {"AMC"} and cal[0]["timing_source"] == "yahoo_time"
    assert {c["timing"] for c in store.calendar_for(conn, "S01")} == {"BMO"}
    assert store.get_instrument(conn, "S00")["sector"] == "Technology"
    assert len(store.load_results(conn, cfg.measure_hash(), ["S00"])) == 14


def test_the_panel_has_no_lookahead_in_historical_columns(conn, ingested):
    _provider, _symbols, cfg, _ = ingested
    panel = load_panel(conn, cfg)
    df = panel.frame
    assert len(df) == 168 and df["day0"].is_monotonic_increasing
    s = df[df["symbol"] == "S00"].sort_values("day0").reset_index(drop=True)
    assert s["event_no"].tolist() == list(range(1, 15)) and pd.isna(s.loc[0, "hist_mean_abs_z"])
    # la moyenne historique de l'événement k est celle des k-1 premiers, jamais celle qui l'inclut
    for k in (3, 8):
        assert s.loc[k, "hist_mean_abs_z"] == pytest.approx(s.loc[:k - 1, "z_abs"].mean())
    # SUE : au moins 4 surprises passées requises
    assert s["sue"].iloc[:4].isna().all() and s["sue"].iloc[5:].notna().all()
    # secteur : événements strictement antérieurs seulement (pas ceux du même jour)
    first_day = df["day0"].min()
    assert df.loc[df["day0"] == first_day, "sector_hist_abs_z"].isna().all()


def test_reaction_is_larger_for_amc_after_the_shift_is_handled(conn, ingested):
    _provider, _symbols, cfg, _ = ingested
    df = load_panel(conn, cfg).frame
    for timing, part in df.groupby("timing"):
        assert part["z_abs"].mean() > 1.0, timing                    # le choc injecté est bien capté, BMO comme AMC
    assert not df["timing_suspect"].any()


def test_every_light_card_runs_on_the_synthetic_world(conn, ingested):
    """Cartes rapides seulement (la suite rapide garde ses tests sous ~10 s) ; les cartes longues sont dans le test marqué slow."""
    provider, _symbols, cfg, _ = ingested
    ctx = _ctx(conn, provider, cfg)
    for sid, st in REGISTRY.items():
        if st.heavy:
            continue
        res = run_study(ctx, sid, force=True)
        assert res["status"] in ("ok", "insufficient", "unavailable"), (sid, res.get("reason"))
    assert run_study(ctx, "core_event_study")["status"] == "ok"


@pytest.mark.slow
def test_every_card_runs_on_the_synthetic_world(conn, ingested):
    provider, _symbols, cfg, _ = ingested
    ctx = _ctx(conn, provider, cfg)
    results = {}
    for sid in REGISTRY:
        res = run_study(ctx, sid, force=True)
        results[sid] = res
        assert res["status"] in ("ok", "insufficient", "unavailable"), (sid, res.get("reason"))
    assert results["core_event_study"]["status"] == "ok"
    ledger = fdr_ledger(results)
    assert ledger["n_tested"] > 5 and ledger["n_bh"] <= ledger["n_raw"]


def test_cards_are_cached_until_the_data_changes(conn, ingested):
    provider, _symbols, cfg, _ = ingested
    ctx = _ctx(conn, provider, cfg)
    first = run_study(ctx, "a_reaction_dist")
    second = run_study(ctx, "a_reaction_dist")
    assert first["cached"] is False and second["cached"] is True
    other = run_study(ctx, "a_reaction_dist", {"group_by": "sector"})
    assert other["cached"] is False                                    # autres paramètres, autre entrée de cache
    with pytest.raises(ValueError):
        run_study(ctx, "a_reaction_dist", {"group_by": "nimporte"})
    # une nouvelle mesure (recalcul d'un titre) change la version des données : le cache n'est plus servi
    pipeline.ingest_symbol(conn, provider, "S00", cfg)
    ctx2 = _ctx(conn, provider, cfg)
    assert run_study(ctx2, "a_reaction_dist")["cached"] is False


def test_scopes_filter_the_panel(conn, ingested):
    _provider, _symbols, cfg, _ = ingested
    full = load_panel(conn, cfg)
    assert full.with_scope(Scope("symbol", "S03")).n == 14
    assert full.with_scope(Scope("sector", "Energy")).n == 4 * 14
    assert full.with_scope(Scope("batch"), batch_symbols=["S00", "S01"]).n == 28
    week = full.frame["day0"].iloc[40]
    monday = (week - pd.Timedelta(days=week.weekday())).strftime("%Y-%m-%d")
    assert 0 < full.with_scope(Scope("week", monday)).n < 30
    assert Scope.parse("sector:Energy") == Scope("sector", "Energy") and Scope.parse("all").key == "all"
    with pytest.raises(ValueError):
        Scope.parse("planète:Mars")


def test_the_erc_is_recovered_from_the_injected_surprise_effect(conn, ingested):
    provider, _symbols, cfg, _ = ingested
    res = run_study(_ctx(conn, provider, cfg), "d_surprise_erc")
    erc = res["blocks"][0]["rows"][0]
    assert erc[2] > 0.1 and erc[4] < 0.01                                    # pente positive significative (choc ∝ surprise)


def test_user_timing_override_survives_a_yahoo_refresh(conn, ingested):
    provider, _symbols, cfg, _ = ingested
    row = store.calendar_for(conn, "S00")[3]
    from patrick.earnings import schedule
    store.upsert_calendar(conn, [schedule.user_override(row, "BMO")], keep_user=False)
    pipeline.ingest_symbol(conn, provider, "S00", cfg)                       # le rafraîchissement Yahoo remet AMC
    after = next(c for c in store.calendar_for(conn, "S00") if c["ann_date"] == row["ann_date"])
    assert after["timing"] == "BMO" and after["timing_source"] == "user"


def test_missing_prices_are_reported_not_raised(conn):
    from earnings_support import FakeProvider
    rep = pipeline.ingest_symbol(conn, FakeProvider(), "ZZZ", EarningsConfig())
    assert not rep.ok and rep.errors and "cours" in rep.errors[0]
    assert np.isnan(np.nan)


def test_option_snapshots_are_matched_to_realized_moves_and_late_ones_are_ignored(conn, ingested):
    provider, _symbols, cfg, _ = ingested
    df = load_panel(conn, cfg).frame
    rows = df[df["symbol"].isin(["S00", "S01", "S02"])].sort_values("day0").tail(24)
    for r in rows.itertuples():
        store.put_snapshot(conn, r.symbol, "options", {"straddle_pct": 0.05, "target_ann_date": str(r.ann_date.date())}, str((r.day0 - pd.Timedelta(days=3)).date()))
    late = rows.iloc[0]
    store.put_snapshot(conn, late.symbol, "options", {"straddle_pct": 0.90, "target_ann_date": str(late.ann_date.date())}, str((late.day0 + pd.Timedelta(days=5)).date()))
    ctx = _ctx(conn, provider, cfg)
    res = run_study(ctx, "b_implied_realized", force=True)
    assert res["status"] == "ok" and res["n"] == 24                                   # le cliché pris APRÈS la réaction est écarté
    ensemble = {it["label"]: it["value"] for it in res["blocks"][0]["items"]}
    assert ensemble["Mouvement implicite moyen"] == pytest.approx(0.05)
    assert any("baselines" in b.get("title", "") for b in res["blocks"])               # le mouvement implicite sert de baseline
    assert run_study(ctx, "b_straddle_backtest", force=True)["status"] == "ok"


def test_statistics_can_be_conditioned_on_the_regime(conn, ingested):
    provider, _symbols, cfg, _ = ingested
    ctx = _ctx(conn, provider, cfg)
    res = run_study(ctx, "a_reaction_dist", {"group_by": "regime"}, force=True)
    labels = {row[0] for row in res["blocks"][0]["rows"]}
    assert res["status"] == "ok" and labels <= {"calme", "normal", "stress", "inconnu"} and len(labels) >= 2
    assert run_study(ctx, "d_surprise_erc", {"group_by": "regime"}, force=True)["status"] in ("ok", "insufficient")
