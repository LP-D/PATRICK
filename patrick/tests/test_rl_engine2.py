"""Moteur RL 2 (refonte du 2026-11-16, ADR 0022) : chaque changement est tiré d'un échec mesuré sur les 456 runs du moteur 1 et testé ici
sans PyTorch (faux agents), sauf le choix du point de contrôle (Stable-Baselines3, ignoré s'il manque).

- récompense « excess » : log-croissance moins celle de l'actif ;
- une décision toutes les `rebalance_every` barres, position tenue entre deux ;
- frais multipliés à l'entraînement, vrais frais à l'évaluation ;
- validation en fin de fenêtre d'entraînement (jamais apprise ni utilisée pour choisir les variables) et repli sur l'achat-conservation ;
- référence « tendance 200 j », test du décalage d'un jour, règle des séances de change ;
- une configuration complète du moteur 1 garde son moteur.
"""
from __future__ import annotations

import importlib.util
import math

import numpy as np
import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.rl import data as rl_data
from patrick.rl import walkforward as wf
from patrick.rl.config import RLRunConfig, RLSettings
from patrick.rl.core import TradingCore, rollout

needs_gym = pytest.mark.skipif(importlib.util.find_spec("gymnasium") is None, reason="gymnasium non installé (extra optionnel rl)")


def _data(n=1200, k=6, seed=0, drift=0.0003, vol=0.01, signal=False) -> rl_data.RLData:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n + 1)
    ret = rng.normal(drift, vol, n)
    price = pd.Series(100 * np.cumprod(np.concatenate([[1.0], 1 + ret])), index=dates)
    fwd = (price.shift(-1) / price - 1.0).iloc[:-1].to_numpy()
    feats = pd.DataFrame(rng.normal(size=(n, k)), index=dates[:-1], columns=[f"f{i}" for i in range(k)])
    if signal:
        feats["f0"] = np.sign(fwd) + rng.normal(0, 0.3, n)          # oracle : informé par le rendement suivant
    return rl_data.RLData(dates=dates[:-1], features=feats, fwd_ret=fwd, price=price, target_col="X")


def _cfg(**rl) -> RLRunConfig:
    return RLRunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}, "output": {"seed": 3},
                                       "rl": {"n_folds": 2, "min_train_frac": 0.5, "max_features": 6, "feature_selection": "none",
                                              "bootstrap_samples": 300, "total_timesteps": 1000, "n_seeds": 1, **rl}})


def _run(data, cfg, policy, spy=None):
    """`policy` : obs -> position, la même pour chaque agent. `spy` reçoit chaque appel d'entraînement (cœur, bornes, validate)."""
    def train(core, settings, seed, start, end, on_progress, validate=None):
        if spy is not None:
            spy.append({"core": core, "start": start, "end": end, "validate": validate})
        return object()

    return wf.run_walkforward(data, cfg, train, lambda model, s: policy, lambda ps: ps[0], progress=lambda line: None)


# --------------------------------------------------------------------------- configuration


def test_defaults_are_long_only_excess_reward_weekly_decisions_with_validation_and_fallback():
    s = RLSettings()
    assert s.engine_version == 2 and s.allow_short is False and s.reward == "excess" and s.rebalance_every == 5
    assert s.train_cost_mult == 2.0 and s.val_frac == 0.2 and s.gate is True and s.positions() == [0.0, 0.5, 1.0]
    assert s.benchmark_position == 1.0 and RLSettings(max_leverage=0.5).benchmark_position == 0.5


def test_a_complete_engine_1_config_keeps_its_engine_and_a_partial_dict_gets_engine_2():
    stored = {k: v for k, v in D.DEFAULT_RL.items() if k not in ("rebalance_every", "train_cost_mult", "val_frac", "gate")}
    stored.update({"allow_short": True, "reward": "log"})                     # tel qu'enregistré par le moteur 1
    old = RLSettings.model_validate(stored)
    assert old.engine_version == 1 and old.rebalance_every == 1 and old.val_frac == 0.0 and old.gate is False and old.train_cost_mult == 1.0
    assert RLSettings.model_validate({"algo": "PPO", "n_folds": 2}).engine_version == 2
    again = RLSettings.model_validate(old.model_dump())                       # ré-enregistré : reste au moteur 1
    assert again.engine_version == 1 and again.rebalance_every == 1


