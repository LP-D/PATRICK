"""Économétrie multivariée : VAR (ordre au BIC, stabilité, IRF orthogonalisées, décomposition de la variance), cointégration de Johansen, VECM.

Processus simulés à paramètres connus : un VAR(1) triangulaire (y1 ne réagit pas à y2, y2 réagit à y1), une paire cointégrée y = 2x + bruit stationnaire."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.econometrics import multivariate as MV
from patrick.econometrics import simulate as SIM

A = np.array([[0.5, 0.0], [0.3, 0.4]])


def _var1(n=2500, seed=1):
    rng = np.random.default_rng(seed)
    y = np.zeros((n + 100, 2))
    for t in range(1, n + 100):
        y[t] = A @ y[t - 1] + rng.normal(0, [1.0, 0.8])
    idx = SIM.arma(n, seed=0).index
    return pd.DataFrame(y[100:], index=idx, columns=["x", "y"]) / 100.0


def _pair(n=1500, seed=2, cointegrated=True):
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, 1, n))
    noise = np.zeros(n)
    for t in range(1, n):
        noise[t] = 0.5 * noise[t - 1] + rng.normal(0, 1)
    y = (2.0 * x + noise) if cointegrated else np.cumsum(rng.normal(0, 1, n))
    idx = SIM.arma(n, seed=0).index
    return pd.DataFrame({"x": x + 100, "y": y + 100}, index=idx)


# ---------------------------------------------------------------- VAR
def test_var_selects_order_one_recovers_the_matrix_and_is_stable():
    res = MV.var_analysis(_var1(), maxlag=4)
    assert res["order"] == 1 and res["stable"] is True and res["max_root_modulus"] < 1
    coefs = np.array(res["coefficients"][0])                       # coefficients[k][i][j] : effet de la variable j au retard k+1 sur l'équation i
    np.testing.assert_allclose(coefs, A, atol=0.06)


def test_orthogonalized_irf_respects_the_ordering_and_the_triangular_structure():
    res = MV.var_analysis(_var1(), maxlag=2, irf_periods=8)
    irf = np.array(res["irf"])                                      # irf[h][i][j] : réponse de i à un choc sur j
    assert irf.shape == (9, 2, 2)
    assert irf[0][0][1] == pytest.approx(0.0, abs=1e-12)            # Cholesky : la 1re variable ne réagit pas à l'instant 0 au choc de la 2e
    assert irf[1][1][0] / irf[0][0][0] == pytest.approx(0.3, abs=0.06)       # y réagit à un choc sur x : 0,3 fois la taille du choc après une période (A21)
    assert abs(irf[1][0][1]) / irf[0][1][1] < 0.08                           # x ne réagit pas au choc sur y (A12 = 0)
    assert res["irf_order"] == ["x", "y"]
    lo, hi = np.array(res["irf_lower"]), np.array(res["irf_upper"])
    assert lo.shape == hi.shape == irf.shape and (lo <= hi).all()
    inside = ((lo <= irf) & (irf <= hi)).mean()                      # les bandes de simulation entourent presque toujours l estimation
    assert inside > 0.8 and (hi - lo).max() > 0                       # une bande a une largeur (régression : graine répétée => bande réduite à un point)


def test_variance_decomposition_sums_to_one_for_every_variable_and_horizon():
    res = MV.var_analysis(_var1(), maxlag=2, irf_periods=6)
    fevd = np.array(res["fevd"])                                    # fevd[h][i][j] : part de la variance de i due au choc j
    np.testing.assert_allclose(fevd.sum(axis=2), 1.0, atol=1e-8)
    assert fevd[-1][0][0] > 0.95 and fevd[-1][1][0] > 0.05          # x s'explique par lui-même ; y porte une part des chocs de x


def test_var_needs_at_least_two_series_and_enough_observations():
    with pytest.raises(ValueError, match="au moins 2"):
        MV.var_analysis(_var1()[["x"]])
    with pytest.raises(ValueError, match="minimum"):
        MV.var_analysis(_var1().iloc[:30])


# ---------------------------------------------------------------- Johansen
def test_johansen_finds_one_cointegrating_relation_in_a_cointegrated_pair():
    res = MV.johansen(_pair(), det_order=0, k_ar_diff=1)
    assert res["rank"] == 1
    assert res["rows"][0]["trace"] > res["rows"][0]["trace_crit_95"] and res["rows"][1]["trace"] < res["rows"][1]["trace_crit_95"]
    vec = res["vectors"][0]                                          # normalisé sur la première variable : (1, -2) à l'erreur près
    assert vec[0] == pytest.approx(1.0) and vec[1] == pytest.approx(-0.5, abs=0.1)     # y = 2x  <=>  x - 0,5 y = 0


def test_johansen_finds_no_relation_between_independent_random_walks_on_most_draws():
    ranks = [MV.johansen(_pair(seed=100 + s, cointegrated=False))["rank"] for s in range(10)]
    assert ranks.count(0) >= 7


# ---------------------------------------------------------------- VECM
def test_vecm_error_correction_pulls_the_dependent_series_back_toward_the_long_run_relation():
    res = MV.vecm(_pair(), rank=1, k_ar_diff=1)
    # vitesse de retour de l'écart à la relation de long terme : beta' alpha (négatif = l'écart se résorbe) ; ici ~ -0,58, demi-vie < 1 période
    assert res["rank"] == 1 and len(res["ect"]["values"]) > 1000
    assert -1.0 < res["speed"] < -0.2
    assert res["half_life"] is not None and 0 < res["half_life"] < 15
    assert np.array(res["alpha"]).shape == (2, 1) and np.array(res["beta"]).shape == (2, 1)


def test_vecm_refuses_a_rank_that_is_not_smaller_than_the_number_of_series():
    with pytest.raises(ValueError, match="rang"):
        MV.vecm(_pair(), rank=2, k_ar_diff=1)
