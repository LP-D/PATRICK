"""Économétrie d'une série, partie 4 : prévision de variance hors échantillon, pertes robustes (QLIKE, MSE), Mincer-Zarnowitz, Model Confidence Set,
Diebold-Mariano, tests de couverture de la VaR (Kupiec, Christoffersen).

La vérité est connue (processus simulé avec sa vraie variance conditionnelle) : une bonne mesure doit préférer la vraie variance à une variance
fausse, et un test de couverture ne doit pas rejeter la bonne VaR."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from patrick.econometrics import forecast_eval as F
from patrick.econometrics import simulate as SIM


def _world(n=1500, seed=1):
    r, h = SIM.garch11(n, 0.05, 0.10, 0.85, seed=seed, return_variance=True)
    return r / 100.0, h / 1e4                                   # rendements et variance vraie, en décimal


# ---------------------------------------------------------------- pertes
def test_qlike_is_zero_at_the_truth_and_positive_elsewhere():
    h = np.array([1.0, 2.0, 3.0])
    assert F.qlike(h, h) == pytest.approx(0.0)
    assert (F.qlike(h, h * 2) > 0).all() and (F.qlike(h, h / 2) > 0).all()


@pytest.mark.parametrize("loss", [F.qlike, F.mse_var])
def test_the_true_variance_has_the_lowest_expected_loss_against_a_noisy_proxy(loss):
    r, h = _world(6000, seed=2)
    proxy = r.to_numpy() ** 2                                   # r^2 : bruité mais sans biais
    best = loss(proxy, h.to_numpy()).mean()
    assert best < loss(proxy, h.to_numpy() * 1.6).mean()
    assert best < loss(proxy, h.to_numpy() * 0.6).mean()


def test_qlike_penalizes_under_prediction_more_than_over_prediction():
    p = np.array([1.0])
    assert F.qlike(p, np.array([0.5]))[0] > F.qlike(p, np.array([2.0]))[0]


# ---------------------------------------------------------------- Mincer-Zarnowitz
def test_mincer_zarnowitz_accepts_the_true_variance_and_rejects_a_scaled_one():
    r, h = _world(5000, seed=3)
    proxy = pd.Series(r.to_numpy() ** 2, index=r.index)
    good = F.mincer_zarnowitz(proxy, h)
    bad = F.mincer_zarnowitz(proxy, h * 2)
    assert good["pvalue"] > 0.01 and good["slope"] == pytest.approx(1.0, abs=0.25)
    assert bad["pvalue"] < 0.001 and bad["slope"] == pytest.approx(0.5, abs=0.15)


# ---------------------------------------------------------------- prévisions hors échantillon
def test_forecasts_cover_only_the_out_of_sample_dates_and_are_positive():
    r, _ = _world(900, seed=4)
    f = F.variance_forecasts(r, "garch", "normal", min_train=500, refit_every=100)
    assert list(f.index) == list(r.index[500:]) and (f["var"] > 0).all()
    assert {"var", "q01", "q05"} <= set(f.columns) and (f["q01"] < f["q05"]).all() and (f["q05"] < 0).all()


def test_forecasts_never_use_the_future():
    r, _ = _world(900, seed=5)
    short = F.variance_forecasts(r.iloc[:650], "garch", "normal", min_train=500, refit_every=100)
    long = F.variance_forecasts(r, "garch", "normal", min_train=500, refit_every=100)
    common = short.index
    np.testing.assert_allclose(short["var"].to_numpy(), long.loc[common, "var"].to_numpy(), rtol=1e-9)
    np.testing.assert_allclose(short["q05"].to_numpy(), long.loc[common, "q05"].to_numpy(), rtol=1e-9)


def test_a_rolling_window_forgets_old_data():
    r, _ = _world(900, seed=6)
    expanding = F.variance_forecasts(r, "garch", "normal", min_train=500, refit_every=200)
    rolling = F.variance_forecasts(r, "garch", "normal", min_train=500, refit_every=200, window=300)
    assert not np.allclose(expanding["var"].to_numpy()[-100:], rolling["var"].to_numpy()[-100:])


def test_benchmarks_are_causal_and_cheap():
    r, _ = _world(700, seed=7)
    rm = F.riskmetrics_forecasts(r, min_train=300)
    roll = F.rolling_forecasts(r, min_train=300, window=60)
    assert list(rm.index) == list(r.index[300:]) == list(roll.index)
    expected = 0.94 * rm["var"].iloc[0] + 0.06 * r.iloc[300] ** 2
    assert rm["var"].iloc[1] == pytest.approx(expected)
    assert roll["var"].iloc[0] == pytest.approx((r.iloc[240:300] ** 2).mean())


def test_har_forecasts_use_the_realized_variance_proxy():
    rng = np.random.default_rng(8)
    idx = SIM.arma(700, seed=0).index
    rv = pd.Series(np.abs(rng.normal(1e-4, 3e-5, 700)) + 1e-5, index=idx)
    f = F.har_forecasts(rv, min_train=300, refit_every=100)
    assert list(f.index) == list(idx[300:]) and (f["var"] > 0).all()


# ---------------------------------------------------------------- comparaison
def test_model_comparison_ranks_the_true_variance_first_and_keeps_it_in_the_confidence_set():
    r, h = _world(2000, seed=9)
    proxy = pd.Series(r.to_numpy() ** 2, index=r.index)
    forecasts = {"truth": h, "double": h * 2, "half": h * 0.5, "constant": pd.Series(r.var(), index=r.index)}
    cmp_ = F.compare_forecasts(proxy, forecasts, benchmark="constant", mcs_size=0.10, seed=0, reps=300)
    rows = {row["name"]: row for row in cmp_["rows"]}
    assert cmp_["rows"][0]["name"] == "truth"
    assert rows["truth"]["in_mcs"] is True and rows["double"]["in_mcs"] is False
    assert rows["truth"]["dm_p"] < 0.05 and rows["truth"]["dm_better"] is True
    assert all(row["dm_p_adj"] >= row["dm_p"] - 1e-12 for row in cmp_["rows"] if row["dm_p"] is not None)
    assert cmp_["n_models"] == 4


# ---------------------------------------------------------------- VaR
def test_kupiec_matches_the_closed_form_and_accepts_the_right_rate():
    n, x, p = 250, 10, 0.01
    expected = 2 * (x * np.log(x / (n * p)) + (n - x) * np.log((n - x) / (n * (1 - p))))
    hits = np.zeros(n, dtype=bool)
    hits[::25] = True                                           # 10 dépassements espacés
    k = F.kupiec_pof(hits, p)
    assert k["lr"] == pytest.approx(expected) and k["pvalue"] == pytest.approx(stats.chi2.sf(expected, 1))
    assert F.kupiec_pof(np.r_[True, np.zeros(99, dtype=bool)], 0.01)["pvalue"] == pytest.approx(1.0)


def test_christoffersen_independence_separates_clustered_from_spread_hits():
    n = 1000
    spread = np.zeros(n, dtype=bool)
    spread[::50] = True
    clustered = np.zeros(n, dtype=bool)
    for start in range(0, n, 250):
        clustered[start:start + 5] = True
    assert F.christoffersen(spread, 0.02)["independence"]["pvalue"] > 0.2
    assert F.christoffersen(clustered, 0.02)["independence"]["pvalue"] < 0.001
    assert set(F.christoffersen(spread, 0.02)) == {"unconditional", "independence", "conditional"}


def test_the_true_var_passes_both_tests_and_a_constant_var_fails_independence():
    # volatilité très groupée (alpha 0,15, beta 0,83) : une VaR constante dépasse en grappes, la vraie VaR non
    for seed in range(5):
        r, h = SIM.garch11(6000, 0.02, 0.15, 0.83, seed=seed, return_variance=True)
        true_hits = (r < stats.norm.ppf(0.05) * np.sqrt(h)).to_numpy()
        const_hits = (r < stats.norm.ppf(0.05) * r.std()).to_numpy()
        assert F.christoffersen(true_hits, 0.05)["conditional"]["pvalue"] > 0.001
        assert F.christoffersen(const_hits, 0.05)["independence"]["pvalue"] < 0.001


# ---------------------------------------------------------------- bout en bout
def test_end_to_end_evaluation_reports_each_model_and_counts_the_comparisons_made():
    r, _ = _world(1000, seed=11)
    out = F.evaluate_forecasts(r, None, ["garch|normal", "gjr|t", "riskmetrics", "rolling60"], min_train=500, refit_every=125, mcs_reps=200)
    assert out["comparison"]["n_models"] == 4 and out["n_obs"] == 500
    assert set(out["var_backtest"]) >= {"garch|normal", "riskmetrics"} and out["proxy"] == "squared_return"
    assert "0.05" in out["var_backtest"]["garch|normal"] and out["refit"]["garch|normal"]["n_refits"] == 4


def test_a_model_name_that_does_not_exist_is_refused():
    r, _ = _world(700, seed=12)
    with pytest.raises(ValueError, match="inconnu"):
        F.evaluate_forecasts(r, None, ["garch|laplace"], min_train=500, refit_every=100)