def test_the_fallback_needs_a_validation_share():
    with pytest.raises(ValueError, match="validation"):
        RLSettings(val_frac=0.0, gate=True)
    assert RLSettings(val_frac=0.0, gate=False).val_frac == 0.0


# --------------------------------------------------------------------------- environnement


def test_the_excess_reward_is_log_growth_minus_the_assets_and_ignores_the_market_when_fully_invested():
    s = RLSettings(cost_bps=0.0, slippage_bps=0.0)
    fwd = np.array([0.02, -0.03, 0.01])
    core = TradingCore(np.zeros((3, 1)), fwd, s, reward_scale=10.0)
    core.reset(0, 3, prev_pos=1.0)
    assert [core.step(1.0)[0] for _ in range(3)] == pytest.approx([0.0, 0.0, 0.0])        # investi = l'actif : rien à apprendre du marché
    core.reset(0, 3, prev_pos=0.0)
    r = core.step(0.0)[0]
    assert r == pytest.approx(-math.log1p(0.02) * 10.0)                                     # à plat pendant une hausse : manque à gagner


def test_training_fees_are_multiplied_and_evaluation_pays_the_real_ones():
    s = RLSettings(cost_bps=5.0, slippage_bps=2.0, train_cost_mult=3.0)
    data, spy = _data(), []
    result = _run(data, _cfg(cost_bps=5.0, slippage_bps=2.0, train_cost_mult=3.0), lambda obs: 1.0, spy=spy)
    assert spy[0]["core"].fee == pytest.approx(7e-4 * 3.0) and s.train_cost_mult == 3.0
    assert result["oos"]["cost"][0] == pytest.approx(7e-4)                                 # l'entrée hors échantillon au vrai tarif


def test_a_rollout_consults_the_policy_once_every_rebalance_bars_and_holds_in_between():
    s = RLSettings(cost_bps=10.0, slippage_bps=0.0)
    core = TradingCore(np.zeros((20, 1)), np.full(20, 0.001), s, reward_scale=1.0)
    calls = {"n": 0}

    def flip(obs):
        calls["n"] += 1
        return 1.0 if calls["n"] % 2 else 0.0

    out = rollout(core, flip, 0, 20, 0.0, rebalance_every=5)
    assert calls["n"] == 4 and out["positions"].tolist() == [1.0] * 5 + [0.0] * 5 + [1.0] * 5 + [0.0] * 5
    assert np.flatnonzero(out["costs"]).tolist() == [0, 5, 10, 15]                         # des frais aux seules décisions


@needs_gym
def test_one_env_step_spans_rebalance_bars_and_sums_their_rewards():
    from patrick.rl.env import TradingEnv
    s = RLSettings(rebalance_every=4, cost_bps=0.0, slippage_bps=0.0, reward="log", episode_length=0)
    fwd = np.full(10, 0.01)
    core = TradingCore(np.zeros((10, 2)), fwd, s, reward_scale=1.0)
    env = TradingEnv(core, s, start=0, end=10, seed=0)
    env.reset(seed=0)
    _obs, reward, terminated, truncated, info = env.step(2)                                # position 1
    assert core.t == 4 and reward == pytest.approx(4 * math.log1p(0.01)) and info["net_return"] == pytest.approx(1.01 ** 4 - 1)
    env.step(2)
    _obs, _r, terminated, truncated, _info = env.step(2)                                   # 2 barres restantes, puis troncature
    assert core.t == 10 and truncated and not terminated


# --------------------------------------------------------------------------- validation et repli


def test_split_validation_keeps_a_one_day_gap_and_gives_up_on_short_windows():
    s = RLSettings(val_frac=0.2)
    assert wf.split_validation(1000, s) == 1000 - 200 - 1
    assert wf.split_validation(280, s) == 280                                              # partie apprise < 250 lignes : pas de validation
    assert wf.split_validation(1000, RLSettings(val_frac=0.0, gate=False)) == 1000


