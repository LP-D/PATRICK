"""Dérive de la calibration en réel : Brier réel contre Brier du holdout."""
from __future__ import annotations

import numpy as np

from patrick.validation.calibration_drift import MIN_LIVE, calibration_drift


def test_an_overconfident_live_model_is_flagged_and_a_steady_one_is_not():
    rng = np.random.default_rng(1)
    n = 400
    y = (rng.random(n) < 0.5).astype(float)
    steady = np.clip(0.5 + 0.1 * (2 * y - 1) + rng.normal(0, 0.05, n), 0.01, 0.99)       # léger savoir, bien calibré
    holdout_brier = float(np.mean((steady - y) ** 2))
    assert calibration_drift(steady, y, holdout_brier)["degraded"] is False
    overconfident = np.where(rng.random(n) < 0.5, 0.95, 0.05)                              # sûr de lui, au hasard
    out = calibration_drift(overconfident, y, holdout_brier)
    assert out["degraded"] is True and out["drift"] > 0.3 and out["n_live"] == n


def test_too_few_live_signals_or_no_holdout_brier_gives_none():
    assert calibration_drift(np.full(MIN_LIVE - 1, 0.5), np.ones(MIN_LIVE - 1), 0.25) is None
    assert calibration_drift(np.full(50, 0.5), np.ones(50), None) is None
