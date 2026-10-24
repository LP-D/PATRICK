"""Liens entre actifs de la page Exploration (corrélation croisée préblanchie, Granger robuste et conditionnel, ratio de variance,
corrélation partielle) : séries synthétiques à vérité connue. Un test échoue si l'étude rate le lien planté OU en invente un."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from patrick.exploration import studies as S

N = 1500


def _idx(n=N):
    return pd.bdate_range("2015-01-01", periods=n)


def _frame(**cols):
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=_idx(n))


@pytest.fixture
def rng():
    return np.random.default_rng(11)


def _ar1(rng, n, phi, sigma=1.0):
    e = rng.normal(0, sigma, n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x


# --------------------------------------------------------------------------- corrélation croisée


def test_prewhitening_removes_the_spurious_cross_correlation_of_two_persistent_independent_series(rng):
    df = _frame(A=_ar1(rng, N, 0.95), B=_ar1(rng, N, 0.95))
    raw = S.cross_correlation(df, "A", "B", 10, prewhiten=False)
    white = S.cross_correlation(df, "A", "B", 10, prewhiten=True)
    # deux marches presque aléatoires indépendantes « sont corrélées » à tous les décalages ; blanchies, elles ne le sont plus
    assert sum(raw["significant"]) >= 15
    assert sum(white["significant"]) == 0 and white["prewhitened"] is True and set(white["ar_orders"]) == {"A", "B"}


def test_the_lead_is_found_and_the_portmanteau_test_gives_the_direction(rng):
    b = rng.normal(size=N)
    a = np.roll(b, 3) + 0.5 * rng.normal(size=N)
    out = S.cross_correlation(_frame(A=a, B=b), "A", "B", 8)
    assert out["best_lag"] == 3 and out["best_value"] > 0.7
    assert out["b_leads_p"] < 1e-6 and out["a_leads_p"] > 0.05            # b mène a, pas l'inverse
    assert out["portmanteau_valid"] is True
    swapped = S.cross_correlation(_frame(A=b, B=a), "A", "B", 8)
    assert swapped["best_lag"] == -3 and swapped["a_leads_p"] < 1e-6 and swapped["b_leads_p"] > 0.05


def test_significance_survives_a_correction_over_all_the_lags(rng):
    df = _frame(A=rng.normal(size=N), B=rng.normal(size=N))
    out = S.cross_correlation(df, "A", "B", 20)
    assert len(out["lags"]) == 41 and len(out["p_adj"]) == 41
    # une bande à 5 % sur 41 décalages en laisse ~2 au hasard ; après Benjamini-Hochberg il n'en reste pas
    assert sum(out["significant"]) == 0
    assert all(q >= p for q, p in zip(out["p_adj"], out["p"], strict=True))


def test_volatility_leads_are_visible_on_absolute_returns_but_not_on_returns(rng):
    vol_b = np.exp(_ar1(rng, N, 0.9, 0.25))
    eb = rng.normal(size=N) * vol_b
    ea = rng.normal(size=N) * (0.5 * np.roll(vol_b, 2) + 0.2)             # la volatilité de a suit celle de b avec 2 périodes de retard
    df = _frame(A=ea, B=eb)
    assert sum(S.cross_correlation(df, "A", "B", 8)["significant"]) == 0   # rendements non corrélés
    vol = S.cross_correlation(df, "A", "B", 8, basis="abs")
    assert vol["basis"] == "abs" and any(s and k > 0 and v > 0 for k, s, v in zip(vol["lags"], vol["significant"], vol["values"], strict=True))


def test_differences_of_levels_need_the_levels_and_match_the_returns_for_a_difference_panel(rng):
    levels = _frame(A=rng.normal(size=N).cumsum() + 500, B=rng.normal(size=N).cumsum() + 500)
    returns = levels.diff().dropna()
    with pytest.raises(ValueError, match="niveaux"):
        S.cross_correlation(returns, "A", "B", basis="diff")
    by_diff = S.cross_correlation(returns, "A", "B", 5, basis="diff", levels=levels, prewhiten=False)
    by_returns = S.cross_correlation(returns, "A", "B", 5, basis="returns", prewhiten=False)
    assert np.allclose(by_diff["values"], by_returns["values"])


def test_spearman_resists_an_outlier_that_creates_a_pearson_link(rng):
    a, b = rng.normal(size=N), rng.normal(size=N)
    a[700] = b[700] = 40.0                                                 # une seule journée extrême commune
    df = _frame(A=a, B=b)
    pearson = S.cross_correlation(df, "A", "B", 3, prewhiten=False)
    spearman = S.cross_correlation(df, "A", "B", 3, prewhiten=False, method="spearman")
    assert pearson["contemporaneous"] > 0.5 and abs(spearman["contemporaneous"]) < 0.1


def test_cross_correlation_refuses_bad_input(rng):
    df = _frame(A=rng.normal(size=100), B=rng.normal(size=100))
    with pytest.raises(ValueError, match="différents"):
        S.cross_correlation(df, "A", "A")
    with pytest.raises(ValueError, match="série inconnue"):
        S.cross_correlation(df, "A", "B", basis="levels")
    with pytest.raises(ValueError, match="méthode inconnue"):
        S.cross_correlation(df, "A", "B", method="kendall")
    json.dumps(S.cross_correlation(df, "A", "B"), allow_nan=False)


# --------------------------------------------------------------------------- Granger


def _lead(rng, n=2000, coefs=(0.6,), noise=0.5):
    b = rng.normal(size=n)
    a = np.zeros(n)
    for t in range(len(coefs), n):
        a[t] = sum(c * b[t - 1 - i] for i, c in enumerate(coefs)) + rng.normal(0, noise)
    return _frame(A=a, B=b)


def test_granger_reports_the_effect_size_and_the_order_chosen_without_looking_at_the_cause(rng):
    out = S.granger(_lead(rng), "A", "B", maxlag=4)
    one = out["b_to_a"]
    assert one["predictive"] is True and one["order"] == 1 and out["order"] == 1
    # a = 0,6·b(t−1) + bruit(σ 0,5) : le passé de b explique 0,36/(0,36+0,25) ≈ 59 % de la variance de a
    assert one["gain_order"] == pytest.approx(0.59, abs=0.05)
    assert out["a_to_b"]["predictive"] is False and out["a_to_b"]["gain_order"] < 0.01


def test_granger_picks_a_two_lag_structure_by_bic(rng):
    out = S.granger(_lead(rng, coefs=(0.4, 0.3)), "A", "B", maxlag=5)
    assert out["order"] == 2 and out["b_to_a"]["predictive"] is True
    assert out["b_to_a"]["p_bonferroni"] < 0.05 and out["b_to_a"]["best_lag"] in (1, 2)


def test_granger_tests_volatility_spillover_with_absolute_returns(rng):
    n = 2500
    eb = rng.normal(size=n)
    ea = np.zeros(n)
    for t in range(1, n):
        ea[t] = rng.normal() * (0.3 + 0.5 * abs(eb[t - 1]))               # la VOLATILITÉ de a suit |b| de la veille, pas son signe
    df = _frame(A=ea, B=eb)
    assert S.granger(df, "A", "B", 3)["b_to_a"]["predictive"] is False     # rien dans les rendements eux-mêmes
    vol = S.granger(df, "A", "B", 3, on="abs")
    assert vol["on"] == "abs" and vol["b_to_a"]["predictive"] is True and vol["a_to_b"]["predictive"] is False


def test_the_robust_test_does_not_overreject_when_variance_changes_over_time():
    # a et b INDÉPENDANTES, tous deux à variance qui change (grappes) : le F classique rejette trop, le Wald robuste reste calibré
    n, hits_classic, hits_robust, runs = 800, 0, 0, 40
    for seed in range(runs):
        r = np.random.default_rng(500 + seed)
        a = r.normal(size=n) * np.exp(_ar1(r, n, 0.97, 0.25))
        b = r.normal(size=n) * np.exp(_ar1(r, n, 0.97, 0.25))
        res = S.granger_test(a, b, 2)
        hits_classic += res["p_classic"] < 0.05
        hits_robust += res["p_robust"] < 0.05
    assert hits_robust <= hits_classic and hits_robust <= 0.15 * runs


def test_granger_warns_about_non_stationary_inputs(rng):
    walk = _frame(A=np.random.default_rng(0).normal(size=N).cumsum(), B=rng.normal(size=N))
    assert S.granger(walk, "A", "B", 2)["nonstationary"] == ["A"]


def test_granger_refuses_bad_input(rng):
    df = _frame(A=rng.normal(size=200), B=rng.normal(size=200))
    with pytest.raises(ValueError, match="différents"):
        S.granger(df, "A", "A")
    with pytest.raises(ValueError, match="série inconnue"):
        S.granger(df, "A", "B", on="levels")


def _chain(rng, n=2000):
    a = rng.normal(size=n)
    b = np.zeros(n)
    c = np.zeros(n)
    for t in range(1, n):
        b[t] = 0.5 * a[t - 1] + rng.normal(0, 0.5)
        c[t] = 0.5 * b[t - 1] + rng.normal(0, 0.5)
    return _frame(A=a, B=b, C=c, D=rng.normal(size=n))


def test_the_conditional_matrix_keeps_direct_links_and_drops_the_indirect_one(rng):
    out = S.granger_matrix(_chain(rng), 3)
    pairs = {(e["cause"], e["effect"]) for e in out["edges"]}
    assert pairs == {("A", "B"), ("B", "C")}                              # A → C passe par B : écarté une fois B connu
    assert out["scope"] == "conditional" and out["n_tests"] == 12
    assert out["leaders"][0]["symbol"] == "A" and out["leaders"][0]["net"] == 1
    edge = out["edges"][0]
    assert 0.1 < edge["gain"] < 0.7 and edge["p_adj"] < 1e-6


def test_the_pairwise_matrix_also_shows_the_indirect_link(rng):
    out = S.granger_matrix(_chain(rng), 3, scope="pairwise")
    pairs = {(e["cause"], e["effect"]) for e in out["edges"]}
    assert {("A", "B"), ("B", "C")} <= pairs and ("A", "C") in pairs
    assert not any("D" in p for p in pairs)
    json.dumps(out, allow_nan=False)


def test_the_matrix_corrects_for_the_number_of_directions_tested(rng):
    df = _frame(**{f"X{i}": rng.normal(size=1000) for i in range(8)})
    out = S.granger_matrix(df, 2, scope="pairwise")
    assert out["n_tests"] == 56
    raw_hits = sum(1 for row in out["p_adj"] for q in row if q is not None and q < 0.05)
    assert raw_hits <= 1                                                   # 56 tests de bruit : au plus un faux positif après Benjamini-Hochberg


def test_the_matrix_limits_the_number_of_assets(rng):
    df = _frame(**{f"X{i}": rng.normal(size=300) for i in range(30)})
    with pytest.raises(ValueError, match="Au plus"):
        S.granger_matrix(df, 2)
    with pytest.raises(ValueError, match="deux actifs"):
        S.granger_matrix(df[["X0"]])
    with pytest.raises(ValueError, match="portée inconnue"):
        S.granger_matrix(df[["X0", "X1"]], scope="global")


# --------------------------------------------------------------------------- ratio de variance


@pytest.mark.parametrize("phi, verdict", [(0.0, "random_walk"), (0.3, "momentum"), (-0.3, "mean_reversion")])
def test_variance_ratio_separates_random_walk_momentum_and_mean_reversion(rng, phi, verdict):
    out = S.variance_ratio(pd.Series(_ar1(rng, N, phi), index=_idx()))
    assert out["verdict"] == verdict
    ratios = [r["vr"] for r in out["rows"]]
    if verdict == "momentum":
        assert all(v > 1.2 for v in ratios)
    elif verdict == "mean_reversion":
        assert all(v < 0.8 for v in ratios)
    else:
        assert all(0.8 < v < 1.25 for v in ratios) and out["joint_p"] > 0.05


def test_variance_ratio_horizons_are_limited_by_the_sample_and_the_output_is_clean(rng):
    out = S.variance_ratio(pd.Series(rng.normal(size=80), index=_idx(80)), horizons=(2, 4, 8, 16, 32))
    assert [r["q"] for r in out["rows"]] == [2, 4, 8, 16]                 # q ≤ n/5
    assert all(r["p_adj"] is not None for r in out["rows"])
    json.dumps(out, allow_nan=False)
    with pytest.raises(ValueError, match="minimum 60"):
        S.variance_ratio(pd.Series(rng.normal(size=30)))


# --------------------------------------------------------------------------- corrélation partielle


def test_partial_correlation_removes_the_link_through_a_common_factor(rng):
    c = rng.normal(size=N)
    df = _frame(A=c + rng.normal(size=N), B=c + rng.normal(size=N), C=c, E=rng.normal(size=N))
    out = S.partial_correlation(df)
    lab = out["labels"]
    m = np.array(out["matrix"], dtype=float)
    i, j, k = lab.index("A"), lab.index("B"), lab.index("C")
    assert df["A"].corr(df["B"]) > 0.4                                     # simple : A et B semblent liées...
    assert abs(m[i, j]) < 0.1 and m[i, k] > 0.4                            # ...partielle : leur lien passe par C
    assert out["method"] == "partial" and out["significant"][i][k] is True and out["significant"][i][j] is False
    assert out["n_tests"] == 6 and math.isfinite(out["condition_number"])
    json.dumps(out, allow_nan=False)


def test_partial_correlation_needs_three_assets_and_enough_observations(rng):
    with pytest.raises(ValueError, match="trois actifs"):
        S.partial_correlation(_frame(A=rng.normal(size=100), B=rng.normal(size=100)))
    wide = pd.DataFrame(rng.normal(size=(8, 10)), columns=list("ABCDEFGHIJ"))
    with pytest.raises(ValueError, match="Pas assez"):
        S.partial_correlation(wide)
