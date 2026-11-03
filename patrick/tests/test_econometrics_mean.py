"""Économétrie d'une série, partie 2 : moyenne conditionnelle (grille ARMA/ARIMA/SARIMA/ARIMAX, diagnostics des résidus, ordre d'intégration d).

Processus simulés à paramètres connus. Le cas qui compte le plus est le bruit blanc : le verdict doit être « aucun modèle ne bat la constante »,
pas un ordre (p,q) fabriqué."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.econometrics import mean_models as M
from patrick.econometrics import simulate as SIM


def _row(res, order):
    return next(r for r in res["rows"] if tuple(r["order"]) == tuple(order))


def test_arma_grid_finds_the_autoregression_that_was_simulated():
    x = SIM.arma(1500, ar=(0.6,), seed=1)
    res = M.fit_arma_grid(x, max_p=2, max_q=2)
    best = res["best"]
    assert best["order"][0] >= 1                              # l'ordre AR est détecté
    assert res["verdict"] == "better_than_constant" and res["delta_bic"] < -50
    ar1 = _row(res, (1, 0, 0))["params"]["ar.L1"]["value"]
    assert ar1 == pytest.approx(0.6, abs=0.08)


def test_the_constant_model_is_always_listed_as_the_reference_row():
    res = M.fit_arma_grid(SIM.arma(800, seed=2), max_p=1, max_q=1)
    const = _row(res, (0, 0, 0))
    assert const["is_constant"] is True and res["constant"]["order"] == [0, 0, 0]
    assert res["n_specs"] == 4 and [r["rank"] for r in res["rows"]] == [1, 2, 3, 4]
    assert res["rows"] == sorted(res["rows"], key=lambda r: r["bic"])


def test_white_noise_gives_no_winning_order_on_most_draws():
    verdicts = [M.fit_arma_grid(SIM.arma(1000, seed=50 + s), max_p=1, max_q=1)["verdict"] for s in range(10)]
    assert verdicts.count("no_better_than_constant") >= 9


def test_constant_model_leaves_autocorrelated_residuals_on_an_ar_series():
    res = M.fit_arma_grid(SIM.arma(1500, ar=(0.6,), seed=3), max_p=1, max_q=0)
    assert _row(res, (0, 0, 0))["diagnostics"]["ljung_box_p"] < 0.001
    assert _row(res, (1, 0, 0))["diagnostics"]["ljung_box_p"] > 0.01


def test_likelihood_ratio_p_values_are_corrected_for_the_number_of_specifications_tried():
    res = M.fit_arma_grid(SIM.arma(1000, seed=4), max_p=2, max_q=2)
    fam = [r for r in res["rows"] if not r["is_constant"]]
    assert len(fam) == 8
    assert all(r["lr_p_adj"] >= r["lr_p"] - 1e-12 for r in fam)
    assert res["fdr"]["n_tested"] == 8


def test_a_specification_that_fails_is_reported_not_dropped(monkeypatch):
    real = M._fit_arima

    def flaky(y, order, seasonal_order, exog, trend):
        if tuple(order) == (1, 0, 1):
            raise np.linalg.LinAlgError("matrice singulière")
        return real(y, order, seasonal_order, exog, trend)

    monkeypatch.setattr(M, "_fit_arima", flaky)
    res = M.fit_arma_grid(SIM.arma(600, ar=(0.5,), seed=5), max_p=1, max_q=1)
    bad = _row(res, (1, 0, 1))
    assert bad["converged"] is False and "singulière" in bad["error"]
    assert res["n_failed"] == 1 and res["n_specs"] == 4 and len(res["rows"]) == 4


def test_residual_summary_has_a_qq_plot_and_a_jarque_bera_test():
    res = M.fit_arma_grid(SIM.arma(800, ar=(0.4,), seed=6), max_p=1, max_q=0)
    diag = res["best"]["diagnostics"]
    assert len(diag["qq"]["theoretical"]) == len(diag["qq"]["sample"]) >= 20
    assert 0 <= diag["jarque_bera_p"] <= 1 and 0 <= diag["arch_lm_p"] <= 1


def test_integrated_series_is_modelled_with_a_difference_and_no_drift_term():
    res = M.fit_arma_grid(SIM.random_walk(800, seed=7), max_p=1, max_q=0, d=1)
    assert res["d"] == 1 and res["constant"]["order"] == [0, 1, 0]


def test_seasonal_term_is_preferred_on_a_seasonal_monthly_series():
    x = SIM.arma(360, ar=(0,) * 11 + (0.7,), seed=8)
    plain = M.fit_arma_grid(x, max_p=1, max_q=0)
    seasonal = M.fit_arma_grid(x, max_p=1, max_q=0, seasonal_order=(1, 0, 0, 12))
    assert seasonal["best"]["bic"] < plain["best"]["bic"] - 20


def test_exogenous_regressor_is_estimated_and_lowers_the_criterion():
    rng = np.random.default_rng(9)
    z = pd.Series(rng.normal(size=800), index=SIM.arma(800, seed=0).index, name="z")
    y = 0.8 * z + pd.Series(rng.normal(size=800), index=z.index)
    with_z = M.fit_arma_grid(y, max_p=0, max_q=0, exog=z.to_frame())
    without = M.fit_arma_grid(y, max_p=0, max_q=0)
    assert with_z["best"]["bic"] < without["best"]["bic"] - 100
    assert with_z["best"]["params"]["z"]["value"] == pytest.approx(0.8, abs=0.1)


def test_gph_estimates_the_fractional_order_of_a_long_memory_series():
    long_memory = SIM.arfima(4000, d=0.3, seed=10)
    noise = SIM.arma(4000, seed=11)
    d_lm, d_wn = M.gph_d(long_memory), M.gph_d(noise)
    assert d_lm["d"] == pytest.approx(0.3, abs=0.13) and d_lm["d"] - 2 * d_lm["se"] > 0
    assert abs(d_wn["d"]) < 2.5 * d_wn["se"]


def test_too_short_a_series_is_refused():
    with pytest.raises(ValueError, match="minimum"):
        M.fit_arma_grid(pd.Series(np.arange(15.0)), max_p=1, max_q=1)
