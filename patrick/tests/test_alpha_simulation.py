"""Simulation d'un modèle d'alpha : portefeuille long actif / short β × benchmark. Le « prix » simulé est le niveau de
la paire couverte, sur le vrai calendrier du benchmark, avec le β connu à chaque date."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.features import alpha_target as at
from patrick.simulate import engine as sim
from patrick.tracking import db as trackdb

H = 5
N = 700
IDX = pd.bdate_range("2020-01-01", periods=N)


def _prices(true_beta=1.5, seed=0):
    rng = np.random.default_rng(seed)
    rb = rng.normal(0.0004, 0.01, N)
    ra = true_beta * rb + rng.normal(0.0002, 0.004, N)
    return (pd.Series(100 * np.cumprod(1 + ra), index=IDX, name="AAA"),
            pd.Series(100 * np.cumprod(1 + rb), index=IDX, name="BBB"))


# --------------------------------------------------------------------------- le niveau de la paire couverte

def test_pair_level_is_the_compounded_hedged_daily_pnl():
    asset, bench = _prices()
    level, beta = at.alpha_pair_level(asset, bench)
    t = 400
    daily = asset.pct_change().iloc[t] - beta.iloc[t] * bench.pct_change().iloc[t]

    assert level.iloc[0] == pytest.approx(100.0)
    assert level.iloc[t] / level.iloc[t - 1] - 1 == pytest.approx(daily)
    assert (level.iloc[:50] == 100.0).all()                     # pas de β connu : pas de position couverte


def test_pair_level_uses_the_true_benchmark_calendar_under_a_session_lag():
    asset, bench = _prices()
    asof = bench.shift(1)                                        # comme l'ingestion le décale
    level, beta = at.alpha_pair_level(asset, asof, bench_lag=1)
    t = 400
    daily = asset.pct_change().iloc[t] - beta.iloc[t] * bench.pct_change().iloc[t]       # rendement du VRAI jour t

    assert level.iloc[t] / level.iloc[t - 1] - 1 == pytest.approx(daily)


def test_pair_level_hedges_away_the_market():
    asset, bench = _prices(true_beta=1.5, seed=3)
    level, _ = at.alpha_pair_level(asset, bench)
    pair_ret = level.pct_change().dropna().iloc[300:]
    market_ret = bench.pct_change().reindex(pair_ret.index)

    assert abs(np.corrcoef(pair_ret, market_ret)[0, 1]) < 0.25    # la jambe actif seule est corrélée à ~0,95
    assert abs(np.corrcoef(asset.pct_change().reindex(pair_ret.index), market_ret)[0, 1]) > 0.8


# --------------------------------------------------------------------------- simulate() sur un run alpha

def _fixture(tmp_path, scores=None, benchmark="BBB"):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    asset, bench = _prices()
    cfg = RunConfig.model_validate({
        "objective": {"target_symbol": "AAA", "horizons": [H], "target_kind": "alpha", "benchmark": benchmark},
        "universe": {"yf_tickers": ["CCC"], "start_date": "2020-01-01"}})
    label = cfg.objective.run_label()
    store = DataStore(root=str(tmp_path / "store"))
    snap = store.save(cfg.objective.raw_cache_key(), pd.DataFrame({"AAA": asset, "BBB": bench}))
    trackdb.upsert_snapshot(conn, snap, "x", 0, 0, "api")
    trackdb.create_run(conn, "r", target=label, horizon=H, snapshot_id=snap, config_json=cfg.model_dump_json(),
                       config_hash="h", git_sha="s", seed=0)
    tid = trackdb.create_trial(conn, "r", "GLOBAL", "X", "none", 1, "shap")
    positions = list(range(320, 450, H))
    ts = [str(IDX[i]) for i in positions]
    y_pred = scores if scores is not None else [3] * len(ts)
    trackdb.add_predictions(conn, tid, fold_index=0, split="holdout", ts=ts, y_true=[3] * len(ts),
                            y_pred=y_pred, y_proba=[0.8] * len(ts))
    conn.close()
    return db_path, str(tmp_path / "store"), tid, label, cfg


def test_simulate_runs_an_alpha_trial_on_the_hedged_pair(tmp_path):
    db_path, store_root, tid, _label, _cfg = _fixture(tmp_path)

    result = sim.simulate(tid, sim.SimParams(), db_path=db_path, store_root=store_root, segment="holdout")

    assert result["ok"] and result["segment"] == "holdout"
    asset, bench = _prices()
    level, _ = at.alpha_pair_level(asset, bench)
    bh = result["buy_and_hold_curve"]
    first, last = bh[0]["t"], bh[-1]["t"]
    pair_window = level.loc[first:last]
    expected = (1 + pair_window.pct_change().fillna(0.0)).cumprod()
    assert bh[-1]["v"] == pytest.approx(float(expected.iloc[-1]), rel=1e-6)          # « acheter-garder » = la paire couverte
    assert result["hedge"]["benchmark"] == "BBB" and result["hedge"]["cost_multiplier"] > 1.0


def test_hedge_cost_multiplier_charges_both_legs(tmp_path):
    db_path, store_root, tid, _l, _c = _fixture(tmp_path, scores=[3, 0] * 13)
    params = sim.SimParams(spread_bps=5.0, commission_bps=5.0)

    result = sim.simulate(tid, params, db_path=db_path, store_root=store_root, segment="holdout")

    mult = result["hedge"]["cost_multiplier"]
    assert 1.0 < mult < 4.0 and mult == pytest.approx(1 + result["hedge"]["median_abs_beta"], abs=1e-6)
    assert result["params"]["spread_bps"] == 5.0                       # les paramètres saisis ne sont pas réécrits


def test_a_perfect_alpha_forecast_earns_money_on_the_pair_and_a_perverse_one_loses(tmp_path):
    asset, bench = _prices()
    forward = at.alpha_labels(asset, bench, H)
    positions = list(range(320, 450, H))
    truth = [3 if forward.iloc[i] > 0 else 0 for i in positions]
    wrong = [0 if v == 3 else 3 for v in truth]

    good = _fixture(tmp_path / "good", scores=truth)
    bad = _fixture(tmp_path / "bad", scores=wrong)
    r_good = sim.simulate(good[2], sim.SimParams(), db_path=good[0], store_root=good[1], segment="holdout")
    r_bad = sim.simulate(bad[2], sim.SimParams(), db_path=bad[0], store_root=bad[1], segment="holdout")

    assert r_good["equity_curve"][-1]["v"] > 1.0 > r_bad["equity_curve"][-1]["v"]


def test_dsr_counts_the_alpha_family_only(tmp_path):
    db_path, store_root, tid, label, _c = _fixture(tmp_path)
    conn = trackdb.connect(db_path)
    trackdb.register_trials(conn, label, H, "scan", 7)
    trackdb.register_trials(conn, "AAA", H, "scan", 1000)               # la famille brute du même actif ne compte pas
    conn.close()

    result = sim.simulate(tid, sim.SimParams(), db_path=db_path, store_root=store_root, segment="holdout")

    assert result["strategy"]["dsr_n_trials"] == 7 + 1 + 1             # essais d'alpha + celui-ci + l'essai créé par create_trial


def test_the_cost_multiplier_really_lowers_the_equity_curve(tmp_path, monkeypatch):
    """Les coûts de la couverture pèsent sur la courbe, pas seulement dans le texte du résultat."""
    db_path, store_root, tid, _l, _c = _fixture(tmp_path, scores=[3, 0] * 13)
    params = sim.SimParams(spread_bps=10.0, commission_bps=10.0)
    real = sim.simulate(tid, params, db_path=db_path, store_root=store_root, segment="holdout")

    original = sim._alpha_pair

    def one_leg_costs(run, raw):
        level, hedge, _multiplier = original(run, raw)
        return level, hedge, 1.0

    monkeypatch.setattr(sim, "_alpha_pair", one_leg_costs)
    one_leg = sim.simulate(tid, params, db_path=db_path, store_root=store_root, segment="holdout")

    assert real["equity_curve"][-1]["v"] < one_leg["equity_curve"][-1]["v"]
