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
    T, h = 150, 5   # >= 15 blocs indépendants (n/h) : sinon le test est refusé, voir plus bas
    loss_a = rng.binomial(1, 0.35, T).astype(float)
    loss_b = rng.binomial(1, 0.55, T).astype(float)
    out = diebold_mariano(loss_a, loss_b, h=h)
    dm_star, p = _reference_hln(loss_a - loss_b, h)
    assert out["dm_stat"] == pytest.approx(dm_star, abs=1e-4)
    assert out["p_value"] == pytest.approx(p, abs=1e-4)
    assert out["correction"] == "HLN"


def test_dm_hln_is_more_conservative_than_the_uncorrected_normal_test():
    rng = np.random.default_rng(4)
    T, h = 200, 10   # >= 15 blocs indépendants (n/h) : sinon le test est refusé, voir plus bas
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


# --- Testabilité selon l'horizon (audit du 2026-10-19) ---------------------------------------------------------------
# Les pertes d'un modèle évalué à l'horizon h partagent h-1 barres avec leurs voisines : l'échantillon de n lignes ne
# vaut que n/h observations indépendantes. Simulé sous H0 (différentiel de pertes = moyenne mobile de h erreurs
# indépendantes), le test à 5 % rejette : ~7 % avec 15 blocs, ~10 % avec 10, ~22 % avec 2,6 (holdout de 15 mois,
# h=120) et plus de 80 % à h=504. HLN et la fenêtre HAC ne suffisent pas : on refuse de conclure sous 15 blocs.

def _overlapping_noise(rng: np.random.Generator, n: int, h: int) -> np.ndarray:
    """Différentiel de pertes sous H0 pour un horizon h : moyenne mobile de h erreurs indépendantes."""
    return np.convolve(rng.standard_normal(n + h - 1), np.ones(h) / h, mode="valid")


def test_dm_refuses_a_verdict_when_the_horizon_leaves_too_few_independent_blocks():
    """Holdout de 15 mois (~315 séances) à h=252 : 1,25 bloc indépendant. Même un écart très net (10 % d'erreurs
    contre 50 %) n'est pas une preuve : le test doit être « non testable », pas p ≈ 0."""
    rng = np.random.default_rng(0)
    n, h = 315, 252
    loss_a = rng.binomial(1, 0.1, n).astype(float)
    loss_b = rng.binomial(1, 0.5, n).astype(float)
    out = diebold_mariano(loss_a, loss_b, h=h)
    assert np.isnan(out["dm_stat"]) and np.isnan(out["p_value"])
    assert out["n_obs"] == n
    assert out["untestable_reason"] == "horizon_too_long"


@pytest.mark.parametrize("h", [5, 20, 60])
def test_dm_horizon_rule_allows_exactly_fifteen_blocks_and_refuses_one_row_less(h):
    rng = np.random.default_rng(h)
    n_ok = 15 * h
    loss_a, loss_b = rng.random(n_ok), rng.random(n_ok)
    assert np.isfinite(diebold_mariano(loss_a, loss_b, h=h)["p_value"])
    refused = diebold_mariano(loss_a[:-1], loss_b[:-1], h=h)
    assert np.isnan(refused["p_value"]) and refused["untestable_reason"] == "horizon_too_long"


def test_dm_without_overlap_keeps_its_small_sample_behaviour():
    """h=1 : les pertes ne se chevauchent pas, la règle des blocs ne s'applique pas (seul le minimum de 10 lignes)."""
    rng = np.random.default_rng(5)
    out = diebold_mariano(rng.random(12), rng.random(12), h=1)
    assert np.isfinite(out["p_value"])


def test_dm_size_stays_near_nominal_at_the_smallest_allowed_sample():
    """Ce qui justifie le seuil de 15 blocs : à la taille minimale autorisée (h=20, n=300) le test à 5 % rejette H0
    moins de 11 % du temps sous H0 chevauchée (mesuré : ~8 %). Une dégradation de la variance ou de la correction
    HLN casserait ce test ; l'abaissement du seuil lui-même est couvert par le test de frontière ci-dessus."""
    rng = np.random.default_rng(11)
    h, reps = 20, 1500
    n = 15 * h
    p_values = np.array([diebold_mariano(_overlapping_noise(rng, n, h), np.zeros(n), h=h)["p_value"]
                         for _ in range(reps)])
    assert np.isfinite(p_values).all()
    assert (p_values < 0.05).mean() < 0.11
