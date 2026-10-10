"""Mécanique de l'environnement RL (`rl/core.py`, `rl/env.py`) : chronologie sans regard vers l'avenir, coûts, récompenses, positions.
La partie NumPy tourne sans PyTorch ; l'enveloppe Gymnasium est testée si Gymnasium est installé."""
from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from patrick.rl.config import RLRunConfig, RLSettings
from patrick.rl.core import REWARD_CLIP, TradingCore, rollout


def _core(n=60, k=3, seed=0, **over):
    rng = np.random.default_rng(seed)
    s = RLSettings(**{"cost_bps": 10.0, "slippage_bps": 0.0, "reward": "pnl", **over})
    return TradingCore(rng.normal(size=(n, k)), rng.normal(0, 0.01, n), s, reward_scale=100.0), s


# --------------------------------------------------------------------------- positions


@pytest.mark.parametrize("over, expected", [
    ({"n_levels": 3}, [-1.0, 0.0, 1.0]),
    ({"n_levels": 5}, [-1.0, -0.5, 0.0, 0.5, 1.0]),
    ({"n_levels": 3, "allow_short": False}, [0.0, 0.5, 1.0]),
    ({"n_levels": 2, "allow_short": False}, [0.0, 1.0]),
    ({"n_levels": 3, "max_leverage": 2.0}, [-2.0, 0.0, 2.0]),
])
def test_discrete_positions_follow_the_levels_the_shorting_flag_and_the_leverage(over, expected):
    assert RLSettings(**over).positions() == pytest.approx(expected)


def test_algorithms_and_action_spaces_must_be_compatible():
    with pytest.raises(ValidationError, match="DQN"):
        RLSettings(algo="DQN", action_space="continuous")
    with pytest.raises(ValidationError, match="SAC"):
        RLSettings(algo="SAC", action_space="discrete")
    with pytest.raises(ValidationError, match="n_steps"):
        RLSettings(algo="PPO", n_steps=64, batch_size=128)
    assert RLSettings(algo="SAC", action_space="continuous").algo == "SAC"
    assert RLSettings(algo="A2C", n_steps=64, batch_size=128).algo == "A2C"


@pytest.mark.parametrize("field, value", [("cost_bps", -1), ("max_leverage", 0), ("learning_rate", 5.0), ("gamma", 1.5), ("n_folds", 0),
                                          ("total_timesteps", 10), ("n_levels", 1), ("min_train_frac", 0.95)])
def test_settings_outside_their_bounds_are_refused(field, value):
    with pytest.raises(ValidationError):
        RLSettings(**{field: value})


def test_a_run_config_refuses_what_has_no_position_to_trade():
    base = {"objective": {"target_symbol": "^GSPC"}}
    assert RLRunConfig.model_validate(base).name == "IDX_GSPC_rl" and RLRunConfig.model_validate(base).kind == "rl"
    with pytest.raises(ValidationError, match="FRED"):
        RLRunConfig.model_validate({"objective": {"target_symbol": "CPIAUCSL", "target_source": "fred"}})
    with pytest.raises(ValidationError, match="alpha"):
        RLRunConfig.model_validate({"objective": {"target_symbol": "AAPL", "target_kind": "alpha", "benchmark": "^GSPC"}})
    with pytest.raises(ValidationError, match="famille"):
        RLRunConfig.model_validate({**base, "features": {"families": ["vol_models", "interactions"]}})


def test_only_causal_families_reach_the_feature_builder():
    cfg = RLRunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}, "features": {"families": ["technical", "vol_models", "interactions", "macro"]}})
    assert cfg.feature_families() == ["technical", "macro"]
    assert cfg.to_run_config().features.families == ["technical", "macro"]


# --------------------------------------------------------------------------- coûts et récompenses


def test_entering_a_position_pays_the_cost_once_and_holding_it_pays_nothing():
    core, _ = _core(cost_bps=10.0, slippage_bps=5.0)
    core.reset(0, 10)
    r1, cost1, net1, _ = core.step(1.0)
    assert cost1 == pytest.approx(15e-4) and net1 == pytest.approx(core.fwd_ret[0] - 15e-4)
    assert r1 == pytest.approx(net1 * 100.0)
    _, cost2, net2, _ = core.step(1.0)
    assert cost2 == 0.0 and net2 == pytest.approx(core.fwd_ret[1])


