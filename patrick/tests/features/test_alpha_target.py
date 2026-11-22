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


# --------------------------------------------------------------------------- jalon 2b : décalage de séance du benchmark

LAG = 1                    # le benchmark clôture après la cible (ex. ^GSPC pour une action européenne) : décalé d'une barre


def test_with_a_session_lag_beta_and_labels_follow_the_true_calendar():
    asset, bench = _levels()
    h, t = 20, 700
    labels = at.alpha_labels(asset, bench.shift(LAG), h, bench_lag=LAG)
    beta_true = at.point_in_time_beta(asset, bench)

    # β connu en t = β estimé jusqu'à la veille (le rendement du jour du benchmark n'est pas connu à la décision)
    expected = (asset.iloc[t + h] / asset.iloc[t] - 1) - beta_true.iloc[t - 1] * (bench.iloc[t + h] / bench.iloc[t] - 1)
    assert labels.iloc[t] == pytest.approx(expected)


def test_known_beta_ignores_what_the_lagged_benchmark_shows_after_t():
    asset, bench = _levels()
    asof, t = bench.shift(LAG), 800
    clean = at.known_beta(asset, asof, LAG)
    rng = np.random.default_rng(5)
    corrupted_asof = asof.copy()
    corrupted_asof.iloc[t + 1:] *= rng.uniform(0.4, 2.5, N - t - 1)

    corrupted = at.known_beta(asset, corrupted_asof, LAG)

    pd.testing.assert_series_equal(clean.iloc[: t + 1], corrupted.iloc[: t + 1])


def test_known_beta_does_use_the_information_available_at_t():
    asset, bench = _levels()
    asof, t = bench.shift(LAG), 800
    clean = at.known_beta(asset, asof, LAG)
    changed = asof.copy()
    changed.iloc[t] *= 1.2                         # = le cours du benchmark de la veille, connu à la décision de t

    assert at.known_beta(asset, changed, LAG).iloc[t] != clean.iloc[t]


def test_alpha_level_series_compounds_the_daily_alpha():
    asset, bench = _levels()
    asof = bench.shift(LAG)
    level = at.alpha_level_series(asset, asof, bench_lag=LAG)
    beta = at.known_beta(asset, asof, LAG)
    t = 600
    daily = asset.pct_change().iloc[t] - beta.iloc[t] * asof.pct_change().iloc[t]

    assert level.iloc[0] == pytest.approx(100.0)
    assert level.iloc[t] / level.iloc[t - 1] - 1 == pytest.approx(daily)


def test_persistence_signal_with_a_lag_only_uses_the_past():
    asset, bench = _levels()
    asof, h, t = bench.shift(LAG), 20, 900
    signal = at.alpha_persistence_signal(asset, asof, h, bench_lag=LAG)
    corrupted = asof.copy()
    corrupted.iloc[t + 1:] *= 1.9
    a2 = asset.copy()
    a2.iloc[t + 1:] *= 0.5

    pd.testing.assert_series_equal(signal.iloc[: t + 1], at.alpha_persistence_signal(a2, corrupted, h, bench_lag=LAG).iloc[: t + 1])


def _config(symbol, **objective):
    from patrick.config.schema import RunConfig
    return RunConfig.model_validate({
        "objective": {"target_symbol": symbol, "horizons": [5], **objective},
        "universe": {"yf_tickers": ["SPX_LIKE"], "start_date": "2015-01-01"}})


def test_run_target_is_the_historical_target_for_a_raw_config():
    from patrick.data.sources.yfinance_source import clean_symbol
    asset, _ = _levels()
    col = clean_symbol("AAPL")
    pool = pd.DataFrame({col: asset})

    got = at.run_target(pool, _config("AAPL"), col, 20, 1000)
    want = build_target(asset, 20, 1000, 0.003)

    pd.testing.assert_series_equal(got[0], want[0])
    assert got[2] == want[2]
    pd.testing.assert_series_equal(at.baseline_price_series(pool, _config("AAPL"), col), asset, check_names=False)


def test_run_target_for_alpha_uses_the_benchmark_column_and_the_session_lag():
    from patrick.data.sources.yfinance_source import clean_symbol
    asset, bench = _levels()
    col, bcol = clean_symbol("MC.PA"), clean_symbol("^GSPC")
    cfg = _config("MC.PA", target_kind="alpha", benchmark="^GSPC")           # clôture US après la clôture européenne
    pool = pd.DataFrame({col: asset, bcol: bench.shift(1)})                   # comme l'ingestion le décale

    assert at.bench_lag(cfg.objective) == 1
    got = at.run_target(pool, cfg, col, 20, 1000)
    want = at.build_alpha_target(asset, bench.shift(1), 20, 1000, bench_lag=1)

    pd.testing.assert_series_equal(got[0], want[0])
    level = at.baseline_price_series(pool, cfg, col)
    pd.testing.assert_series_equal(level, at.alpha_level_series(asset, bench.shift(1), bench_lag=1))


def test_bench_lag_is_zero_when_the_session_lag_is_disabled_or_the_closes_align():
    assert at.bench_lag(_config("MC.PA", target_kind="alpha", benchmark="^GSPC", disable_session_lag=True).objective) == 0
    assert at.bench_lag(_config("MC.PA", target_kind="alpha").objective) == 0            # ^STOXX50E : même séance
