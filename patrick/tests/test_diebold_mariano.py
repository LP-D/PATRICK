"""Test de Diebold-Mariano (Phase 2.5) — patrick.validation.diebold_mariano."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation.diebold_mariano import diebold_mariano


def test_dm_significant_when_candidate_clearly_better():
    rng = np.random.default_rng(0)
    n = 300
    loss_a = rng.binomial(1, 0.2, n).astype(float)  # candidat : 20% d'erreur
    loss_b = rng.binomial(1, 0.5, n).astype(float)  # baseline : 50% d'erreur
    out = diebold_mariano(loss_a, loss_b)
    assert out["dm_stat"] < 0  # perte du candidat < perte de la baseline
    assert out["p_value"] < 0.01
    assert out["mean_loss_diff"] < 0


def test_dm_not_significant_when_identical_performance():
    rng = np.random.default_rng(1)
    loss = rng.binomial(1, 0.4, 200).astype(float)
    out = diebold_mariano(loss, loss.copy())
    assert out["dm_stat"] == 0.0
    assert out["p_value"] == 1.0
    assert out["mean_loss_diff"] == 0.0


def test_dm_too_few_observations_returns_nan():
    out = diebold_mariano(np.array([1.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]))
    assert np.isnan(out["dm_stat"])
    assert np.isnan(out["p_value"])
    assert out["n_obs"] == 3


def test_dm_symmetry_flips_sign():
    rng = np.random.default_rng(2)
    loss_a = rng.binomial(1, 0.2, 200).astype(float)
    loss_b = rng.binomial(1, 0.5, 200).astype(float)
    ab = diebold_mariano(loss_a, loss_b)
    ba = diebold_mariano(loss_b, loss_a)
    assert ab["dm_stat"] == -ba["dm_stat"]
    assert ab["p_value"] == ba["p_value"]


def _reference_hln(d: np.ndarray, h: int) -> tuple[float, float]:
    """Independent reference: Diebold & Mariano (1995) statistic with the
    standard autocovariance estimator gamma_k = (1/T) sum_{t>k} (d_t - dbar)
    (d_{t-k} - dbar), rectangular window up to lag h-1, then the Harvey,
    Leybourne & Newbold (1997) small-sample correction
    DM* = DM * sqrt((T + 1 - 2h + h(h-1)/T) / T), referred to Student t(T-1)."""
    from scipy import stats

    T = len(d)
    dbar = d.mean()
    c = d - dbar
    var = c @ c / T + 2 * sum(c[k:] @ c[:-k] / T for k in range(1, h))
    dm = dbar / np.sqrt(var / T)
    dm_star = dm * np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    return dm_star, 2 * stats.t.sf(abs(dm_star), df=T - 1)


def test_dm_applies_the_harvey_leybourne_newbold_correction():
    """F04: without HLN the statistic is referred to N(0,1) with no
    small-sample/horizon correction -- over-rejects H0 for small T and
    h > 1 (HLN 1997, Table 1). DM is evaluated here on a SINGLE walk-forward
    fold (a few hundred rows at most), squarely in that regime."""
    rng = np.random.default_rng(3)
    T, h = 60, 5
    loss_a = rng.binomial(1, 0.35, T).astype(float)
    loss_b = rng.binomial(1, 0.55, T).astype(float)
    out = diebold_mariano(loss_a, loss_b, h=h)
    dm_star, p = _reference_hln(loss_a - loss_b, h)
    assert out["dm_stat"] == pytest.approx(dm_star, abs=1e-4)
    assert out["p_value"] == pytest.approx(p, abs=1e-4)
    assert out["correction"] == "HLN"


def test_dm_hln_is_more_conservative_than_the_uncorrected_normal_test():
    rng = np.random.default_rng(4)
    T, h = 50, 10
    loss_a = rng.binomial(1, 0.30, T).astype(float)
    loss_b = rng.binomial(1, 0.50, T).astype(float)
    d = loss_a - loss_b
    from scipy import stats
    c = d - d.mean()
    var = c @ c / T + 2 * sum(c[k:] @ c[:-k] / T for k in range(1, h))
    p_normal = 2 * stats.norm.sf(abs(d.mean() / np.sqrt(var / T)))
    assert diebold_mariano(loss_a, loss_b, h=h)["p_value"] > p_normal


_NEG_VAR_D = np.array([0, 0, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0,
                       1, -1, -1, 1, 0, 0, 1, 0, -1, 1, -1, 1, 1, -1, 1, -1, 0, 0, -1, 1,
                       1, -1, 0, 1, 0, 0, 0, 0, -1, 1, -1, 1, 1, -1, 0, 0, -1, 1, 1, -1], dtype=float)


def test_dm_negative_rectangular_variance_falls_back_to_bartlett_not_a_clamp():
    """The rectangular window used by DM can yield a NEGATIVE long-run
    variance for h > 1 (here a 0/1-loss differential with strong negative
    lag-1 dependence, h=3). It used to be clamped to 1e-12, turning the
    nonzero mean difference into an astronomically large statistic --
    p=0.0, reported as highly significant. It now falls back to Bartlett
    (Newey-West) weights, non-negative by construction."""
    c = _NEG_VAR_D - _NEG_VAR_D.mean()
    T = len(c)
    rect = c @ c / T + 2 * sum(c[k:] @ c[:-k] / T for k in (1, 2))
    assert rect < 0
    out = diebold_mariano(_NEG_VAR_D, np.zeros(T), h=3)
    assert out["variance_kernel"] == "bartlett"
    assert np.isfinite(out["dm_stat"]) and abs(out["dm_stat"]) < 10
    assert out["p_value"] > 0.01