def test_validation_rows_are_never_learned_nor_used_to_select_features():
    data, spy = _data(k=8, seed=4), []
    n = data.n
    # f7 « prédit » le rendement suivant seulement sur les lignes de validation du premier pli : la sélection ne doit pas le voir
    folds = wf.make_folds(n, RLSettings(n_folds=2, min_train_frac=0.5))
    n_fit = wf.split_validation(folds[0].train_hi - folds[0].train_lo, RLSettings())
    rows = np.arange(n)
    data.features["f7"] = np.where((rows > n_fit) & (rows < folds[0].train_hi), np.sign(data.fwd_ret) * 3.0, 0.0)
    result = _run(data, _cfg(n_folds=2, max_features=3, feature_selection="correlation"), lambda obs: 1.0, spy=spy)
    first = result["folds"][0]
    assert spy[0]["core"].n == spy[0]["end"] == first["n_fit"] == n_fit and callable(spy[0]["validate"])
    assert "f7" not in first["features"] and first["n_val"] == first["n_train"] - first["n_fit"] - 1
    assert pd.Timestamp(first["val_start"]) > pd.Timestamp(first["fit_end"])
    assert pd.Timestamp(first["train_end"]) < pd.Timestamp(first["test_start"])


def test_an_agent_that_loses_to_buy_and_hold_in_validation_is_replaced_by_buy_and_hold():
    data = _data(drift=0.001, vol=0.002, seed=5)                                                    # marché haussier : rester à plat perd en validation
    result = _run(data, _cfg(), lambda obs: 0.0)
    assert all(f["gated"] and f["val_score"] < 0 for f in result["folds"])
    assert (result["oos"]["position"] == 1.0).all() and result["strategy"]["agent_share"] == 0.0
    assert result["agent_ungated"]["exposure"] == 0.0                                    # l'agent lui-même reste publié
    assert any("aucun pli" in d for d in result["diagnostics"])
    assert result["strategy"]["total_return"] == pytest.approx(result["baselines"]["buy_hold"]["total_return"], abs=2e-3)


def test_an_agent_that_beats_buy_and_hold_in_validation_keeps_control():
    data = _data(seed=6, signal=True)
    cfg = _cfg(rebalance_every=1, cost_bps=0.0, slippage_bps=0.0)
    result = _run(data, cfg, lambda obs: 1.0 if obs[0] > 0 else 0.0)                     # f0 (oracle) est la première colonne
    assert not any(f["gated"] for f in result["folds"]) and all(f["val_score"] > 0 for f in result["folds"])
    assert result["strategy"]["agent_share"] == 1.0
    assert np.array_equal(result["oos"]["position"], result["oos"]["agent_position"])


def test_without_fallback_the_agent_keeps_control_even_when_it_loses():
    data = _data(drift=0.001, vol=0.002, seed=5)
    result = _run(data, _cfg(gate=False), lambda obs: 0.0)
    assert not any(f["gated"] for f in result["folds"]) and (result["oos"]["position"] == 0.0).all()
    assert all(f["val_score"] is not None for f in result["folds"])                     # la validation choisit encore le point de contrôle


# --------------------------------------------------------------------------- références et diagnostics


def test_the_trend_baseline_is_causal_long_only_and_flat_before_200_bars():
    data = _data(seed=7)
    price = data.price.reset_index(drop=True)
    rows = np.arange(0, 900)
    pos = wf.trend_positions(price, rows, RLSettings())
    assert set(np.unique(pos)) <= {0.0, 1.0} and (pos[:199] == 0.0).all()
    altered = price.copy()
    altered.iloc[900:] *= 5.0
    assert np.array_equal(pos, wf.trend_positions(altered, rows, RLSettings()))
    result = _run(data, _cfg(), lambda obs: 1.0)
    assert "trend" in result["baselines"] and "vs_trend" in result["stats"] and len(result["curves"]["trend"]) == len(result["curves"]["dates"])


