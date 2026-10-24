"""Dépendance non linéaire (`patrick/exploration/dependence.py`) : chaque mesure est testée sur des séries synthétiques dont on connaît la
vérité (lien en U, lien décalé, indépendance, grappes de volatilité) et contre un calcul de référence écrit à la main pour les briques
numériques (U-centrage, produit de FFT des décalages circulaires, estimateur de l'information mutuelle)."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from patrick.exploration import dependence as D

N = 1200


def _idx(n=N):
    return pd.bdate_range("2016-01-01", periods=n)


def _frame(**cols):
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=_idx(n))


@pytest.fixture
def rng():
    return np.random.default_rng(21)


# --------------------------------------------------------------------------- briques numériques


def _ucenter_by_definition(v):
    n = len(v)
    d = np.abs(v[:, None] - v[None, :])
    out = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                out[i, j] = d[i, j] - d[i, :].sum() / (n - 2) - d[:, j].sum() / (n - 2) + d.sum() / ((n - 1) * (n - 2))
    return out


def test_u_centering_matches_its_definition_and_row_sums_are_exact(rng):
    x = rng.normal(size=40)
    assert np.allclose(D.ucenter(x), _ucenter_by_definition(x))
    assert np.allclose(D._row_sums_abs(x), np.abs(x[:, None] - x[None, :]).sum(axis=1))


def test_the_blockwise_gram_equals_the_pairwise_distance_covariance(rng):
    n = 300
    x = np.column_stack([rng.normal(size=n), rng.normal(size=n), rng.standard_t(3, size=n)])
    x[:, 1] += x[:, 0] ** 2
    gram = D._dcov_gram(x, block=64)
    for i, j in ((0, 1), (0, 2), (1, 2), (2, 2)):
        direct = np.vdot(D.ucenter(x[:, i]), D.ucenter(x[:, j])) / (n * (n - 3))
        assert gram[i, j] == pytest.approx(direct, rel=1e-9)


def test_the_fft_null_equals_explicit_circular_shifts(rng):
    n = 90
    x, y = rng.normal(size=n), rng.normal(size=n)
    a, b = D.ucenter(x), D.ucenter(y)
    null = D._circular_dcor_null(a, b, smin=10)
    scale = math.sqrt(np.vdot(a, a) * np.vdot(b, b))
    for s in (10, 23, 61, n - 10):
        shifted = np.roll(np.roll(b, -s, axis=0), -s, axis=1)
        assert null[s - 10] == pytest.approx(float(np.vdot(a, shifted)) / scale, rel=1e-9, abs=1e-12)


def test_the_neighbour_estimator_recovers_the_information_of_a_gaussian_pair(rng):
    for rho in (0.3, 0.6, 0.9):
        n = 2000
        x = rng.normal(size=n)
        y = rho * x + math.sqrt(1 - rho**2) * rng.normal(size=n)
        truth = -0.5 * math.log(1 - rho**2)
        mi = D.ksg_mutual_information(D.normal_scores(x), D.normal_scores(y))
        assert mi == pytest.approx(truth, abs=0.04)
        if rho >= 0.6:                                                     # à faible lien, le bruit d'estimation domine l'échelle de Linfoot
            assert D.linfoot(mi) == pytest.approx(rho, abs=0.05)           # l'échelle de Linfoot se lit comme une corrélation


def test_mutual_information_is_blind_to_a_monotone_transformation(rng):
    x = rng.normal(size=800)
    y = 0.7 * x + rng.normal(size=800)
    base = D.ksg_mutual_information(D.normal_scores(x), D.normal_scores(y))
    warped = D.ksg_mutual_information(D.normal_scores(np.exp(2 * x)), D.normal_scores(y**3))
    assert warped == pytest.approx(base, abs=1e-9)


def test_distance_correlation_is_unbiased_under_independence(rng):
    # sans correction du biais, la corrélation de distance de deux séries indépendantes de 40 points vaut ~0,3 : ici elle est centrée sur 0
    vals = []
    for _ in range(60):
        x, y = rng.normal(size=40), rng.normal(size=40)
        vals.append(D._r_star(D.ucenter(x), D.ucenter(y), 40))
    assert abs(np.mean(vals)) < 0.03


# --------------------------------------------------------------------------- matrice


def _u_shape(rng, n=N):
    x = rng.normal(size=n)
    y = x**2 + 0.3 * rng.normal(size=n)                      # Pearson ≈ 0, lien fort
    z = rng.normal(size=n)
    return _frame(X=x, Y=y, Z=z)


@pytest.mark.parametrize("measure", ["dcor", "mi"])
def test_the_matrix_finds_a_u_shaped_link_that_pearson_misses(rng, measure):
    out = D.dependence_matrix(_u_shape(rng), measure)
    lab = out["labels"]
    i, j, k = lab.index("X"), lab.index("Y"), lab.index("Z")
    assert abs(out["pearson"][i][j]) < 0.1
    assert out["matrix"][i][j] > 0.4 and out["significant"][i][j] is True
    assert out["matrix"][i][k] < 0.15 and out["significant"][i][k] is False
    hidden = [(r["a"], r["b"]) for r in out["hidden"]]
    assert hidden and set(hidden[0]) == {"X", "Y"} and out["hidden"][0]["gap"] > 0.3
    assert out["measure"] == measure and out["n_obs"] == N and out["n_used"] == N and out["windowed"] is False


@pytest.mark.parametrize("measure", ["dcor", "mi"])
def test_independent_series_stay_below_the_noise_floor(rng, measure):
    df = _frame(**{c: rng.normal(size=N) for c in "ABCDE"})
    out = D.dependence_matrix(df, measure)
    assert out["n_tests"] == 10
    assert all(v is not True for row in out["significant"] for v in row)
    assert out["mean_dependence"] < 0.12


def test_the_matrix_uses_only_the_most_recent_observations(rng):
    n = D.MATRIX_MAX_OBS + 300
    out = D.dependence_matrix(_frame(A=rng.normal(size=n), B=rng.normal(size=n)), "dcor")
    assert out["n_obs"] == n and out["n_used"] == D.MATRIX_MAX_OBS and out["windowed"] is True


def test_the_matrix_is_symmetric_with_a_unit_diagonal_and_json_clean(rng):
    out = D.dependence_matrix(_u_shape(rng), "dcor")
    m = np.array(out["matrix"], dtype=float)
    assert np.allclose(m, m.T) and np.allclose(np.diag(m), 1.0)
    json.dumps(out, allow_nan=False)


def test_the_matrix_needs_two_assets_and_a_known_measure(rng):
    with pytest.raises(ValueError, match="deux actifs"):
        D.dependence_matrix(_frame(A=rng.normal(size=100)), "dcor")
    with pytest.raises(ValueError, match="mesure inconnue"):
        D.dependence_matrix(_frame(A=rng.normal(size=100), B=rng.normal(size=100)), "cosine")


# --------------------------------------------------------------------------- un couple, décalage par décalage


def _lagged_square(rng, n=N, lag=2):
    y = rng.normal(size=n)
    x = np.zeros(n)
    x[lag:] = y[:-lag] ** 2 + 0.4 * rng.normal(size=n - lag)           # x(t) dépend de y(t−2) sans corrélation linéaire
    x[:lag] = rng.normal(size=lag)
    return _frame(X=x, Y=y)


@pytest.mark.parametrize("measure", ["dcor", "mi"])
def test_the_pair_view_finds_the_lag_of_a_nonlinear_lead(rng, measure):
    out = D.dependence_pair(_lagged_square(rng), "X", "Y", measure, maxlag=5)
    assert out["best_lag"] == 2 and out["best_significant"] is True
    assert out["contemporaneous_significant"] is False
    assert out["values"][out["lags"].index(2)] > 3 * out["band"] * 0.5
    assert max(out["pearson_abs"]) < 0.12                              # la corrélation linéaire ne voit rien, à aucun décalage
    assert out["null_draws"] >= 200 and out["lags"] == list(range(-5, 6))


def test_the_pair_view_flags_a_same_day_link_that_pearson_cannot_see(rng):
    out = D.dependence_pair(_u_shape(rng), "X", "Y", "dcor", maxlag=3)
    assert out["contemporaneous_significant"] is True and out["pearson_p"] > 0.05
    assert out["nonlinear_only"] is True


def test_circular_shifts_keep_volatility_clustering_so_independent_garch_pairs_are_not_flagged():
    # deux séries INDÉPENDANTES mais à grappes de volatilité : un test iid y verrait un lien (les deux ont de longues périodes calmes /
    # agitées) ; la loi nulle par décalages circulaires garde ces grappes et reste calibrée
    flagged = 0
    for seed in range(8):
        r = np.random.default_rng(100 + seed)
        n = 900

        def garch(r=r, n=n):
            vol = np.empty(n)
            out = np.empty(n)
            v = 1.0
            for t in range(n):
                out[t] = math.sqrt(v) * r.normal()
                v = 0.05 + 0.1 * out[t] ** 2 + 0.85 * v
                vol[t] = v
            return out

        pair = D.dependence_pair(_frame(A=garch(), B=garch()), "A", "B", "dcor", maxlag=3)
        flagged += bool(pair["contemporaneous_significant"])
    assert flagged <= 2                                                # 5 % attendu sur 8 séries : 0 ou 1 ; 2 de marge


@pytest.mark.parametrize("measure", ["dcor", "mi"])
def test_a_very_strong_link_is_significant_even_among_many_lags(rng, measure):
    # le plus petit p d'un test par permutations (1 / tirages) ne doit pas empêcher Benjamini-Hochberg de rejeter parmi 21 décalages
    x = rng.normal(size=700)
    y = 0.85 * x + 0.5 * rng.normal(size=700)
    out = D.dependence_pair(_frame(X=x, Y=y), "X", "Y", measure, maxlag=10)
    assert out["contemporaneous_significant"] is True and out["contemporaneous_p"] <= 1.0 / (1 + out["null_draws"])
    assert out["pearson_p"] < 1e-10 and out["nonlinear_only"] is False


def test_the_permutation_p_extrapolates_past_the_last_simulated_draw():
    null = np.random.default_rng(0).normal(size=400)
    assert D._perm_p(0.0, null) == pytest.approx(0.5, abs=0.1)              # au milieu du nul : fréquence empirique
    assert D._perm_p(10.0, null) < 1.0 / 401 * 1e-3                         # très loin : extrapolé, pas plafonné au plancher
    assert D._perm_p(float("nan"), null) != D._perm_p(float("nan"), null)   # NaN reste NaN


def test_the_pair_view_reports_its_window_and_refuses_bad_input(rng):
    n = D.PAIR_MAX_OBS + 100
    out = D.dependence_pair(_frame(A=rng.normal(size=n), B=rng.normal(size=n)), "A", "B", "mi", maxlag=2)
    assert out["n_used"] == D.PAIR_MAX_OBS and out["windowed"] is True and out["n_obs"] == n
    json.dumps(out, allow_nan=False)
    df = _frame(A=rng.normal(size=100), B=rng.normal(size=100))
    with pytest.raises(ValueError, match="différents"):
        D.dependence_pair(df, "A", "A")
    with pytest.raises(ValueError, match="mesure inconnue"):
        D.dependence_pair(df, "A", "B", "cosine")
    with pytest.raises(ValueError, match="minimum 60"):
        D.dependence_pair(df.iloc[:30], "A", "B")
