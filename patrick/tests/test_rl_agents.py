"""Agents RL (`rl/agents.py`, Stable-Baselines3) : les quatre algorithmes s'entraînent et rendent une position valide ; un agent APPREND quand
l'observation contient un signal ; la graine rend l'entraînement reproductible. Ignoré si PyTorch, Gymnasium ou Stable-Baselines3 manquent."""
from __future__ import annotations

import importlib.util

import numpy as np
import pytest

for _module in ("torch", "gymnasium", "stable_baselines3"):
    if importlib.util.find_spec(_module) is None:
        pytest.skip(f"{_module} non installé (extra optionnel rl)", allow_module_level=True)

from patrick.rl import agents
from patrick.rl.config import RLSettings
from patrick.rl.core import TradingCore, rollout

FAST = {"total_timesteps": 1500, "n_steps": 64, "batch_size": 32, "n_epochs": 2, "policy_units": 16, "policy_layers": 1,
        "buffer_size": 3000, "learning_starts": 100, "train_freq": 4, "target_update_interval": 100, "episode_length": 60}


def _core(settings: RLSettings, n=400, seed=0, oracle=False):
    rng = np.random.default_rng(seed)
    fwd = rng.normal(0.0003, 0.01, n)
    feats = rng.normal(size=(n, 4))
    if oracle:
        feats[:, 0] = np.sign(fwd) * 2.0                    # le signe du rendement SUIVANT (pour vérifier que l'agent sait apprendre)
    return TradingCore(feats, fwd, settings, 1.0 / fwd.std()), fwd


@pytest.mark.parametrize("over", [
    {"algo": "PPO"}, {"algo": "A2C"}, {"algo": "DQN"}, {"algo": "SAC", "action_space": "continuous"},
    {"algo": "PPO", "action_space": "continuous"}, {"algo": "PPO", "allow_short": False, "activation": "relu"},
])
def test_every_algorithm_trains_and_returns_a_valid_position(over):
    s = RLSettings(**{**FAST, **over})
    core, _ = _core(s)
    model = agents.train_agent(core, s, seed=1, start=0, end=300)
    policy = agents.policy_from_model(model, s)
    out = rollout(core, policy, 300, 400)
    lo = -1.0 if s.allow_short else 0.0
    assert len(out["positions"]) == 100 and np.isfinite(out["net_returns"]).all()
    assert out["positions"].min() >= lo - 1e-9 and out["positions"].max() <= 1.0 + 1e-9


def test_an_agent_learns_to_follow_a_signal_that_is_in_its_observation():
    s = RLSettings(**{**FAST, "total_timesteps": 8000, "n_steps": 256, "batch_size": 64, "learning_rate": 1e-3, "cost_bps": 0.0,
                      "slippage_bps": 0.0, "reward": "pnl", "ent_coef": 0.0, "episode_length": 100, "policy_units": 32})
    core, fwd = _core(s, n=600, seed=2, oracle=True)
    model = agents.train_agent(core, s, seed=3, start=0, end=450)
    out = rollout(core, agents.policy_from_model(model, s), 450, 600)
    pnl = out["positions"] * fwd[450:600]
    assert pnl.mean() > 0 and (np.sign(out["positions"]) == np.sign(fwd[450:600])).mean() > 0.65


def test_the_same_seed_gives_the_same_trained_agent():
    s = RLSettings(**FAST)
    core, _ = _core(s)
    a = rollout(core, agents.policy_from_model(agents.train_agent(core, s, 5, 0, 300), s), 300, 360)["positions"]
    b = rollout(core, agents.policy_from_model(agents.train_agent(core, s, 5, 0, 300), s), 300, 360)["positions"]
    assert np.array_equal(a, b)


def test_training_reports_progress_through_the_callback():
    s = RLSettings(**FAST)
    core, _ = _core(s)
    seen: list[tuple[int, int]] = []
    agents.train_agent(core, s, 1, 0, 300, on_progress=lambda done, total: seen.append((done, total)))
    assert seen and seen[-1][1] == FAST["total_timesteps"] and seen == sorted(seen)


def test_the_ensemble_position_is_the_mean_of_the_agents():
    pol = agents.ensemble_policy([lambda o: 1.0, lambda o: 0.0, lambda o: -1.0, lambda o: 1.0])
    assert pol(np.zeros(3)) == pytest.approx(0.25)
    single = lambda o: 0.5
    assert agents.ensemble_policy([single]) is single


def test_a_missing_dependency_is_a_clear_error_not_an_import_crash(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(agents.importlib.util, "find_spec", lambda name, *a, **k: None if name == "stable_baselines3" else real(name, *a, **k))
    assert agents.rl_available() is False
    with pytest.raises(agents.RLUnavailableError, match="stable_baselines3"):
        agents.require_rl()
    s = RLSettings(**FAST)
    core, _ = _core(s)
    with pytest.raises(agents.RLUnavailableError, match="pip install"):
        agents.train_agent(core, s, 1, 0, 100)
