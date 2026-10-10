"""Enveloppe Gymnasium de `rl/core.TradingCore`. Importe Gymnasium : n'est chargée qu'à l'entraînement (`rl/agents.py`)."""
from __future__ import annotations

from typing import ClassVar

import gymnasium as gym
import numpy as np

from patrick.rl.config import RLSettings
from patrick.rl.core import TradingCore


def action_to_position(action, settings: RLSettings) -> float:
    """Action de l'agent -> position cible. Discrète : un des niveaux de `RLSettings.positions()`. Continue : a ∈ [−1, 1] ;
    à découvert autorisé, position = a · levier ; sinon position = (a + 1)/2 · levier (tout l'intervalle sert, rien n'est « coupé »)."""
    if settings.action_space == "discrete":
        return float(settings.positions()[int(np.asarray(action).reshape(-1)[0])])
    a = float(np.clip(np.asarray(action, dtype=np.float64).reshape(-1)[0], -1.0, 1.0))
    return a * settings.max_leverage if settings.allow_short else (a + 1.0) / 2.0 * settings.max_leverage


class TradingEnv(gym.Env):
    """Un épisode = un segment d'historique rejoué dans l'ordre. En entraînement, de longueur `episode_length` à un point de départ
    tiré au hasard (diversité), ou tout le segment si `episode_length = 0` ; la fin d'un épisode est une TRONCATURE (limite de temps),
    pas une fin de partie : la valeur future est donc estimée, jamais forcée à zéro."""

    metadata: ClassVar[dict] = {"render_modes": []}

    def __init__(self, core: TradingCore, settings: RLSettings, start: int = 0, end: int | None = None, seed: int | None = None):
        super().__init__()
        self.core, self.s = core, settings
        self.lo, self.hi = int(start), int(core.n if end is None else end)
        self._rng = np.random.default_rng(seed)
        if settings.action_space == "discrete":
            self.action_space = gym.spaces.Discrete(len(settings.positions()))
        else:
            self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(1,), dtype=np.float32)
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, shape=(core.obs_dim,), dtype=np.float32)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        span = self.hi - self.lo
        length = int(self.s.episode_length)
        if length <= 0 or length >= span:
            start, end = self.lo, self.hi
        elif self.s.random_start:
            start = self.lo + int(self._rng.integers(0, span - length + 1))
            end = start + length
        else:
            start, end = self.lo, self.lo + length
        return self.core.reset(start, end, prev_pos=0.0), {}

    def step(self, action):
        reward, cost, net, done = self.core.step(action_to_position(action, self.s))
        return self.core.observation(), reward, False, done, {"cost": cost, "net_return": net}
