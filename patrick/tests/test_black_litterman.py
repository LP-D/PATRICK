"""Black-Litterman v2 : les « vues » viennent des probabilités de hausse CALIBRÉES (`prediction.p_up`), la confiance de leur
netteté, le prior d'une pondération de référence (HRP). Aucun appel au réseau, aucun réentraînement."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from patrick.data.store import DataStore
from patrick.tracking import black_litterman as bl
from patrick.tracking import db


def _cov(vols=(0.2, 0.3, 0.25), corr=0.5):
    n = len(vols)
    c = np.full((n, n), corr)
    np.fill_diagonal(c, 1.0)
    d = np.diag(vols)
    names = list("ABCDEFG")[:n]
    return pd.DataFrame(d @ c @ d, index=names, columns=names)


def test_implied_returns_are_risk_aversion_times_covariance_times_weights():
    cov = _cov()
    w = pd.Series([0.5, 0.3, 0.2], index=cov.index)
    pi = bl.implied_returns(cov, w, risk_aversion=2.5)
    np.testing.assert_allclose(pi.values, 2.5 * cov.values @ w.values)


def test_view_return_is_proportional_to_the_edge_and_to_horizon_scaled_volatility():
    vol = pd.Series({"A": 0.20, "B": 0.40})
    q = bl.view_returns(pd.Series({"A": 0.75, "B": 0.25}), vol, horizon=21)
    expected = 0.5 * np.sqrt(2 / np.pi) * 0.20 * np.sqrt(252 / 21)
    assert q["A"] == pytest.approx(expected)
    assert q["B"] == pytest.approx(-0.5 * np.sqrt(2 / np.pi) * 0.40 * np.sqrt(252 / 21))
    assert bl.view_returns(pd.Series({"A": 0.5}), vol, 21)["A"] == 0.0


def test_no_view_means_the_posterior_is_the_prior():
    cov = _cov()
    pi = bl.implied_returns(cov, pd.Series(1 / 3, index=cov.index))
    mu, sigma = bl.posterior(cov, pi, pd.Series(dtype=float), pd.Series(dtype=float))
    np.testing.assert_allclose(mu.values, pi.values)
    assert (np.diag(sigma) >= np.diag(cov.values)).all()


def test_a_bullish_view_raises_and_a_bearish_view_lowers_the_expected_return():
    cov = _cov()
    pi = bl.implied_returns(cov, pd.Series(1 / 3, index=cov.index))
    omega = pd.Series({"A": 0.01})
    up, _ = bl.posterior(cov, pi, pd.Series({"A": pi["A"] + 0.10}), omega)
    down, _ = bl.posterior(cov, pi, pd.Series({"A": pi["A"] - 0.10}), omega)
    assert up["A"] > pi["A"] > down["A"]


def test_a_view_on_one_asset_moves_the_correlated_ones_the_same_way():
    cov = _cov(corr=0.7)
    pi = bl.implied_returns(cov, pd.Series(1 / 3, index=cov.index))
    mu, _ = bl.posterior(cov, pi, pd.Series({"A": pi["A"] + 0.15}), pd.Series({"A": 0.005}))
    assert mu["B"] > pi["B"] and mu["C"] > pi["C"]


def test_a_less_confident_view_stays_closer_to_the_prior():
    cov = _cov()
    pi = bl.implied_returns(cov, pd.Series(1 / 3, index=cov.index))
    q = pd.Series({"A": pi["A"] + 0.10})
    sure, _ = bl.posterior(cov, pi, q, pd.Series({"A": 0.001}))
    unsure, _ = bl.posterior(cov, pi, q, pd.Series({"A": 0.1}))
    assert abs(unsure["A"] - pi["A"]) < abs(sure["A"] - pi["A"])


def test_undecided_probabilities_give_no_view_and_decisive_ones_give_more_confidence():
    p = pd.Series({"A": 0.51, "B": 0.62, "C": 0.9})
    keep = bl.select_views(p, min_edge=0.05)
    assert list(keep.index) == ["B", "C"]
    conf = bl.view_confidence(keep)
    assert conf["C"] > conf["B"] > 0


def test_optimal_weights_are_long_only_capped_and_sum_to_one():
    cov = _cov((0.2, 0.3, 0.25, 0.35, 0.15))
    mu = pd.Series([0.10, 0.02, 0.05, 0.12, 0.01], index=cov.index)
    w = bl.optimal_weights(mu, cov, risk_aversion=2.5, max_weight=0.4)
    assert w.sum() == pytest.approx(1.0, abs=1e-6)
    assert (w >= -1e-9).all() and (w <= 0.4 + 1e-6).all()


def test_weights_tilt_toward_the_bullish_asset_and_away_from_the_bearish_one():
    cov = _cov((0.2, 0.2, 0.2))
    ref = pd.Series(1 / 3, index=cov.index)
    result = bl.black_litterman(cov, ref, pd.Series({"A": 0.85, "B": 0.15}), horizon=21, max_weight=0.6)
    w = result["weights"]
    assert w["A"] > ref["A"] > w["B"]
    assert result["views"].loc["A", "view_return"] > 0 > result["views"].loc["B", "view_return"]
    assert set(result["views"].index) == {"A", "B"}


def test_without_decisive_probabilities_the_portfolio_is_the_reference_one():
    cov = _cov()
    ref = pd.Series([0.5, 0.3, 0.2], index=cov.index)
    result = bl.black_litterman(cov, ref, pd.Series({"A": 0.5, "B": 0.51}), horizon=21, max_weight=1.0)
    assert result["views"].empty
    np.testing.assert_allclose(result["weights"].values, ref.values, atol=1e-3)


# --- lecture des probabilités et vue d'ensemble ------------------------------------------------------------------------

def _run_with_p_up(conn, run_id, target, horizon, p_up, *, calibrated=True, split="live", ts="2026-10-16"):
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    db.create_run(conn, run_id, target, horizon, f"snap_{run_id}",
                  json.dumps({"name": run_id, "models": {"calibration": calibrated}}), "h", "sha", 1)
    db.finish_run(conn, run_id, status="done", n_trials=1)
    trial = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.add_predictions(conn, trial, 1, split, [ts], [None], [3], [0.6], p_up=[p_up])


def test_only_calibrated_probabilities_are_read(conn):
    _run_with_p_up(conn, "r1", "A", 21, 0.8, calibrated=True)
    _run_with_p_up(conn, "r2", "B", 21, 0.9, calibrated=False)
    got = bl.latest_calibrated_p_up(conn, ["A", "B", "C"], 21)
    assert got == {"A": pytest.approx(0.8)}
    assert bl.latest_calibrated_p_up(conn, ["A", "B"], 21, require_calibrated=False) == {
        "A": pytest.approx(0.8), "B": pytest.approx(0.9)}


def test_the_most_recent_live_probability_wins(conn):
    _run_with_p_up(conn, "r1", "A", 21, 0.3, ts="2026-10-01")
    _run_with_p_up(conn, "r2", "A", 21, 0.8, ts="2026-10-15")
    assert bl.latest_calibrated_p_up(conn, ["A"], 21)["A"] == pytest.approx(0.8)


def test_overview_reads_cached_prices_and_never_downloads(conn, tmp_path):
    import patrick.config.defaults as D
    from patrick.data.sources.yfinance_source import clean_symbol

    store = DataStore(root=str(tmp_path))
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2018-01-01", periods=400)
    symbols = D.DEFAULT_UNIVERSE_YF_TICKERS[:4]
    for sym in symbols:
        store.save(f"raw_{sym}", pd.DataFrame(
            {clean_symbol(sym): 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(idx)))}, index=idx))
    _run_with_p_up(conn, "r1", symbols[0], 21, 0.85)
    _run_with_p_up(conn, "r2", symbols[1], 21, 0.15)
    out = bl.bl_overview(conn, horizon=21, store=store, max_age_days=None)
    assert out["n_assets"] == 4 and out["n_views"] == 2
    assert out["weights"].sum() == pytest.approx(1.0, abs=1e-6)
    assert out["weights"][symbols[0]] > out["reference"][symbols[0]]
    assert out["weights"][symbols[1]] < out["reference"][symbols[1]]
    assert set(out["views"].index) == {symbols[0], symbols[1]}
    assert out["covariance"] == "ledoit_wolf"


def test_overview_without_calibrated_views_says_so(conn, tmp_path):
    store = DataStore(root=str(tmp_path))
    out = bl.bl_overview(conn, horizon=21, store=store)
    assert out["n_assets"] == 0 and out["n_views"] == 0 and out["weights"].empty


def test_table_rows_pair_each_weight_with_its_view_when_it_has_one():
    cov = _cov((0.2, 0.2, 0.2))
    ref = pd.Series(1 / 3, index=cov.index)
    rows = bl.table_rows(bl.black_litterman(cov, ref, pd.Series({"A": 0.85}), horizon=21, max_weight=0.6))
    assert rows[0]["symbol"] == "A"                       # triées par poids décroissant
    a = rows[0]
    assert a["tilt_pts"] == pytest.approx((a["weight"] - a["reference"]) * 100)
    assert a["p_up"] == pytest.approx(0.85) and a["view_return"] > 0 and 0 < a["confidence"] <= 1
    assert all(r["p_up"] is None and r["view_return"] is None for r in rows[1:])
    assert sum(r["weight"] for r in rows) == pytest.approx(1.0, abs=1e-6)
