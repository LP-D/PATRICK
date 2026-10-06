"""Cible alpha vs benchmark, jalon 1 : β point-in-time, rendement excédentaire, cible 4 classes, baselines.

Chaque test de fuite corrompt le FUTUR d'une date et exige que tout ce qui était connu à cette date soit identique
au bit près (docs/ways-of-working.md : test de fuite par corruption)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features import alpha_target as at
from patrick.features.target import build_target

N = 1500
IDX = pd.bdate_range("2018-01-01", periods=N)


def _levels(true_beta=1.5, market_drift=0.0008, seed=0):
    rng = np.random.default_rng(seed)
    rb = rng.normal(market_drift, 0.01, N)
    ra = true_beta * rb + rng.normal(0.0, 0.004, N)
    return (pd.Series(100 * np.cumprod(1 + ra), index=IDX, name="asset"),
            pd.Series(100 * np.cumprod(1 + rb), index=IDX, name="bench"))


def test_point_in_time_beta_recovers_the_true_beta_and_is_nan_before_min_obs():
    asset, bench = _levels(true_beta=1.5)
    beta = at.point_in_time_beta(asset, bench, window=252, min_obs=60)

    assert beta.iloc[:59].isna().all() and beta.iloc[60:].notna().all()
    assert beta.iloc[-1] == pytest.approx(1.5, abs=0.15)


def test_beta_at_t_ignores_everything_after_t():
    asset, bench = _levels()
    t = 800
    clean = at.point_in_time_beta(asset, bench)
    rng = np.random.default_rng(9)
    a2, b2 = asset.copy(), bench.copy()
    a2.iloc[t + 1:] *= rng.uniform(0.5, 2.0, N - t - 1)
    b2.iloc[t + 1:] *= rng.uniform(0.5, 2.0, N - t - 1)

    corrupted = at.point_in_time_beta(a2, b2)

    pd.testing.assert_series_equal(clean.iloc[: t + 1], corrupted.iloc[: t + 1])


def test_alpha_forward_return_matches_a_hand_computation():
    idx = pd.bdate_range("2026-01-05", periods=5)
    asset = pd.Series([100.0, 110.0, 121.0, 133.1, 146.41], index=idx)       # +10 % par jour
    bench = pd.Series([100.0, 105.0, 110.25, 115.7625, 121.550625], index=idx)   # +5 % par jour
    beta = pd.Series(2.0, index=idx)

    alpha = at.alpha_forward_return(asset, bench, horizon=2, beta=beta)

    # actif +21 %, benchmark +10,25 % sur 2 jours : 0,21 - 2 * 0,1025 = 0,005
    assert alpha.iloc[0] == pytest.approx(0.21 - 2 * 0.1025)
    assert alpha.iloc[-2:].isna().all()


def test_series_are_aligned_on_their_common_dates():
    asset, bench = _levels()
    bench = bench.drop(bench.index[100:110])                                  # jours fériés d'une autre place

    beta = at.point_in_time_beta(asset, bench)

    assert beta.index.equals(asset.index.intersection(bench.index))


def test_alpha_target_is_balanced_while_the_raw_target_is_dominated_by_the_market():
    # Moyenne sur 8 tirages : les fenêtres de 20 jours se chevauchent (~75 observations indépendantes par tirage),
    # un seul tirage varie de 0,38 à 0,59 (mesuré sur 12 graines : alpha 0,49 en moyenne, brut 0,71).
    h, split = 20, 1200
    raw_up, alpha_up, first_label = [], [], []
    for seed in range(8):
        asset, bench = _levels(true_beta=1.5, market_drift=0.0015, seed=seed)
        raw, _, _ = build_target(asset, h, split)
        alpha, _, _ = at.build_alpha_target(asset, bench, h, split)
        raw_up.append(raw.isin((2, 3)).mean())
        alpha_up.append(alpha.isin((2, 3)).mean())
        first_label.append(alpha.index.min() >= asset.index[59])                 # pas de label sans β
    assert np.mean(raw_up) > 0.65
    assert 0.44 < np.mean(alpha_up) < 0.56
    assert all(first_label)


def test_alpha_target_thresholds_ignore_data_after_the_split():
    asset, bench = _levels()
    h, split = 20, 1000
    _, _, thr = at.build_alpha_target(asset, bench, h, split)
    rng = np.random.default_rng(3)
    a2, b2 = asset.copy(), bench.copy()
    a2.iloc[split:] *= rng.uniform(0.3, 3.0, N - split)
    b2.iloc[split:] *= rng.uniform(0.3, 3.0, N - split)

    _, _, thr_corrupted = at.build_alpha_target(a2, b2, h, split)

    assert thr == thr_corrupted


def test_persistence_signal_only_uses_the_past_and_matches_the_past_alpha():
    asset, bench = _levels()
    h, t = 20, 900
    signal = at.alpha_persistence_signal(asset, bench, h)
    beta = at.point_in_time_beta(asset, bench)
    past = (asset.iloc[t] / asset.iloc[t - h] - 1) - beta.iloc[t] * (bench.iloc[t] / bench.iloc[t - h] - 1)
    assert signal.iloc[t] == (1 if past > 0 else 0)

    a2, b2 = asset.copy(), bench.copy()
    a2.iloc[t + 1:] *= 1.7
    b2.iloc[t + 1:] *= 0.6
    corrupted = at.alpha_persistence_signal(a2, b2, h)
    pd.testing.assert_series_equal(signal.iloc[: t + 1], corrupted.iloc[: t + 1])


def test_build_target_is_unchanged_without_an_explicit_return_series():
    asset, _ = _levels()
    default, regime, thr = build_target(asset, 20, 1000)
    explicit_ret = (asset.ffill().bfill().shift(-20) / asset.ffill().bfill()) - 1
    same, regime2, thr2 = build_target(asset, 20, 1000, ret=explicit_ret)

    pd.testing.assert_series_equal(default, same)
    pd.testing.assert_series_equal(regime, regime2)
    assert thr == thr2
