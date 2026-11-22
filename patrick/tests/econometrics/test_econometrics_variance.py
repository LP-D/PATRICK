"""Économétrie d'une série, partie 3 : variance conditionnelle (ARCH, GARCH, GJR, EGARCH, APARCH, FIGARCH, IGARCH/EWMA, HAR-RV).

On simule un processus dont on connaît les paramètres, on l'ajuste et on vérifie qu'on les retrouve ; on vérifie aussi que les tests de
signe d'Engle-Ng détectent un effet de levier que le modèle symétrique rate, et que les non-convergences sont affichées."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.econometrics import simulate as SIM
from patrick.econometrics import variance_models as V


def _pct(x: pd.Series) -> pd.Series:
    """Les simulations sont en pourcent ; les fonctions publiques prennent des rendements décimaux."""
    return x / 100.0


# ---------------------------------------------------------------- GARCH
def test_garch_fit_recovers_the_simulated_parameters():
    x = _pct(SIM.garch11(4000, 0.05, 0.10, 0.85, seed=1))
    fit = V.fit_variance_model(x, "garch", "normal")
    p = fit["params"]
    assert fit["converged"] is True
    assert p["alpha[1]"]["value"] == pytest.approx(0.10, abs=0.04)
    assert p["beta[1]"]["value"] == pytest.approx(0.85, abs=0.06)
    assert fit["persistence"] == pytest.approx(0.95, abs=0.04)
    assert fit["half_life"] == pytest.approx(np.log(0.5) / np.log(fit["persistence"]))


def test_standardized_residuals_of_the_right_model_show_no_remaining_arch():
    fit = V.fit_variance_model(_pct(SIM.garch11(4000, 0.05, 0.10, 0.85, seed=2)), "garch", "normal")
    d = fit["diagnostics"]
    assert d["ljung_box_squared_p"] > 0.01 and d["arch_lm_p"] > 0.01


def test_conditional_volatility_is_annualized_percent_and_covers_every_date():
    x = _pct(SIM.garch11(1500, 0.05, 0.10, 0.85, seed=3))
    fit = V.fit_variance_model(x, "garch", "normal", periods_per_year=252)
    cv = fit["conditional_vol"]
    assert len(cv["dates"]) == len(cv["values"]) == len(x)
    # volatilité inconditionnelle théorique : sqrt(0,05/0,05) = 1 % par jour -> ~15,9 % annualisés
    assert np.mean(cv["values"]) == pytest.approx(15.9, rel=0.2)


def test_small_decimal_returns_do_not_break_the_optimizer():
    fit = V.fit_variance_model(_pct(SIM.garch11(3000, 0.05, 0.10, 0.85, seed=4)) * 0.2, "garch", "normal")
    assert fit["converged"] is True and fit["persistence"] == pytest.approx(0.95, abs=0.05)


# ---------------------------------------------------------------- asymétrie
def test_gjr_detects_leverage_that_symmetric_garch_misses():
    x = _pct(SIM.garch11(5000, 0.05, 0.03, 0.88, gamma=0.12, seed=5))
    gjr = V.fit_variance_model(x, "gjr", "normal")
    garch = V.fit_variance_model(x, "garch", "normal")
    assert gjr["params"]["gamma[1]"]["value"] == pytest.approx(0.12, abs=0.06) and gjr["params"]["gamma[1]"]["p"] < 0.01
    assert gjr["bic"] < garch["bic"] - 5
    assert garch["engle_ng"]["joint"]["pvalue"] < 0.05                    # le test de signe voit ce que GARCH rate
    assert gjr["engle_ng"]["joint"]["pvalue"] > 0.01


def test_engle_ng_has_the_three_single_tests_and_the_joint_test():
    z = np.random.default_rng(6).standard_normal(2000)
    en = V.engle_ng(z)
    assert set(en) == {"sign_bias", "negative_size_bias", "positive_size_bias", "joint"}
    assert en["joint"]["pvalue"] > 0.01 and all("pvalue" in v for v in en.values())


def test_news_impact_curve_is_asymmetric_for_gjr_and_symmetric_for_garch():
    x = _pct(SIM.garch11(5000, 0.05, 0.03, 0.88, gamma=0.12, seed=5))
    gjr = V.fit_variance_model(x, "gjr", "normal")["news_impact"]
    garch = V.fit_variance_model(x, "garch", "normal")["news_impact"]
    mid = len(gjr["shock"]) // 2
    assert gjr["shock"][mid] == pytest.approx(0.0)
    assert gjr["variance"][0] > gjr["variance"][-1] * 1.2                 # un choc négatif fait plus monter la variance qu'un positif
    assert garch["variance"][0] == pytest.approx(garch["variance"][-1], rel=1e-6)
    assert min(gjr["variance"]) == pytest.approx(gjr["variance"][mid])


# ---------------------------------------------------------------- lois
def test_student_innovations_beat_normal_on_fat_tailed_data_and_recover_nu():
    x = _pct(SIM.garch11(5000, 0.05, 0.08, 0.88, seed=7, dist="t5"))
    normal = V.fit_variance_model(x, "garch", "normal")
    student = V.fit_variance_model(x, "garch", "t")
    assert student["bic"] < normal["bic"] - 20
    assert student["params"]["nu"]["value"] == pytest.approx(5.0, abs=2.0)


# ---------------------------------------------------------------- autres modèles
@pytest.mark.parametrize("model", ["arch", "egarch", "aparch", "figarch", "igarch"])
def test_every_model_of_the_family_fits_and_reports_its_state(model):
    fit = V.fit_variance_model(_pct(SIM.garch11(2500, 0.05, 0.10, 0.85, seed=8)), model, "normal")
    assert fit["model"] == model and isinstance(fit["converged"], bool)
    assert len(fit["conditional_vol"]["values"]) == 2500 and np.isfinite(fit["loglik"])


def test_igarch_is_integrated_by_construction():
    fit = V.fit_variance_model(_pct(SIM.garch11(2500, 0.05, 0.10, 0.85, seed=9)), "igarch", "normal")
    assert fit["persistence"] == 1.0 and fit["half_life"] is None and 0 < fit["params"]["lam"]["value"] < 1


def test_unknown_model_or_distribution_is_refused():
    x = _pct(SIM.garch11(500, 0.05, 0.1, 0.85, seed=1))
    with pytest.raises(ValueError, match="inconnu"):
        V.fit_variance_model(x, "garchm", "normal")
    with pytest.raises(ValueError, match="inconnue"):
        V.fit_variance_model(x, "garch", "laplace")


# ---------------------------------------------------------------- convergence affichée
def test_a_model_that_cannot_converge_says_so():
    fit = V.fit_variance_model(_pct(SIM.garch11(2000, 0.05, 0.10, 0.85, seed=10)), "garch", "normal", maxiter=1)
    assert fit["converged"] is False and fit["message"]


def test_grid_is_sorted_by_bic_lists_every_combination_and_reports_failures(monkeypatch):
    real = V._fit_one

    def flaky(y, model, dist, mean, maxiter):
        if (model, dist) == ("egarch", "ged"):
            raise RuntimeError("Hessienne non inversible")
        return real(y, model, dist, mean, maxiter)

    monkeypatch.setattr(V, "_fit_one", flaky)
    x = _pct(SIM.garch11(1500, 0.05, 0.10, 0.85, seed=11))
    grid = V.fit_variance_grid(x, models=("garch", "gjr", "egarch"), dists=("normal", "t", "ged"))
    assert grid["n_specs"] == 9 and len(grid["rows"]) == 9
    ok = [r for r in grid["rows"] if r["bic"] is not None]
    assert [r["bic"] for r in ok] == sorted(r["bic"] for r in ok)
    bad = next(r for r in grid["rows"] if (r["model"], r["dist"]) == ("egarch", "ged"))
    assert bad["converged"] is False and "Hessienne" in bad["error"] and grid["n_failed"] == 1
    assert grid["best"]["bic"] == ok[0]["bic"]


# ---------------------------------------------------------------- HAR-RV
def test_har_recovers_the_daily_weekly_monthly_coefficients():
    rng = np.random.default_rng(12)
    n, bd, bw, bm, c = 6000, 0.2, 0.3, 0.4, 0.1
    rv = np.full(n, c / (1 - bd - bw - bm))
    for t in range(22, n):
        rv[t] = c + bd * rv[t - 1] + bw * rv[t - 5:t].mean() + bm * rv[t - 22:t].mean() + rng.normal(0, 0.05)
    har = V.fit_har(pd.Series(rv[22:], index=SIM.arma(n - 22, seed=0).index))
    b = har["params"]
    assert b["daily"]["value"] == pytest.approx(bd, abs=0.07)
    assert b["weekly"]["value"] == pytest.approx(bw, abs=0.1)
    assert b["monthly"]["value"] == pytest.approx(bm, abs=0.1)
    assert har["persistence"] == pytest.approx(bd + bw + bm, abs=0.05)         # somme des trois coefficients = persistance de la variance
    assert 0.2 < har["r2"] < 0.6 and har["n_obs"] > 5000                       # bruit de 0,05 sur une série de persistance 0,9 : R2 modéré, pas 1


def test_har_regressors_use_only_the_past():
    s = pd.Series(np.abs(np.random.default_rng(13).normal(size=300)) + 0.1, index=SIM.arma(300, seed=0).index)
    a = V.fit_har(s)["fitted"]["values"]
    s2 = s.copy()
    s2.iloc[-1] = 1000.0                                                   # la dernière valeur change : les ajustements antérieurs ne bougent pas
    b = V.fit_har(s2)["fitted"]["values"]
    # l'échantillon d'estimation change (donc les coefficients), mais la régression est causale : la dernière valeur n'est jamais un régresseur de sa propre date
    assert len(a) == len(b)
    X, y = V._har_design(s2)
    assert y.index[-1] == s2.index[-1] and X.index[-1] == s2.index[-1]
    assert X.iloc[-1]["daily"] == pytest.approx(s2.iloc[-2])
