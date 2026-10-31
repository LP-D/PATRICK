"""Décision de direction causale à partir de P(hausse) et AUC de direction (`validation/direction.py`)."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation import direction as dr


def _naive_trailing(p, window, min_history, fallback=0.5):
    out = np.full(len(p), fallback, float)
    for i in range(len(p)):
        history = p[max(0, i - window):i]
        if len(history) >= min_history:
            out[i] = np.median(history)
    return out


@pytest.mark.parametrize("n", [5, 10, 11, 60, 130, 400])
def test_trailing_median_matches_a_plain_loop(n):
    p = np.random.default_rng(n).uniform(0.2, 0.8, n)
    assert np.allclose(dr.trailing_median(p, window=50, min_history=10), _naive_trailing(p, 50, 10))
    assert np.allclose(dr.trailing_median(p), _naive_trailing(p, dr.TRAIL_WINDOW, dr.MIN_HISTORY))


def test_a_decision_never_depends_on_a_later_row():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.1, 0.9, 300)
    before = dr.direction_from_p_up(p)
    altered = p.copy()
    altered[200:] = 0.99                                    # l'avenir change du tout au tout
    after = dr.direction_from_p_up(altered)
    assert np.array_equal(before[:200], after[:200])


def test_recentering_recovers_the_signal_of_a_biased_model():
    """Un modèle dont les P(hausse) tournent autour de 0,35 (rééquilibrage, régime) classerait tout en baisse avec un seuil de 0,5 ;
    recentré sur ses prédictions récentes il retrouve le signal qu'il porte."""
    rng = np.random.default_rng(3)
    n = 800
    signal = rng.normal(size=n)
    y = (signal + rng.normal(scale=1.0, size=n) > 0).astype(int)
    p = 0.35 + 0.06 * np.tanh(signal)                     # classement informatif, centre à 0,35
    assert (p > 0.5).sum() == 0                            # seuil fixe : aucune hausse prédite
    m = dr.direction_metrics(y, p)
    from sklearn.metrics import f1_score

    fixed = f1_score(y, (p > 0.5).astype(int), average="macro", zero_division=0)
    assert m["F1_dir_p"] > fixed + 0.15
    assert m["AUC_dir"] > 0.65


def test_auc_dir_is_threshold_free_and_exact_on_simple_cases():
    y = np.array([0, 0, 0, 1, 1, 1] * 20)
    assert dr.direction_metrics(y, np.where(y == 1, 0.7, 0.3))["AUC_dir"] == 1.0
    assert dr.direction_metrics(y, np.where(y == 1, 0.3, 0.7))["AUC_dir"] == 0.0
    rng = np.random.default_rng(5)
    assert abs(dr.direction_metrics(rng.integers(0, 2, 4000), rng.uniform(size=4000))["AUC_dir"] - 0.5) < 0.04


def test_metrics_are_nan_when_a_single_direction_or_no_probability():
    out = dr.direction_metrics(np.ones(50), np.linspace(0.2, 0.8, 50))
    assert np.isnan(out["AUC_dir"]) and np.isnan(out["F1_dir_p"]) and 0.0 <= out["Acc_dir_p"] <= 1.0
    empty = dr.direction_metrics([], [])
    assert all(np.isnan(v) for v in empty.values())
    mismatched = dr.direction_metrics([0, 1, 1], [0.2, 0.9])
    assert all(np.isnan(v) for v in mismatched.values())


def test_non_finite_rows_are_dropped_before_scoring():
    y = np.array([0, 1] * 40, dtype=float)
    p = np.where(y == 1, 0.7, 0.3).astype(float)
    p[::7] = np.nan
    assert dr.direction_metrics(y, p)["AUC_dir"] == 1.0
