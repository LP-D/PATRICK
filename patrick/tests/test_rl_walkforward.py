"""Validation walk-forward du RL (`rl/walkforward.py`, `rl/data.py`, `rl/metrics.py`) avec de FAUX agents : la logique des plis, de la
sélection de variables, de la mise à l'échelle, du report de position et des lignes de base se vérifie sans PyTorch ni entraînement.
Chaque garde d'anti-fuite est testée en plantant un signal qui n'existe que dans l'avenir."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from patrick.rl import data as rl_data
from patrick.rl import metrics as rl_metrics
from patrick.rl import walkforward as wf
from patrick.rl.config import RLRunConfig, RLSettings


def _data(n=1200, k=12, seed=0, signal=False) -> rl_data.RLData:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n + 1)
    ret = rng.normal(0.0003, 0.01, n)
    price = pd.Series(100 * np.cumprod(np.concatenate([[1.0], 1 + ret])), index=dates)
    fwd = (price.shift(-1) / price - 1.0).iloc[:-1].to_numpy()
    feats = pd.DataFrame(rng.normal(size=(n, k)), index=dates[:-1], columns=[f"f{i}" for i in range(k)])
    if signal:
        feats["f0"] = np.sign(fwd) + rng.normal(0, 0.5, n)          # un vrai signal (informé par le rendement suivant, comme un oracle)
    return rl_data.RLData(dates=dates[:-1], features=feats, fwd_ret=fwd, price=price, target_col="X")


def _cfg(**rl) -> RLRunConfig:
    return RLRunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}, "output": {"seed": 7},
                                       "rl": {"n_folds": 3, "min_train_frac": 0.5, "max_features": 4, "bootstrap_samples": 300,
                                              "total_timesteps": 1000, **rl}})


def _run(data, cfg, positions=1.0, spy=None):
    """`positions` : position constante de l'agent factice (ou fonction obs -> position)."""
    def train(core, settings, seed, start, end, on_progress):
        if spy is not None:
            spy.append({"core": core, "seed": seed, "start": start, "end": end})
        return object()

    def policy_from(model, settings):
        return positions if callable(positions) else (lambda obs: positions)

    def ensemble(policies):
        return lambda obs: float(np.mean([p(obs) for p in policies]))

    return wf.run_walkforward(data, cfg, train, policy_from, ensemble, progress=lambda line: None)


# --------------------------------------------------------------------------- plis


def test_folds_are_contiguous_non_overlapping_and_cover_the_end_of_the_sample():
    folds = wf.make_folds(1200, RLSettings(n_folds=4, min_train_frac=0.5))
    assert [f.test_lo for f in folds] == [600, 750, 900, 1050] and folds[-1].test_hi == 1200
    for a, b in zip(folds, folds[1:], strict=False):
        assert a.test_hi == b.test_lo
    assert all(f.train_lo == 0 and f.train_hi == f.test_lo - 1 for f in folds)          # un jour d'écart avant le test


def test_a_rolling_window_keeps_only_the_most_recent_rows():
    folds = wf.make_folds(2000, RLSettings(n_folds=2, min_train_frac=0.6, retrain="rolling", rolling_bars=500))
    assert [f.train_lo for f in folds] == [folds[0].test_lo - 500, folds[1].test_lo - 500]


def test_too_few_folds_fit_a_short_sample_and_a_tiny_one_is_refused():
    folds = wf.make_folds(420, RLSettings(n_folds=12, min_train_frac=0.6))
    assert len(folds) == 8 and all(f.test_hi - f.test_lo >= wf.MIN_TEST_ROWS for f in folds)
    with pytest.raises(rl_data.RLDataError, match="trop court"):
        wf.make_folds(300, RLSettings(n_folds=3, min_train_frac=0.5))


