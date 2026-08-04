"""PBO / CSCV (Phase 2.4) — patrick.validation.pbo."""
from __future__ import annotations

import numpy as np

from patrick.validation.pbo import compute_pbo


def test_pbo_low_when_one_trial_is_consistently_best():
    """Un trial nettement et uniformément meilleur que les autres sur TOUS les
    blocs doit rester le meilleur en OOS quel que soit le découpage IS/OOS —
    PBO doit être bas (pas de surapprentissage)."""
    rng = np.random.default_rng(0)
    n_trials, n_blocks = 8, 8
    perf = rng.normal(0.5, 0.02, (n_trials, n_blocks))
    perf[0, :] += 0.3  # trial 0 dominant sur tous les blocs, marge large
    out = compute_pbo(perf)
    assert out["pbo"] < 0.3
    assert out["n_blocks"] == 8
    assert out["n_combinations"] > 0


def test_pbo_high_when_best_in_sample_is_pure_noise():
    """Performance indépendante et identiquement distribuée bloc par bloc, sans
    aucun signal réel : le "meilleur en IS" est essentiellement aléatoire et ne
    doit pas généraliser -> PBO proche de 0.5 (autour du hasard)."""
    rng = np.random.default_rng(42)
    n_trials, n_blocks = 20, 8
    perf = rng.normal(0.0, 1.0, (n_trials, n_blocks))
    out = compute_pbo(perf)
    assert 0.3 < out["pbo"] < 0.7


def test_pbo_drops_earliest_block_when_odd_count():
    rng = np.random.default_rng(0)
    perf = rng.normal(0, 1, (6, 5))  # 5 blocs, impair
    out = compute_pbo(perf)
    assert out["n_blocks"] == 4


def test_pbo_nan_with_insufficient_blocks_or_trials():
    out = compute_pbo(np.zeros((1, 4)))
    assert np.isnan(out["pbo"])
    out2 = compute_pbo(np.zeros((5, 1)))
    assert np.isnan(out2["pbo"])