def test_the_delay_test_flags_same_day_information_and_spares_a_persistent_signal():
    rng = np.random.default_rng(8)
    ret = rng.normal(0.0002, 0.01, 2000)
    leak = wf.delay_test(np.sign(ret), ret)                                              # connaît le rendement du jour même
    assert leak["suspect"] and leak["gross_sharpe"] > 5 and leak["lagged_sharpe"] < 1
    trend = np.repeat(rng.choice([-1.0, 1.0], 40), 50)                                    # régimes de 50 jours
    persistent = trend * 0.004 + rng.normal(0, 0.01, 2000)
    kept = wf.delay_test(trend, persistent)
    assert not kept["suspect"] and kept["lagged_sharpe"] > 0.8 * kept["gross_sharpe"]
    assert not wf.delay_test(np.ones(2000), ret)["suspect"]                              # Sharpe brut modeste : test non armé


def test_a_same_day_leak_is_reported_with_the_results():
    data = _data(seed=9, signal=True)
    cfg = _cfg(rebalance_every=1, cost_bps=0.0, slippage_bps=0.0, gate=False)
    result = _run(data, cfg, lambda obs: 1.0 if obs[0] > 0 else -0.0)
    assert result["stats"]["delay"]["suspect"] and any("décalées d'un jour" in d for d in result["diagnostics"])


def test_the_summary_decomposes_gross_return_costs_and_legs():
    dates = pd.bdate_range("2020-01-01", periods=4)
    from patrick.rl import metrics as rl_metrics
    m = rl_metrics.summarize(np.array([0.009, -0.02, 0.028, 0.0]), np.array([1.0, 1.0, -1.0, 0.0]), np.array([0.001, 0.0, 0.002, 0.0]), dates)
    assert m["gross_return_ann"] == pytest.approx((0.010 - 0.02 + 0.030) / 4 * 252)
    assert m["cost_ann"] == pytest.approx(0.003 / 4 * 252)
    assert m["long_contrib_ann"] == pytest.approx((0.010 - 0.02) / 4 * 252) and m["short_contrib_ann"] == pytest.approx(0.030 / 4 * 252)


def test_a_fresh_run_applies_todays_session_rule_so_fx_bars_cannot_leak(monkeypatch, tmp_path):
    from patrick.data.session_calendar import CURRENT_SESSION_RULE
    from patrick.rl import agents
    from patrick.rl import run as rl_run
    seen = {}

    class Stop(Exception):
        pass

    def fake_ingest(objective, *a, **k):
        seen["rule"] = objective.session_rule
        raise Stop

    monkeypatch.setattr(agents, "require_rl", lambda: None)
    monkeypatch.setattr(rl_run, "ingest", fake_ingest)
    cfg = RLRunConfig.model_validate({"objective": {"target_symbol": "EURUSD=X"}, "output": {"dir": str(tmp_path)}})
    assert cfg.objective.session_rule == 1
    with pytest.raises(Stop):
        rl_run.run_rl(cfg, store=object())
    assert seen["rule"] == CURRENT_SESSION_RULE >= 2


def test_an_old_fx_run_is_flagged_when_displayed_and_a_new_one_is_not():
    from patrick.rl.history import FX_ALIGNMENT_WARNING, display_warnings
    old = {"kind": "rl", "target": "AUDUSD=X", "warnings": ["autre"],
           "config": {"objective": {"target_symbol": "AUDUSD=X", "target_source": "yfinance", "session_rule": 1}}}
    shown = display_warnings(old)
    assert shown["warnings"] == [FX_ALIGNMENT_WARNING, "autre"] and old["warnings"] == ["autre"]
    assert display_warnings(shown)["warnings"].count(FX_ALIGNMENT_WARNING) == 1
    new = {**old, "config": {"objective": {**old["config"]["objective"], "session_rule": 2}}}
    assert display_warnings(new)["warnings"] == ["autre"]
    gspc = {"kind": "rl", "target": "^GSPC", "config": {"objective": {"target_symbol": "^GSPC", "session_rule": 1}}}
    assert display_warnings(gspc) is gspc and display_warnings({"kind": "ml"}) == {"kind": "ml"}