def test_training_never_sees_a_test_date_or_the_price_after_its_cut():
    data, spy = _data(), []
    result = _run(data, _cfg(), spy=spy)
    assert len(spy) == 3 and result["n_folds"] == 3
    for call, fold in zip(spy, result["folds"], strict=True):
        core = call["core"]
        test_start = pd.Timestamp(fold["test_start"])
        n_train = fold["n_train"]
        assert core.n == n_train and call["end"] == n_train
        # le rendement de la dernière date d'entraînement est réalisé AVANT le premier jour de test
        last_train_row = int(np.flatnonzero(data.dates == pd.Timestamp(fold["train_end"]))[0])
        assert data.dates[last_train_row + 1] < test_start
        assert np.array_equal(core.fwd_ret, data.fwd_ret[last_train_row + 1 - n_train:last_train_row + 1])


def test_the_stitched_oos_curve_has_one_point_per_test_date_and_no_gap():
    data = _data()
    result = _run(data, _cfg())
    n_test = sum(f["n_test"] for f in result["folds"])
    assert result["strategy"]["n"] == n_test == data.n - int(data.n * 0.5)
    assert result["curves"]["dates"][0] == result["folds"][0]["test_start"] and result["curves"]["dates"][-1] == result["folds"][-1]["test_end"]
    assert result["oos"]["dates"].is_monotonic_increasing and result["oos"]["dates"].is_unique


# --------------------------------------------------------------------------- sélection et échelle sur l'entraînement seul


def test_a_feature_that_predicts_only_the_test_period_is_never_selected():
    data = _data(k=20, seed=1)
    n = data.n
    # f0 « prédit » le rendement suivant UNIQUEMENT à partir de la ligne 600 (le test du premier pli) : l'entraînement ne le voit pas
    data.features["f0"] = np.where(np.arange(n) >= 600, np.sign(data.fwd_ret) * 3.0, 0.0) + np.random.default_rng(2).normal(0, 0.1, n)
    result = _run(data, _cfg(n_folds=1, max_features=3))
    assert "f0" not in result["folds"][0]["features"]


def test_a_feature_that_predicts_the_training_period_is_selected():
    data = _data(k=20, seed=3, signal=True)
    result = _run(data, _cfg(n_folds=1, max_features=3))
    assert "f0" in result["folds"][0]["features"] and len(result["folds"][0]["features"]) == 3


def test_selection_skips_near_duplicates_and_none_keeps_the_pool_order():
    rng = np.random.default_rng(4)
    base = rng.normal(size=500)
    fwd = base * 0.01 + rng.normal(0, 0.01, 500)
    train = pd.DataFrame({"a": base, "a_copy": base + rng.normal(0, 1e-3, 500), "b": rng.normal(size=500), "c": rng.normal(size=500)})
    chosen = rl_data.select_columns(train, fwd, 2, "correlation")
    assert len(chosen) == 2 and not {"a", "a_copy"} <= set(chosen)            # un seul des deux quasi-doublons
    assert rl_data.select_columns(train, fwd, 2, "none") == ["a", "a_copy"]


def test_scaling_uses_the_training_median_and_clips_extreme_future_values():
    rng = np.random.default_rng(5)
    train = pd.DataFrame({"x": rng.normal(10, 2, 400)})
    future = pd.DataFrame({"x": [10.0, 1e6, np.nan]})
    a, b = rl_data.scale_fold(train, future, ["x"])
    assert abs(float(np.median(a))) < 0.05                        # centré sur la médiane d'ENTRAÎNEMENT
    assert b[0, 0] == pytest.approx(0.0, abs=0.1) and b[1, 0] == 5.0 and b[2, 0] == 0.0 and a.dtype == np.float32


def test_a_feature_dominated_by_test_period_magnitude_does_not_change_the_training_scale():
    data = _data(seed=6)
    data.features["huge_in_test"] = np.where(np.arange(data.n) >= 600, 1e9, 1.0)
    cfg = _cfg(n_folds=1, max_features=12, feature_selection="none")
    spy: list = []
    _run(data, cfg, spy=spy)
    assert np.abs(spy[0]["core"].features).max() <= 5.0