def test_flipping_from_long_to_short_pays_twice_the_cost():
    core, _ = _core(cost_bps=10.0, slippage_bps=0.0)
    core.reset(0, 10, prev_pos=1.0)
    _, cost, net, _ = core.step(-1.0)
    assert cost == pytest.approx(2 * 10e-4) and net == pytest.approx(-core.fwd_ret[0] - 20e-4)


def test_a_short_position_earns_when_the_price_falls():
    core, _ = _core(cost_bps=0.0, slippage_bps=0.0)
    core.fwd_ret[:] = -0.02
    core.reset(0, 5)
    assert core.step(-1.0)[2] == pytest.approx(0.02)


def test_long_only_clips_negative_targets_and_the_leverage_caps_the_position():
    core, _ = _core(allow_short=False, max_leverage=1.5)
    core.reset(0, 5)
    core.step(-1.0)
    assert core.pos == 0.0
    core.step(9.0)
    assert core.pos == pytest.approx(1.5)


def test_the_episode_ends_exactly_at_the_end_index_and_never_reads_past_it():
    core, _ = _core(n=20)
    core.reset(5, 8)
    flags = [core.step(0.0)[3] for _ in range(3)]
    assert flags == [False, False, True] and core.t == 8
    last = core.observation()
    assert last.shape == (core.obs_dim,)
    with pytest.raises(ValueError):
        core.reset(10, 5)


def test_log_reward_matches_the_scaled_return_for_small_moves_and_risk_aversion_lowers_it():
    base, _ = _core(reward="log", cost_bps=0.0)
    base.reset(0, 5)
    r_log, _, net, _ = base.step(1.0)
    assert r_log == pytest.approx(math.log1p(net) * 100.0)
    averse, _ = _core(reward="log", cost_bps=0.0, risk_aversion=0.5)
    averse.reset(0, 5)
    assert averse.step(1.0)[0] < r_log


def test_rewards_are_clipped():
    core, _ = _core(reward="pnl", cost_bps=0.0)
    core.fwd_ret[:] = 0.5
    core.reset(0, 5)
    assert core.step(1.0)[0] == REWARD_CLIP


def test_the_differential_sharpe_reward_is_positive_for_a_better_than_usual_period_and_safe_without_variance():
    core, _ = _core(reward="dsr", cost_bps=0.0, dsr_eta=0.1, n=40)
    rng = np.random.default_rng(5)
    core.fwd_ret[:] = 0.001 + rng.normal(0, 0.002, 40)
    core.fwd_ret[8] = 0.004                         # une période nettement au-dessus de la moyenne, sans être aberrante
    core.fwd_ret[10] = -0.004                       # et une nettement en dessous
    core.reset(0, 20)
    rewards = [core.step(1.0)[0] for _ in range(12)]
    assert rewards[8] > 0 > rewards[10] and all(abs(r) <= REWARD_CLIP for r in rewards)
    flat, _ = _core(reward="dsr", cost_bps=0.0, n=40)
    flat.fwd_ret[:] = 0.0
    flat.reset(0, 20)
    assert [flat.step(1.0)[0] for _ in range(5)] == [0.0] * 5      # aucune variance : récompense neutre, jamais d'explosion


# --------------------------------------------------------------------------- aucun regard vers l'avenir


def test_the_observation_never_contains_the_return_it_is_about_to_earn():
    a, _ = _core(seed=1)
    b, _ = _core(seed=1)
    b.fwd_ret[:] = b.fwd_ret[::-1] * 7.0                      # autres rendements futurs, mêmes variables
    for t in (0, 10, 30):
        a.reset(t, 40)
        b.reset(t, 40)
        assert np.array_equal(a.observation(), b.observation())


def test_the_observation_at_t_only_depends_on_rows_up_to_t():
    a, _ = _core(seed=2, obs_lookback=4)
    b, _ = _core(seed=2, obs_lookback=4)
    t = 20
    b.features[t + 1:] = 99.0                                 # l'avenir change, le présent non
    a.reset(t, 40)
    b.reset(t, 40)
    assert np.array_equal(a.observation(), b.observation())
    assert a.obs_dim == 3 * 4 + 1


def test_a_lookback_at_the_start_repeats_the_first_row_instead_of_wrapping_around():
    core, _ = _core(obs_lookback=3, include_position=False)
    core.reset(0, 10)
    obs = core.observation().reshape(3, 3)
    assert np.array_equal(obs[0], core.features[0]) and np.array_equal(obs[2], core.features[0])


