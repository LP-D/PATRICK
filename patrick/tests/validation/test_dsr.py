"""Sharpe déflaté (Phase 2.3) — patrick.validation.dsr."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation.dsr import deflated_sharpe_ratio, expected_max_sharpe


def test_deflated_sharpe_penalizes_more_trials():
    """Le même Sharpe observé doit être jugé moins significatif (p-value plus
    grande) quand il a été choisi parmi plus d'essais — c'est tout le point du
    DSR : corriger le biais de sélection."""
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, 500)  # petit Sharpe positif, bruité

    few = deflated_sharpe_ratio(returns, n_trials=1)
    many = deflated_sharpe_ratio(returns, n_trials=1000)

    assert few["sr"] == many["sr"]  # même série -> même Sharpe brut
    assert many["p_value"] > few["p_value"]
    assert many["dsr"] < few["dsr"]


def test_deflated_sharpe_strong_signal_survives_many_trials():
    """Un Sharpe annualisé très élevé et stable doit rester significatif même
    après correction pour un grand nombre d'essais — sinon la métrique serait
    inutilisable en pratique."""
    rng = np.random.default_rng(1)
    returns = rng.normal(0.01, 0.01, 500)  # Sharpe journalier ~1, très fort
    out = deflated_sharpe_ratio(returns, n_trials=200)
    assert out["p_value"] < 0.01


def test_deflated_sharpe_too_few_observations_returns_nan():
    out = deflated_sharpe_ratio(np.array([0.01, -0.02, 0.03]), n_trials=10)
    assert np.isnan(out["dsr"])
    assert np.isnan(out["p_value"])
    assert out["n_obs"] == 3


def test_expected_max_sharpe_increases_with_n_trials():
    sr_std = 0.1
    e1 = expected_max_sharpe(1, sr_std)
    e100 = expected_max_sharpe(100, sr_std)
    e10000 = expected_max_sharpe(10000, sr_std)
    assert e1 <= e100 < e10000


def test_expected_max_sharpe_zero_for_single_trial():
    assert expected_max_sharpe(1, 0.2) == 0.0


# --- Valeurs exactes (survivants de mutation, 2026-11-02) : références recalculées ici à partir de la formule du papier -----------

def _returns(n: int = 400, seed: int = 0, mu: float = 0.0008, sd: float = 0.01) -> np.ndarray:
    return np.random.default_rng(seed).standard_t(6, n) * sd + mu


def _reference_dsr(r: np.ndarray, n_trials: int, benchmark_sr: float | None = None) -> dict:
    from scipy import stats

    n = len(r)
    sr = r.mean() / r.std(ddof=1)
    skew, kurt = stats.skew(r), stats.kurtosis(r, fisher=False)
    se = np.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1))
    g = 0.5772156649015329
    emax = 0.0 if n_trials <= 1 else se * ((1 - g) * stats.norm.ppf(1 - 1 / n_trials) + g * stats.norm.ppf(1 - 1 / (n_trials * np.e)))
    sr0 = emax if benchmark_sr is None else benchmark_sr
    return {"sr": sr, "skew": skew, "kurt": kurt, "se": se, "sr0": sr0, "dsr": stats.norm.cdf((sr - sr0) / se)}


def test_dsr_matches_the_closed_form_of_the_paper():
    r = _returns()
    ref = _reference_dsr(r, 50)
    out = deflated_sharpe_ratio(r, 50)
    assert out["sr"] == pytest.approx(ref["sr"], abs=5e-5)
    assert out["skew"] == pytest.approx(ref["skew"], abs=5e-5) and out["kurtosis"] == pytest.approx(ref["kurt"], abs=5e-5)
    assert out["benchmark_sr"] == pytest.approx(ref["sr0"], abs=5e-7)
    assert out["dsr"] == pytest.approx(ref["dsr"], abs=5e-5)
    assert out["p_value"] == pytest.approx(1 - ref["dsr"], abs=5e-6)
    assert out["n_obs"] == 400 and out["n_trials"] == 50


def test_dsr_annualises_the_sharpe_with_the_given_periods():
    r = _returns(seed=1)
    daily, monthly = deflated_sharpe_ratio(r, 5), deflated_sharpe_ratio(r, 5, periods_per_year=12)
    assert daily["sr_annualized"] == pytest.approx(daily["sr"] * np.sqrt(252), abs=2e-3)
    assert monthly["sr_annualized"] == pytest.approx(monthly["sr"] * np.sqrt(12), abs=1e-3)


def test_dsr_one_trial_or_a_zero_benchmark_is_the_probabilistic_sharpe_ratio():
    r = _returns(seed=2)
    ref = _reference_dsr(r, 1)
    assert deflated_sharpe_ratio(r, 1)["benchmark_sr"] == 0.0
    assert deflated_sharpe_ratio(r, 1)["dsr"] == pytest.approx(ref["dsr"], abs=5e-5)
    assert deflated_sharpe_ratio(r, 100, benchmark_sr=0.0)["dsr"] == pytest.approx(ref["dsr"], abs=5e-5)
    assert deflated_sharpe_ratio(r, 100, benchmark_sr=0.05)["benchmark_sr"] == 0.05
    assert deflated_sharpe_ratio(r, 0)["benchmark_sr"] == 0.0           # n_trials < 1 compte pour un essai


def test_dsr_needs_exactly_twenty_observations_and_ignores_nans():
    r = _returns(n=20, seed=3)
    assert np.isfinite(deflated_sharpe_ratio(r, 3)["dsr"])
    short = deflated_sharpe_ratio(r[:19], 3)
    assert np.isnan(short["dsr"]) and short["n_obs"] == 19 and short["n_trials"] == 3
    padded = np.concatenate([r, [np.nan, np.nan]])
    out = deflated_sharpe_ratio(padded, 3)
    assert out["n_obs"] == 20 and out["dsr"] == deflated_sharpe_ratio(r, 3)["dsr"]


def test_sharpe_standard_error_reduces_to_one_over_root_n_minus_one_under_normality():
    from patrick.validation.dsr import _sharpe_std_error

    assert _sharpe_std_error(101, 0.0, 3.0, 0.0) == pytest.approx(0.1)
    assert _sharpe_std_error(101, 0.0, 3.0, 0.2) == pytest.approx(np.sqrt((1 + 0.5 * 0.04) / 100))
    assert _sharpe_std_error(101, -0.5, 5.0, 0.2) == pytest.approx(np.sqrt((1 + 0.1 + 1.0 * 0.04) / 100))
    assert _sharpe_std_error(1, 0.0, 3.0, 0.0) == 1.0                    # n - 1 plancher à 1
    assert _sharpe_std_error(50, 10.0, 1.0, 1.0) == 0.0                  # variance négative ramenée à 0


def test_expected_max_sharpe_known_values_and_scaling():
    from scipy import stats

    from patrick.validation.dsr import expected_max_sharpe

    g = 0.5772156649015329
    assert expected_max_sharpe(2, 1.0) == pytest.approx(g * stats.norm.ppf(1 - 1 / (2 * np.e)))
    assert expected_max_sharpe(10, 1.0) == pytest.approx(
        (1 - g) * stats.norm.ppf(0.9) + g * stats.norm.ppf(1 - 1 / (10 * np.e)))
    assert expected_max_sharpe(10, 2.5) == pytest.approx(2.5 * expected_max_sharpe(10, 1.0))
    assert expected_max_sharpe(10, 0.0) == 0.0 and expected_max_sharpe(1, 1.0) == 0.0