# --------------------------------------------------------------------------- positions, coûts, lignes de base


def test_the_position_is_carried_between_folds_so_the_entry_cost_is_paid_once():
    result = _run(_data(), _cfg(cost_bps=20.0, slippage_bps=0.0), positions=1.0)
    oos = result["oos"]
    assert (oos["position"] == 1.0).all()
    assert oos["cost"][0] == pytest.approx(20e-4) and oos["cost"][1:].sum() == 0.0          # une entrée, jamais de re-paiement au changement de pli


def test_a_flat_agent_costs_nothing_and_earns_nothing_and_buy_and_hold_earns_the_asset():
    data = _data()
    result = _run(data, _cfg(), positions=0.0)
    assert result["strategy"]["total_return"] == 0.0 and result["strategy"]["cost_drag"] == 0.0 and result["strategy"]["exposure"] == 0.0
    first_test = int(data.n * 0.5)
    expected = float(np.prod(1 + data.fwd_ret[first_test:]) - 1)
    assert result["baselines"]["buy_hold"]["total_return"] == pytest.approx(expected)
    assert result["baselines"]["flat"]["total_return"] == 0.0


def test_the_ensemble_position_is_the_average_of_the_agents_and_each_agent_is_reported():
    cfg = _cfg(n_seeds=2)
    calls = {"i": 0}

    def positions_for(obs):
        return 0.0

    def train(core, settings, seed, start, end, on_progress):
        calls["i"] += 1
        return calls["i"] % 2                                     # impair : agent +1 ; pair : agent −1

    def policy_from(model, settings):
        return (lambda obs: 1.0) if model else (lambda obs: -1.0)

    result = wf.run_walkforward(_data(), cfg, train, policy_from, lambda ps: (lambda obs: float(np.mean([p(obs) for p in ps]))),
                                progress=lambda line: None)
    assert (result["oos"]["position"] == 0.0).all() and len(result["seeds"]) == 2
    assert positions_for(None) == 0.0
    assert {s["seed"] for s in result["seeds"]} == {1, 2}


def test_momentum_is_causal_and_pays_its_costs():
    data = _data(seed=8)
    rows = np.arange(700, 900)
    settings = RLSettings()
    pos = wf.momentum_positions(data.price.reset_index(drop=True), rows, settings)
    altered = data.price.copy()
    altered.iloc[900:] *= 3.0                                    # l'avenir change, les positions passées non
    pos2 = wf.momentum_positions(altered.reset_index(drop=True), rows, settings)
    assert np.array_equal(pos, pos2) and set(np.unique(pos)) <= {-1.0, 0.0, 1.0}
    assert set(np.unique(wf.momentum_positions(data.price.reset_index(drop=True), rows, RLSettings(allow_short=False)))) <= {0.0, 1.0}


def test_an_oracle_agent_beats_buy_and_hold_but_the_bootstrap_still_reports_its_uncertainty():
    data = _data(seed=9)
    sign = np.sign(data.fwd_ret)

    def oracle(obs):
        return 0.0

    # l'oracle lit le rendement futur directement dans une variable : il n'a de sens que pour vérifier la chaîne de métriques
    cfg = _cfg(cost_bps=0.0, slippage_bps=0.0)
    state = {"t": 0}
    first_test = int(data.n * 0.5)

    def make_policy(model, settings):
        def policy(obs):
            idx = first_test + state["t"]
            state["t"] += 1
            return float(sign[idx]) if idx < data.n else 0.0
        return policy

    result = wf.run_walkforward(data, cfg, lambda *a: None, make_policy, lambda ps: ps[0], progress=lambda line: None)
    stats = result["stats"]["vs_buy_hold"]
    assert result["strategy"]["sharpe"] > result["baselines"]["buy_hold"]["sharpe"] * 3
    assert stats["diff"] > 0 and stats["ci_low"] > 0 and stats["p_one_sided"] < 0.05 and stats["n"] == data.n - first_test
    assert result["stats"]["psr"] > 0.99 and oracle(None) == 0.0


