"""Valeurs exactes de `dsr` et `diebold_mariano` contre une réimplémentation indépendante, écrite d'après les articles.

Tests de mutation du 20/10 : dsr 113 mutants tués sur 211, diebold_mariano 164 sur 233 -- les moins protégés des modules statistiques.
Les tests existants vérifiaient surtout des sens (« plus de essais, plus sévère ») : un opérateur ou une constante modifiés passaient.
Ici chaque sortie est comparée, à 1e-9 près, à un calcul refait de zéro (formules de Bailey et López de Prado 2012 / 2014, de Diebold et
Mariano 1995 avec la correction de Harvey, Leybourne et Newbold 1997), sur des entrées variées et aux frontières.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from patrick.validation import diebold_mariano as dm_mod
from patrick.validation import dsr as dsr_mod

GAMMA = 0.5772156649015329


# ------------------------------------------------------------------------------------------------ Sharpe déflaté

def _ref_se(n, skew, kurt, sr):
    return math.sqrt(max((1 - skew * sr + (kurt - 1) / 4 * sr * sr) / max(n - 1, 1), 0.0))


def _ref_emax(n_trials, sd):
    if n_trials <= 1 or sd <= 0:
        return 0.0
    return sd * ((1 - GAMMA) * stats.norm.ppf(1 - 1 / n_trials) + GAMMA * stats.norm.ppf(1 - 1 / (n_trials * math.e)))


@pytest.mark.parametrize(("n", "skew", "kurt", "sr"), [(101, 0.0, 3.0, 0.0), (101, 0.5, 5.0, 0.2), (2, -1.0, 9.0, 0.7),
                                                       (1, 0.0, 3.0, 0.1), (500, 2.0, 12.0, -0.3)])
def test_sharpe_standard_error_matches_the_formula(n, skew, kurt, sr):
    assert dsr_mod._sharpe_std_error(n, skew, kurt, sr) == pytest.approx(_ref_se(n, skew, kurt, sr), abs=1e-12)


def test_sharpe_standard_error_under_normality_is_one_over_root_n_minus_one():
    assert dsr_mod._sharpe_std_error(101, 0.0, 3.0, 0.0) == pytest.approx(0.1, abs=1e-12)


@pytest.mark.parametrize(("n_trials", "sd"), [(2, 1.0), (10, 1.0), (10, 0.25), (1000, 0.07), (1, 1.0), (10, 0.0), (10, -1.0)])
def test_expected_max_sharpe_matches_the_formula(n_trials, sd):
    assert dsr_mod.expected_max_sharpe(n_trials, sd) == pytest.approx(_ref_emax(n_trials, sd), abs=1e-12)


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("n_trials", [1, 7, 120])
def test_deflated_sharpe_matches_a_reference_computation(seed, n_trials):
    rng = np.random.default_rng(seed)
    r = rng.standard_t(df=4, size=60 + 40 * seed) * 0.01 + 0.0005 * (seed - 2)
    out = dsr_mod.deflated_sharpe_ratio(r, n_trials, periods_per_year=252)
    std = r.std(ddof=1)
    sr = r.mean() / std
    skew, kurt = stats.skew(r), stats.kurtosis(r, fisher=False)
    se = _ref_se(len(r), skew, kurt, sr)
    sr0 = _ref_emax(max(n_trials, 1), se)
    dsr = stats.norm.cdf((sr - sr0) / se)
    assert out["sr"] == round(sr, 4) and out["sr_annualized"] == round(sr * math.sqrt(252), 4)
    assert out["skew"] == round(skew, 4) and out["kurtosis"] == round(kurt, 4)
    assert out["benchmark_sr"] == round(sr0, 6) and out["dsr"] == round(dsr, 4) and out["p_value"] == round(1 - dsr, 6)
    assert (out["n_obs"], out["n_trials"]) == (len(r), n_trials)


def test_an_explicit_benchmark_replaces_the_expected_maximum():
    r = np.random.default_rng(3).normal(0.001, 0.01, 250)
    out = dsr_mod.deflated_sharpe_ratio(r, 50, benchmark_sr=0.0)
    se = _ref_se(250, stats.skew(r), stats.kurtosis(r, fisher=False), r.mean() / r.std(ddof=1))
    assert out["benchmark_sr"] == 0.0 and out["dsr"] == round(stats.norm.cdf((r.mean() / r.std(ddof=1)) / se), 4)


def test_the_annualisation_uses_the_given_periods():
    r = np.random.default_rng(4).normal(0.001, 0.01, 100)
    assert dsr_mod.deflated_sharpe_ratio(r, 1, periods_per_year=52)["sr_annualized"] == round(r.mean() / r.std(ddof=1) * math.sqrt(52), 4)


def test_nan_returns_are_dropped_and_under_twenty_observations_nothing_is_computed():
    r = np.r_[np.random.default_rng(5).normal(0, 0.01, 19), [np.nan] * 5]
    out = dsr_mod.deflated_sharpe_ratio(r, 3)
    assert out["n_obs"] == 19 and out["n_trials"] == 3
    assert all(math.isnan(out[k]) for k in ("sr", "sr_annualized", "dsr", "p_value", "skew", "kurtosis", "benchmark_sr"))
    assert dsr_mod.deflated_sharpe_ratio(np.r_[r[:19], [0.002]], 3)["n_obs"] == 20


# ------------------------------------------------------------------------------------------------ Diebold-Mariano

def _ref_dm(d, h):
    n = len(d)
    c = d - d.mean()
    gam = [c @ c / n] + [c[k:] @ c[:-k] / n for k in range(1, h) if k < n]
    var = gam[0] + 2 * sum(gam[1:])
    kernel = "rectangular"
    if not var > 0:
        L = len(gam)
        var = gam[0] + 2 * sum((1 - k / L) * gam[k] for k in range(1, L))
        kernel = "bartlett"
    stat = d.mean() / math.sqrt(var / n)
    hln = math.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 0.0))
    star = stat * hln
    return round(star, 4), round(2 * stats.t.sf(abs(star), df=n - 1), 4), kernel


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("h", [1, 2, 5, 10])
def test_dm_matches_a_reference_computation(seed, h):
    rng = np.random.default_rng(100 + seed)
    n = 15 * h + 37 * seed + 3
    base = rng.normal(0, 1, n + h)
    d = np.convolve(base, np.ones(h) / h, mode="valid")[:n] + 0.05 * (seed - 2)   # différentiel autocorrélé sur h-1 retards
    a, b = d + 1.0, np.ones(n)
    out = dm_mod.diebold_mariano(a, b, h=h)
    stat, p, kernel = _ref_dm(d, h)
    assert (out["dm_stat"], out["p_value"], out["variance_kernel"]) == (stat, p, kernel)
    assert out["mean_loss_diff"] == round(float(d.mean()), 6) and out["n_obs"] == n and out["correction"] == "HLN"


def test_dm_falls_back_to_bartlett_weights_when_the_rectangular_variance_is_not_positive():
    d = np.tile([1.0, -1.0], 40) + 0.01               # autocorrélation ≈ -1 au retard 1 : à h = 2 la somme rectangulaire est négative
    out = dm_mod.diebold_mariano(d + 2.0, np.full(len(d), 2.0), h=2)
    stat, p, kernel = _ref_dm(d, 2)
    assert kernel == "bartlett" and (out["dm_stat"], out["p_value"], out["variance_kernel"]) == (stat, p, kernel)


def test_dm_boundaries_on_the_sample_size():
    rng = np.random.default_rng(7)
    assert dm_mod.diebold_mariano(rng.normal(size=9), rng.normal(size=9))["untestable_reason"] == "too_few_observations"
    assert "untestable_reason" not in dm_mod.diebold_mariano(rng.normal(size=10), rng.normal(size=10))
    h = 4
    short = dm_mod.diebold_mariano(rng.normal(size=15 * h - 1), rng.normal(size=15 * h - 1), h=h)
    exact = dm_mod.diebold_mariano(rng.normal(size=15 * h), rng.normal(size=15 * h), h=h)
    assert short["untestable_reason"] == "horizon_too_long" and "untestable_reason" not in exact
    assert math.isnan(short["dm_stat"]) and math.isnan(short["p_value"]) and short["variance_kernel"] is None


def test_dm_constant_differentials():
    zero = dm_mod.diebold_mariano(np.ones(20), np.ones(20))
    assert (zero["dm_stat"], zero["p_value"]) == (0.0, 1.0)
    worse = dm_mod.diebold_mariano(np.full(20, 2.0), np.ones(20))
    better = dm_mod.diebold_mariano(np.ones(20), np.full(20, 2.0))
    assert worse["dm_stat"] == math.inf and better["dm_stat"] == -math.inf and worse["p_value"] == better["p_value"] == 0.0
    assert worse["mean_loss_diff"] == 1.0 and better["mean_loss_diff"] == -1.0


def test_a_negative_statistic_means_the_candidate_is_better():
    rng = np.random.default_rng(8)
    base = rng.normal(1.0, 0.3, 300)
    out = dm_mod.diebold_mariano(base - 0.2, base + rng.normal(0, 0.05, 300))
    assert out["dm_stat"] < 0 and out["p_value"] < 0.01


@pytest.mark.parametrize(("p", "stat", "expected"), [(0.08, -1.7, 0.04), (0.08, 1.7, 0.96), (0.08, 0.0, 0.96), (1.0, -0.1, 0.5),
                                                     (None, -1.0, None), (float("nan"), -1.0, None), (0.08, None, 0.96),
                                                     (0.08, float("nan"), 0.96)])
def test_one_sided_better_p(p, stat, expected):
    out = dm_mod.one_sided_better_p(p, stat)
    assert out == (None if expected is None else pytest.approx(expected))
