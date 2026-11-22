"""Test de permutation par décalage circulaire et signal regroupé par paire cible-horizon (`validation/pooled_signal.py`)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.validation import pooled_signal as ps


def _dates(n):
    return pd.bdate_range("2025-01-01", periods=n)


def test_a_real_signal_is_detected_and_pure_noise_is_not():
    rng = np.random.default_rng(1)
    n = 300
    y = rng.integers(0, 2, n)
    signal = y + rng.normal(scale=1.2, size=n)              # AUC ~ 0,80
    assert ps.shift_test(y, signal, horizon=1, n_shift=500)["p_value"] < 0.01
    noise = ps.shift_test(y, rng.normal(size=n), horizon=1, n_shift=500)
    assert noise["p_value"] > 0.05 and abs(noise["auc"] - 0.5) < 0.12


def test_overlapping_labels_do_not_inflate_false_positives():
    """Au-delà d'un jour l'étiquette (rendement sur h jours) est autocorrélée : un test qui la mélangerait librement rejetterait bien plus
    que 5 % sur du bruit ; le décalage circulaire garde l'autocorrélation."""
    rng = np.random.default_rng(2)
    n, h, trials = 300, 20, 120
    rejections = 0
    for _ in range(trials):
        walk = rng.normal(size=n + h).cumsum()
        y = ((walk[h:] - walk[:-h]) > 0).astype(int)              # direction à 20 jours : très autocorrélée
        score = pd.Series(rng.normal(size=n)).rolling(15, min_periods=1).mean().to_numpy()   # score lui aussi lisse, sans lien
        if ps.shift_test(y, score, horizon=h, n_shift=300, seed=int(rng.integers(1e6)))["p_value"] < 0.05:
            rejections += 1
    assert rejections / trials < 0.13


def test_too_short_or_single_direction_series_give_no_p_value():
    assert np.isnan(ps.shift_test(np.zeros(200, int), np.arange(200.0), 1)["p_value"])
    assert np.isnan(ps.shift_test([0, 1] * 20, np.arange(40.0), 1)["p_value"])


def test_pooling_runs_improves_a_weak_common_signal():
    rng = np.random.default_rng(4)
    n = 320
    idx = _dates(n)
    y = pd.Series(rng.integers(0, 2, n), index=idx)
    frames = [pd.Series(0.12 * y.to_numpy() + rng.normal(size=n), index=idx) for _ in range(6)]
    out = ps.test_pair(frames, y, horizon=1, n_shift=400)
    assert out["n_runs"] == 6 and out["n_dates"] == n
    assert out["auc"] > out["auc_run_mean"] + 0.015                  # la moyenne de 6 modèles bruités vaut mieux qu'un seul
    assert 0.5 < out["auc_run_mean"] < 0.6


def test_pool_scores_needs_enough_runs_covering_a_date():
    idx = _dates(100)
    a = pd.Series(np.linspace(0, 1, 100), index=idx)
    b = pd.Series(np.linspace(1, 0, 60), index=idx[:60])
    c = pd.Series(np.linspace(0, 1, 60), index=idx[:60])
    pooled = ps.pool_scores([a, b, c], min_coverage=0.9)
    assert len(pooled) == 60                                        # 3 runs sur 3 seulement avant la 61e date
    assert len(ps.pool_scores([a, b, c], min_coverage=0.3)) == 100


def test_benjamini_hochberg_adjustment_flags_only_what_survives():
    results = {f"x{i}": {"p_value": 0.9} for i in range(30)}
    results["strong"] = {"p_value": 0.0005}
    results["nan"] = {"p_value": float("nan")}
    out = ps.adjust(results, alpha=0.10)
    assert out["strong"]["significant"] is True and out["strong"]["q_value"] is not None
    assert not any(out[f"x{i}"]["significant"] for i in range(30))
    assert out["nan"]["significant"] is False and out["nan"]["q_value"] is None
