"""Test de Diebold-Mariano (Phase 2.5) — patrick.validation.diebold_mariano."""
from __future__ import annotations

import numpy as np

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
