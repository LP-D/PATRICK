"""Résolution des noms, calendrier d'annonces, fiabilité, parseur des facteurs French, garde contre la fuite d'information (aucun réseau)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from earnings_support import FakeProvider, make_world

from patrick.earnings import model, resolve, schedule, signif, store
from patrick.earnings.config import EarningsConfig
from patrick.earnings.panel import load_panel
from patrick.earnings.parse import parse_newsletter
from patrick.earnings.provider import parse_french_csv
from patrick.earnings.reliability import partial_pooling, reliability
from patrick.tracking import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    c = db.connect(str(tmp_path / "patrick.db"))
    yield c
    c.close()


# --------------------------------------------------------------------------------------------------------------- résolution

def test_alias_keys_ignore_accents_punctuation_and_legal_forms():
    n = resolve.normalize_alias
    assert n("Novo Nordisk A/S") == "novo nordisk"
    assert n("Leonardo S.p.A.") == "leonardo"
    assert n("L'Oréal") == "loreal"
    assert n("Block, Inc.") == "block"
    assert n("Air France-KLM") == "air france-klm"
    assert resolve.name_similarity("Novo Nordisk", "Novo Nordisk A/S") > 0.9
    assert resolve.name_matches("Novo Nordisk", "Novo Nordisk A/S") and resolve.name_matches("AMD", "Advanced Micro Devices, Inc.")
    assert resolve.name_matches("Air France-KLM", "Air France-KLM SA") and resolve.name_matches("Apple", "Apple Inc.")
    assert not resolve.name_matches("Block", "Blackrock, Inc.") and not resolve.name_matches("Arm", "Armstrong World Industries")


def test_ambiguous_names_are_seeded_and_still_need_a_first_confirmation(conn):
    items = parse_newsletter("Lundi : Arm, Block, Figma, AMC, Leonardo, Diageo, SharkNinja, Novo Nordisk, Ryanair (ADR), Interparfums", None).items
    rows = {r["name"]: r for r in resolve.resolve_all(conn, items, None)}
    assert rows["Arm"]["symbol"] == "ARM" and rows["Block"]["symbol"] == "XYZ" and rows["Leonardo"]["symbol"] == "LDO.MI"
    assert rows["AMC"]["symbol"] == "AMC" and rows["Diageo"]["adr_symbol"] == "DEO"
    assert rows["Novo Nordisk"]["symbol"] == "NOVO-B.CO" and rows["Novo Nordisk"]["adr_symbol"] == "NVO"
    assert rows["Ryanair"]["symbol"] == "RYAAY" and rows["Ryanair"]["adr_symbol"] == "RYA.IR"     # « (ADR) » inverse le défaut local
    assert rows["Interparfums"]["symbol"] == "ITP.PA" and rows["Interparfums"]["adr_symbol"] == "IPAR"
    assert all("alias semé : à confirmer" in r["flags"] and r["status"] == "pending" for r in rows.values())


def test_a_confirmed_alias_is_remembered_and_overrides_the_seed(conn):
    resolve.confirm_item(conn, {"alias": "block", "name": "Block"}, "SQ", None)
    [row] = resolve.resolve_all(conn, parse_newsletter("Lundi : Block", None).items, None)
    assert row["symbol"] == "SQ" and row["status"] == "confirmed" and row["flags"] == ["alias confirmé"]


def test_yahoo_search_picks_the_local_line_and_flags_the_adr(conn):
    prov = FakeProvider()
    prov.searches["Zeta Corp"] = [
        {"symbol": "ZET", "name": "Zeta Corp ADR", "exchange": "NYSE", "type": "EQUITY"},
        {"symbol": "ZETA.PA", "name": "Zeta Corp SA", "exchange": "Paris", "type": "EQUITY"},
        {"symbol": "ZET.MX", "name": "Zeta Corp", "exchange": "Mexico", "type": "EQUITY"},
        {"symbol": "ZETX", "name": "Zeta Fund", "exchange": "NYSEArca", "type": "ETF"}]
    prov.infos["ZET"] = {"country": "France", "longName": "Zeta Corp ADR", "currency": "USD"}
    prov.infos["ZETA.PA"] = {"country": "France", "longName": "Zeta Corp SA", "currency": "EUR"}
    prov.infos["ZET.MX"] = {"country": "France", "longName": "Zeta Corp", "currency": "MXN"}
    [row] = resolve.resolve_all(conn, parse_newsletter("Lundi : Zeta Corp", None).items, prov)
    assert row["symbol"] == "ZETA.PA" and row["adr_symbol"] == "ZET"                   # locale par défaut, ADR en contrôle
    assert "plusieurs lignes" in row["flags"] and "Yahoo : Zeta Corp SA" in row["flags"]
    assert [c["symbol"] for c in row["candidates"]][:2] == ["ZETA.PA", "ZET"] or "ZET" in [c["symbol"] for c in row["candidates"]]
    assert "ZETX" not in (row["symbol"], row["adr_symbol"])                            # un ETF n'est jamais une société


def test_a_name_that_yahoo_maps_to_another_company_is_flagged(conn):
    prov = FakeProvider()
    prov.infos["XYZ"] = {"longName": "Tout Autre Chose Holdings"}
    [row] = resolve.resolve_all(conn, parse_newsletter("Lundi : Block", None).items, prov)
    assert "nom différent" in row["flags"]


def test_unknown_names_are_reported_not_guessed(conn):
    [row] = resolve.resolve_all(conn, parse_newsletter("Lundi : Société Inconnue SA", None).items, FakeProvider())
    assert row["symbol"] is None and row["flags"] == ["introuvable"]


def test_an_explicit_ticker_in_parentheses_wins(conn):
    [row] = resolve.resolve_all(conn, parse_newsletter("Lundi : Apple (AAPL)", None).items, None)
    assert row["symbol"] == "AAPL" and row["flags"] == ["symbole indiqué"]


# ------------------------------------------------------------------------------------------------------------------ calendrier

def _raw(*stamps):
    return pd.DataFrame([{"ts": pd.Timestamp(ts, tz="America/New_York"), "eps_estimate": 1.0, "eps_actual": act, "surprise_pct": 2.0}
                         for ts, act in stamps])


def test_calendar_rows_convert_european_hours_and_dedupe(conn):
    rows = schedule.calendar_rows("NOVO-B.CO", _raw(("2026-08-06 01:00", 6.0), ("2026-08-06 02:00", 6.1), ("2025-11-05 02:00", 5.0)))
    assert [r["ann_date"] for r in rows] == ["2025-11-05", "2026-08-06"]
    assert {r["timing"] for r in rows} == {"BMO"} and rows[1]["ann_local_time"] in ("07:00", "08:00") and not rows[1]["uncertain"]


def test_a_future_date_with_the_11h_placeholder_falls_back_to_the_venue_default():
    future = _raw(("2027-01-26 11:00", np.nan))
    [row] = schedule.calendar_rows("MC.PA", future)
    assert row["timing"] == "BMO" and row["timing_source"] == "heuristic" and row["uncertain"] == 1 and "provisoire" in row["reason"]
    [us] = schedule.calendar_rows("AAPL", future)
    assert us["timing"] == "UNKNOWN" and us["uncertain"] == 1
    past = _raw(("2019-01-29 11:00", 2.0))                                       # passé et publié : l'heure est une vraie heure
    assert schedule.calendar_rows("SAP.DE", past)[0]["timing_source"] == "yahoo_time"


def test_manual_dates_and_user_override():
    rows = schedule.parse_manual_dates("DGE.L", "2024-02-14\n2024-07-30 07:00\n2024-11-05 AMC\n# commentaire\n")
    assert [(r["timing"], r["uncertain"]) for r in rows] == [("BMO", 1), ("BMO", 0), ("AMC", 0)]
    assert all(r["timing_source"] == "user" and r["source"] == "manual" for r in rows)
    with pytest.raises(ValueError):
        schedule.parse_manual_dates("DGE.L", "hier soir")
    assert schedule.user_override(rows[0], "AMC")["timing"] == "AMC" and schedule.user_override(rows[0], "auto") is rows[0]
    with pytest.raises(ValueError):
        schedule.user_override(rows[0], "MIDI")


def test_reaction_window_follows_timing_certainty():
    auto = EarningsConfig()
    assert schedule.reaction_window("AMC", False, auto) == (0, 0)
    assert schedule.reaction_window("AMC", True, auto) == (0, 1) and schedule.reaction_window("DURING", False, auto) == (0, 1)
    assert schedule.reaction_window("AMC", False, EarningsConfig(reaction="d01")) == (0, 1)


def test_macro_days_cover_fomc_and_first_friday_jobs():
    days = schedule.macro_days("2026-10-01", "2026-11-10")
    assert days[pd.Timestamp("2026-10-28")] == "FOMC" and days[pd.Timestamp("2026-10-02")] == "NFP~" and days[pd.Timestamp("2026-11-06")] == "NFP~"


# --------------------------------------------------------------------------------------------------------------- fiabilité

def test_reliability_grows_with_n_and_is_forced_down_below_the_minimum():
    few = reliability(np.array([0.05, 0.04, 0.06]), n=3, min_events=8)
    many = reliability(np.random.default_rng(0).normal(0.05, 0.01, 60) + 0.05, n=60, min_events=8)
    assert few["level"] == "insuffisant" and many["score"] > few["score"] and many["level"] in ("moyen", "bon")


def test_partial_pooling_pulls_small_samples_toward_their_sector():
    rng = np.random.default_rng(3)
    groups = {"big": rng.normal(0.05, 0.02, 40), "tiny": np.array([0.20, 0.22]), "peer1": rng.normal(0.05, 0.02, 30), "peer2": rng.normal(0.05, 0.02, 30)}
    out = partial_pooling(groups, {k: "tech" for k in groups})
    assert out["tiny"]["shrunk"] < out["tiny"]["raw"] and out["tiny"]["weight"] < out["big"]["weight"]
    assert abs(out["big"]["shrunk"] - out["big"]["raw"]) < abs(out["tiny"]["shrunk"] - out["tiny"]["raw"])


# --------------------------------------------------------------------------------------------- facteurs de la bibliothèque French

def test_french_factor_files_are_parsed_in_decimals():
    text = "This file was created by CMPT_ME_BEME...\n\n,Mkt-RF,SMB,HML,RF\n20260102,  1.00, -0.50,  0.25, 0.01\n20260105, -2.00,  0.10, -0.30, 0.01\n\nAnnual Factors\n2025, 9.0, 1.0, 2.0, 4.0\n"
    df = parse_french_csv(text)
    assert list(df.columns) == ["Mkt_RF", "SMB", "HML", "RF"] and len(df) == 2
    assert df["Mkt_RF"].iloc[0] == pytest.approx(0.01) and df["HML"].iloc[1] == pytest.approx(-0.003)
    assert df.index[0] == pd.Timestamp("2026-01-02")
    assert parse_french_csv("rien d'utile").empty


# ---------------------------------------------------------------------------------------------------- aucune fuite d'information

def test_models_never_read_the_announcement_surprise_or_the_outcome(conn):
    prov, symbols = make_world(n_symbols=6, events_per_symbol=14, seed=5)
    from patrick.earnings import pipeline
    cfg = EarningsConfig()
    pipeline.ingest_many(lambda: db.connect(), prov, symbols, cfg, workers=2)
    df = load_panel(conn, cfg).frame
    assert not set(model.FORBIDDEN_FEATURES) & set(model.AMP_FEATURES + model.DIR_FEATURES)
    base = model.build_features(df)
    scrambled = df.copy()
    rng = np.random.default_rng(1)
    for col in ("surprise_pct", "sue", "beat", "car", "raw", "abs_car", "z", "z_abs", "car01", "ar0", "post_short", "on0", "id0", "vol0"):
        scrambled[col] = rng.normal(size=len(df))
    for col in [c for c in df.columns if c.startswith(("drift_", "bhar_"))]:
        scrambled[col] = rng.normal(size=len(df))
    again = model.build_features(scrambled)
    pd.testing.assert_frame_equal(base[model.AMP_FEATURES + model.DIR_FEATURES], again[model.AMP_FEATURES + model.DIR_FEATURES])


def test_walk_forward_purges_events_overlapping_the_test_block():
    days = pd.Series(pd.to_datetime(["2020-01-01"]) .repeat(1)).iloc[0:0]
    days = pd.Series(pd.date_range("2020-01-01", periods=300, freq="3D"))
    folds = model.walk_forward_folds(days, n_folds=4, min_train_frac=0.4, purge_days=10)
    assert folds
    for train, test in folds:
        assert days.iloc[train].max() < days.iloc[test].min() - pd.Timedelta(days=9)          # purge d'au moins 10 jours
        assert set(train).isdisjoint(test)


def test_kolari_pynnonen_correlation_counts_non_overlapping_pairs_as_zero(conn):
    from earnings_support import bench_frame, make_series, market_returns

    from patrick.earnings import engine
    rm = market_returns(1, 1500)
    bench = bench_frame(rm)
    rows = []
    for k in range(12):                                                   # 12 annonces espacées de ~250 séances : fenêtres d'estimation disjointes
        pos = 300 + 80 * k
        df = make_series(900 + k, n=1500, market=rm, shocks={pos: 0.02})
        sp = engine.SymbolPrices(df, bench["Close"], bench["Open"])
        ev, _ = engine.compute_event(sp, symbol=f"T{k}", ann_date=df.index[pos], timing="BMO", uncertain=False, cfg=EarningsConfig())
        rows.append(ev)
    assert abs(signif.mean_pairwise_correlation(rows, list(range(12)))) < 0.05


def test_generalized_sign_test_is_refused_on_long_windows():
    from earnings_support import bench_frame, make_series, market_returns

    from patrick.earnings import engine
    rm = market_returns(1, 1500)
    bench = bench_frame(rm)
    rows = []
    for k in range(8):
        pos = 400 + 30 * k
        df = make_series(700 + k, n=1500, market=rm, shocks={pos: 0.03})
        sp = engine.SymbolPrices(df, bench["Close"], bench["Open"])
        rows.append(engine.compute_event(sp, symbol=f"T{k}", ann_date=df.index[pos], timing="BMO", uncertain=False, cfg=EarningsConfig())[0])
    out = signif.run_tests(rows, 2, 60, n_boot=100)
    assert out["tests"]["sign"]["p"] is None and "trop longue" in out["tests"]["sign"]["note"]
    assert signif.run_tests(rows, 0, 1, n_boot=100)["tests"]["sign"]["p"] is not None


def test_store_state_roundtrip_and_snapshots_are_frozen_per_day(conn):
    store.put_state(conn, "config", {"model": "factor"})
    assert store.get_state(conn, "config") == {"model": "factor"} and store.get_state(conn, "absent", 5) == 5
    assert store.put_snapshot(conn, "AAPL", "consensus", {"a": 1}, "2026-11-03") is True
    assert store.put_snapshot(conn, "AAPL", "consensus", {"a": 2}, "2026-11-03") is False        # daté = figé
    assert store.snapshots(conn, "AAPL")[0]["payload"] == {"a": 1}
    store.put_alias(conn, "x", "XX", None, "X", "user")
    store.put_alias(conn, "x", "YY", "ADR", None, "user")
    assert store.get_alias(conn, "x")["symbol"] == "YY" and store.get_alias(conn, "x")["display"] == "X"
