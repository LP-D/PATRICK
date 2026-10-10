"""Mécanique de l'environnement de trading, en NumPy pur (ni Gymnasium ni PyTorch) : testable seule, réutilisée telle quelle par
l'évaluation hors échantillon et par l'enveloppe Gymnasium (`rl/env.py`).

Chronologie, sans regard vers l'avenir : à la date t, l'agent voit les variables de t (calculées avec l'information disponible en t)
et sa position précédente ; il choisit une position cible ; le rendement qu'il touche est celui de t à t+1 (`fwd_ret[t]`), moins les
coûts du changement de position. Aucune observation ne contient `fwd_ret`.

Récompenses (échelonnées par `reward_scale = 1 / écart-type des rendements d'entraînement`, pour que l'ordre de grandeur soit ~1) :
- `pnl` : rendement net · échelle ;
- `log` : log(1 + rendement net) · échelle (la croissance du capital) ;
- `dsr` : ratio de Sharpe différentiel de Moody & Saffell (1998), la variation instantanée du Sharpe exponentiellement pondéré.
Le terme `risk_aversion · (rendement net · échelle)²` est retiré aux récompenses `pnl` et `log`.
"""
from __future__ import annotations

import math

import numpy as np

from patrick.rl.config import RLSettings

REWARD_CLIP = 10.0
OBS_CLIP = 5.0


class TradingCore:
    def __init__(self, features: np.ndarray, fwd_ret: np.ndarray, settings: RLSettings, reward_scale: float):
        features = np.asarray(features, dtype=np.float32)
        fwd_ret = np.asarray(fwd_ret, dtype=np.float64)
        if features.ndim != 2 or len(features) != len(fwd_ret):
            raise ValueError("features (n, k) et fwd_ret (n,) doivent avoir le même nombre de lignes")
        self.features = np.clip(np.nan_to_num(features, nan=0.0, posinf=OBS_CLIP, neginf=-OBS_CLIP), -OBS_CLIP, OBS_CLIP)
        self.fwd_ret = fwd_ret
        self.s = settings
        self.scale = float(reward_scale)
        self.n = len(fwd_ret)
        self.n_features = features.shape[1]
        self.obs_dim = self.n_features * int(settings.obs_lookback) + (1 if settings.include_position else 0)
        self.fee = (float(settings.cost_bps) + float(settings.slippage_bps)) / 1e4
        self.t = 0
        self.end = self.n
        self.pos = 0.0
        self._a = 0.0
        self._b = 0.0

    # ------------------------------------------------------------------ épisodes
    def reset(self, start: int = 0, end: int | None = None, prev_pos: float = 0.0) -> np.ndarray:
        self.t = int(start)
        self.end = self.n if end is None else int(end)
        if not 0 <= self.t < self.end <= self.n:
            raise ValueError("intervalle d'épisode invalide")
        self.pos = float(prev_pos)
        self._a = 0.0
        self._b = 0.0
        return self.observation()

    def observation(self) -> np.ndarray:
        """Variables de t (et des `obs_lookback − 1` lignes précédentes), puis la position courante rapportée au levier maximal."""
        lb = int(self.s.obs_lookback)
        t = min(self.t, self.n - 1)           # après le dernier pas d'un épisode : la dernière observation connue (bootstrap de valeur)
        if lb == 1:
            rows = self.features[t]
        else:
            idx = np.clip(np.arange(t - lb + 1, t + 1), 0, None)
            rows = self.features[idx].reshape(-1)
        if self.s.include_position:
            rows = np.append(rows, np.float32(self.pos / self.s.max_leverage))
        return rows.astype(np.float32, copy=False)

    # ------------------------------------------------------------------ une période
    def step(self, target_pos: float) -> tuple[float, float, float, bool]:
        """Prend la position `target_pos` à la date t. Retourne (récompense, coût, rendement net, fin d'épisode)."""
        lev = float(self.s.max_leverage)
        target = float(np.clip(target_pos, -lev if self.s.allow_short else 0.0, lev))
        cost = abs(target - self.pos) * self.fee
        net = target * self.fwd_ret[self.t] - cost
        scaled = net * self.scale
        if self.s.reward == "dsr":
            reward = self._dsr(scaled)
        elif self.s.reward == "log":
            reward = math.log1p(max(net, -0.999)) * self.scale - self.s.risk_aversion * scaled * scaled
        else:
            reward = scaled - self.s.risk_aversion * scaled * scaled
        self.pos = target
        self.t += 1
        return float(np.clip(reward, -REWARD_CLIP, REWARD_CLIP)), float(cost), float(net), self.t >= self.end

    def _dsr(self, r: float) -> float:
        eta = float(self.s.dsr_eta)
        a, b = self._a, self._b
        da, db = r - a, r * r - b
        var = b - a * a
        d = (b * da - 0.5 * a * db) / (var ** 1.5) if var > 1e-8 else 0.0
        self._a, self._b = a + eta * da, b + eta * db
        return float(d)


def rollout(core: TradingCore, policy, start: int, end: int, prev_pos: float = 0.0) -> dict:
    """Rejoue `policy(obs) -> position cible` du début à la fin (déterministe, séquentiel) : positions, rendements nets, coûts."""
    obs = core.reset(start, end, prev_pos)
    positions, net, costs = [], [], []
    done = False
    while not done:
        target = float(policy(obs))
        _reward, cost, ret, done = core.step(target)
        positions.append(core.pos)
        net.append(ret)
        costs.append(cost)
        if not done:
            obs = core.observation()
    return {"positions": np.asarray(positions), "net_returns": np.asarray(net), "costs": np.asarray(costs)}