def test_the_deflated_sharpe_uses_the_number_of_prior_trials():
    data = _data(seed=10)
    low = _run(data, _cfg(), positions=1.0)
    cfg = _cfg()
    many = wf.run_walkforward(data, cfg, lambda *a: None, lambda m, s: (lambda obs: 1.0), lambda ps: ps[0], progress=lambda line: None, n_trials=200)
    assert low["stats"]["n_trials"] == 1 and many["stats"]["n_trials"] == 200
    assert many["stats"]["dsr"]["benchmark_sr"] > low["stats"]["dsr"]["benchmark_sr"]


def test_progress_is_reported_with_the_markers_the_worker_reads():
    lines: list[str] = []
    cfg = _cfg(n_folds=2, n_seeds=2)
    wf.run_walkforward(_data(), cfg, lambda *a: None, lambda m, s: (lambda obs: 0.0), lambda ps: ps[0], progress=lines.append)
    assert lines[0].startswith("[RL-DATA]") and "[RL-PROGRESS] 0/4" in lines
    assert "[RL-PROGRESS] 4/4" in lines and sum(1 for line in lines if line.startswith("[RL-EVAL]")) == 2


# --------------------------------------------------------------------------- métriques


def test_summary_metrics_match_hand_computation():
    dates = pd.bdate_range("2020-01-01", periods=4)
    r = np.array([0.01, -0.02, 0.03, 0.0])
    pos = np.array([1.0, 1.0, -1.0, 0.0])
    m = rl_metrics.summarize(r, pos, np.array([0.001, 0.0, 0.002, 0.001]), dates)
    assert m["total_return"] == pytest.approx(1.01 * 0.98 * 1.03 - 1)
    assert m["turnover"] == pytest.approx((1 + 0 + 2 + 1) / 4 * 252)
    assert m["exposure"] == pytest.approx(0.75) and m["n_trades"] == 3 and m["cost_drag"] == pytest.approx(0.004)
    assert m["net_long_share"] == 0.5 and m["short_share"] == 0.25
    assert m["hit_rate"] == pytest.approx(2 / 3) and m["max_drawdown"] == pytest.approx(0.98 - 1)


def test_bootstrap_of_identical_series_finds_no_difference_and_short_series_are_refused():
    rng = np.random.default_rng(0)
    a = rng.normal(0.0004, 0.01, 500)
    same = rl_metrics.bootstrap_sharpe_diff(a, a, 300)
    assert same["diff"] == 0.0 and same["ci_low"] == 0.0 and same["ci_high"] == 0.0
    # deux séries indépendantes de même Sharpe : l'intervalle à 90 % doit contenir 0 la plupart du temps (calibration, pas un tirage)
    covered = 0
    for i in range(40):
        r = rl_metrics.bootstrap_sharpe_diff(rng.normal(0.0004, 0.01, 400), rng.normal(0.0004, 0.01, 400), 200, seed=i)
        covered += r["ci_low"] <= 0 <= r["ci_high"]
    assert covered >= 30
    assert math.isnan(rl_metrics.bootstrap_sharpe_diff(a[:10], a[:10])["diff"])


def test_the_bootstrap_is_reproducible():
    rng = np.random.default_rng(1)
    a, b = rng.normal(0.001, 0.01, 400), rng.normal(0.0, 0.01, 400)
    assert rl_metrics.bootstrap_sharpe_diff(a, b, 400, seed=3) == rl_metrics.bootstrap_sharpe_diff(a, b, 400, seed=3)


def test_probabilistic_sharpe_grows_with_the_evidence():
    rng = np.random.default_rng(2)
    weak = rl_metrics.probabilistic_sharpe(rng.normal(0.0001, 0.01, 200))
    strong = rl_metrics.probabilistic_sharpe(rng.normal(0.002, 0.01, 2000))
    assert strong > 0.99 > weak and math.isnan(rl_metrics.probabilistic_sharpe(np.zeros(100)))
