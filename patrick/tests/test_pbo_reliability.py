"""Rapport de correction, C5 -- diagnostic de fiabilité du PBO
(`patrick/validation/pbo_reliability.py`), calculé À CÔTÉ de `compute_pbo`
(`patrick/validation/pbo.py`), jamais en le modifiant."""
from __future__ import annotations

from math import comb

import numpy as np
import pytest

from patrick.validation.pbo import compute_pbo
from patrick.validation.pbo_reliability import (
    MIN_BLOCKS,
    MIN_COMBINATIONS_FLOOR,
    _combination_outcomes,
    pbo_reliability,
    required_blocks_reason,
)


@pytest.mark.parametrize("seed,n_trials,n_blocks", [
    (0, 13, 10), (1, 11, 6), (2, 7, 10), (3, 4, 10), (4, 19, 8),
    (5, 16, 8), (6, 12, 6), (7, 13, 10), (8, 8, 8), (9, 17, 6),
])
def test_combination_outcomes_matches_compute_pbo_exactly(seed, n_trials, n_blocks):
    """Garde-fou anti-dérive : si `compute_pbo` change un jour sans que ce
    module soit mis à jour en miroir, ce test doit le détecter."""
    rng = np.random.default_rng(seed)
    perf_matrix = rng.normal(0.5, 0.1, size=(n_trials, n_blocks))
    ref = compute_pbo(perf_matrix)
    mine = float(_combination_outcomes(perf_matrix).mean())
    assert abs(round(mine, 4) - ref["pbo"]) < 1e-6


def test_min_blocks_floor_is_calculation_based_not_arbitrary():
    """Vérifie l'arithmétique citée dans la justification : C(MIN_BLOCKS,
    MIN_BLOCKS/2) doit dépasser le plancher nécessaire (n*p>=5 et n*(1-p)>=5,
    pire cas p=0.5 -> n>=10), et le seuil juste en dessous ne doit PAS le
    satisfaire (sinon MIN_BLOCKS ne serait pas le seuil minimal réel)."""
    assert comb(MIN_BLOCKS, MIN_BLOCKS // 2) >= MIN_COMBINATIONS_FLOOR
    below = MIN_BLOCKS - 2  # prochaine valeur paire en dessous
    assert comb(below, below // 2) < MIN_COMBINATIONS_FLOOR, (
        f"MIN_BLOCKS={MIN_BLOCKS} ne serait pas le seuil minimal réel : "
        f"{below} blocs satisferait déjà le plancher."
    )


@pytest.mark.parametrize("n_blocks", [2, 4])
def test_pbo_reliability_refuses_below_min_blocks_explicitly(n_blocks):
    rng = np.random.default_rng(0)
    perf_matrix = rng.normal(0.5, 0.1, size=(10, n_blocks))
    result = pbo_reliability(perf_matrix)
    assert result["ok"] is False
    assert result["pbo"] != result["pbo"]  # NaN
    assert str(n_blocks) in result["message"] or "blocs disponibles" in result["message"]
    assert "n*p" in required_blocks_reason() or "combinaisons" in required_blocks_reason()


def test_pbo_reliability_computes_ci_above_min_blocks():
    rng = np.random.default_rng(1)
    n_blocks = 8
    perf_matrix = rng.normal(0.5, 0.1, size=(15, n_blocks))
    result = pbo_reliability(perf_matrix, n_bootstrap=500, seed=1)
    assert result["ok"] is True
    assert result["n_combinations"] == comb(n_blocks, n_blocks // 2)
    assert 0.0 <= result["ci_low"] <= result["pbo"] <= result["ci_high"] <= 1.0
    assert result["bootstrap_std"] >= 0.0
    # cohérent avec compute_pbo (même entrée, même valeur ponctuelle)
    ref = compute_pbo(perf_matrix)
    assert abs(result["pbo"] - ref["pbo"]) < 1e-6


def test_pbo_reliability_single_draw_wide_ci_matches_audit_finding():
    """Rapport d'audit, section E : sur un tirage aléatoire unique (n_blocks
    proche de 16), le PBO seul peut être loin de 0.5 -- l'intervalle de
    confiance bootstrap doit être visiblement large (pas un faux sentiment de
    précision), cohérent avec l'écart-type ~0.16 mesuré par l'audit sur 30
    tirages indépendants à n_blocks=16."""
    rng = np.random.default_rng(123)
    perf_matrix = rng.normal(0.5, 0.1, size=(50, 16))
    result = pbo_reliability(perf_matrix, n_bootstrap=2000, seed=123)
    assert result["ok"] is True
    width = result["ci_high"] - result["ci_low"]
    assert width > 0.15, f"intervalle de confiance suspicieusement étroit ({width:.3f}) pour un tirage unique."


def test_pbo_reliability_expectation_near_half_on_purely_random_data_many_draws():
    """Contrôle de cohérence avec l'audit (section E) : sur des données
    purement aléatoires, la moyenne du PBO sur PLUSIEURS tirages indépendants
    doit être proche de 0.5 (l'estimateur, non modifié ici, est correct en
    espérance) -- ce test valide l'infrastructure de test, pas une nouvelle
    propriété de `compute_pbo`."""
    pbos = []
    for seed in range(20):
        rng = np.random.default_rng(seed)
        perf_matrix = rng.normal(0.5, 0.1, size=(30, 8))
        pbos.append(pbo_reliability(perf_matrix, n_bootstrap=200, seed=seed)["pbo"])
    mean_pbo = float(np.mean(pbos))
    assert 0.35 <= mean_pbo <= 0.65, f"moyenne du PBO sur 20 tirages aléatoires = {mean_pbo}, attendu proche de 0.5"
