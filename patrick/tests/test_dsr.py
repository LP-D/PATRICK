"""Sharpe déflaté (Phase 2.3) — patrick.validation.dsr."""
from __future__ import annotations

import numpy as np

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