def test_the_position_enters_the_observation_scaled_by_the_leverage():
    core, _ = _core(max_leverage=2.0)
    core.reset(0, 10)
    core.step(2.0)
    assert core.observation()[-1] == pytest.approx(1.0)
    off, _ = _core(include_position=False)
    off.reset(0, 5)
    assert off.obs_dim == 3


def test_features_are_clipped_and_cleaned_on_entry():
    rng = np.random.default_rng(0)
    feats = rng.normal(size=(30, 2))
    feats[3, 0], feats[4, 1], feats[5, 0] = np.nan, np.inf, 1e9
    core = TradingCore(feats, rng.normal(0, 0.01, 30), RLSettings(), 100.0)
    assert np.isfinite(core.features).all() and np.abs(core.features).max() <= 5.0


def test_mismatched_inputs_are_refused():
    with pytest.raises(ValueError, match="même nombre"):
        TradingCore(np.zeros((10, 2)), np.zeros(9), RLSettings(), 1.0)


# --------------------------------------------------------------------------- rollout


def test_a_constant_long_policy_earns_the_asset_minus_one_entry_cost():
    core, _ = _core(n=50, cost_bps=10.0)
    out = rollout(core, lambda obs: 1.0, 10, 40)
    assert (out["positions"] == 1.0).all() and len(out["net_returns"]) == 30
    assert out["costs"][0] == pytest.approx(10e-4) and out["costs"][1:].sum() == 0.0
    assert out["net_returns"][1:] == pytest.approx(core.fwd_ret[11:40])


def test_the_policy_sees_the_position_it_actually_holds():
    core, _ = _core(n=30, cost_bps=0.0)
    seen = []

    def policy(obs):
        seen.append(float(obs[-1]))
        return 1.0 if len(seen) % 2 else -1.0

    rollout(core, policy, 0, 6)
    assert seen == [0.0, 1.0, -1.0, 1.0, -1.0, 1.0]


# --------------------------------------------------------------------------- enveloppe Gymnasium


gym = pytest.importorskip("gymnasium")


def test_the_gymnasium_env_follows_the_api_and_truncates_at_the_episode_end():
    from patrick.rl.env import TradingEnv
    core, s = _core(n=80, episode_length=20, random_start=False)
    env = TradingEnv(core, s, start=0, end=80, seed=1)
    obs, info = env.reset(seed=1)
    assert obs.shape == env.observation_space.shape and info == {}
    done_at = None
    for i in range(1, 40):
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        assert terminated is False and obs.shape == env.observation_space.shape and "cost" in info
        if truncated:
            done_at = i
            break
    assert done_at == 20


def test_random_episode_starts_stay_inside_the_training_segment():
    from patrick.rl.env import TradingEnv
    core, s = _core(n=200, episode_length=30, random_start=True)
    env = TradingEnv(core, s, start=50, end=120, seed=3)
    starts = set()
    for _ in range(60):
        env.reset()
        starts.add(core.t)
        assert 50 <= core.t and core.end <= 120 and core.end - core.t == 30
    assert len(starts) > 10


def test_actions_map_to_positions_for_both_action_spaces():
    from patrick.rl.env import action_to_position
    d = RLSettings(action_space="discrete", n_levels=3)
    assert [action_to_position(a, d) for a in (0, 1, 2)] == [-1.0, 0.0, 1.0]
    c_short = RLSettings(action_space="continuous", algo="SAC")
    assert action_to_position(np.array([0.4]), c_short) == pytest.approx(0.4) and action_to_position(np.array([5.0]), c_short) == 1.0
    c_long = RLSettings(action_space="continuous", algo="SAC", allow_short=False, max_leverage=2.0)
    assert action_to_position(np.array([-1.0]), c_long) == 0.0 and action_to_position(np.array([1.0]), c_long) == pytest.approx(2.0)


def test_the_env_passes_the_gymnasium_checker_for_both_action_spaces():
    from gymnasium.utils.env_checker import check_env

    from patrick.rl.env import TradingEnv
    for over in ({}, {"action_space": "continuous", "algo": "SAC"}):
        core, s = _core(n=100, episode_length=25, **over)
        check_env(TradingEnv(core, s, start=0, end=100, seed=0), skip_render_check=True)
