"""Agents de reinforcement learning (Stable-Baselines3 : PPO, A2C, DQN, SAC). PyTorch, Gymnasium et Stable-Baselines3 sont des
dépendances OPTIONNELLES (`pip install -e .[rl]`) : rien ici n'est importé avant l'entraînement, et leur absence produit un message clair
(`RLUnavailableError`) au lancement plutôt qu'une erreur d'import au démarrage de l'application."""
from __future__ import annotations

import importlib.util
from collections.abc import Callable

import numpy as np

from patrick.rl.config import RLSettings
from patrick.rl.core import TradingCore


class RLUnavailableError(RuntimeError):
    """PyTorch, Gymnasium ou Stable-Baselines3 manque : message affichable tel quel."""


def rl_available() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "gymnasium", "stable_baselines3"))


def require_rl() -> None:
    missing = [m for m in ("torch", "gymnasium", "stable_baselines3") if importlib.util.find_spec(m) is None]
    if missing:
        raise RLUnavailableError(
            "Reinforcement learning indisponible : " + ", ".join(missing) + " non installé. "
            "Installe-les avec : pip install -e \".[rl]\" (ou pip install torch gymnasium stable-baselines3).")


def _device(settings: RLSettings):
    import torch
    if settings.device == "cpu":
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def build_model(env, settings: RLSettings, seed: int):
    """Modèle Stable-Baselines3 sur `env`, avec les réglages de `settings` (ceux d'un autre algorithme sont ignorés)."""
    require_rl()
    import torch
    from stable_baselines3 import A2C, DQN, PPO, SAC

    if torch.get_num_threads() != int(settings.threads):
        torch.set_num_threads(int(settings.threads))
    act = torch.nn.Tanh if settings.activation == "tanh" else torch.nn.ReLU
    net = [int(settings.policy_units)] * int(settings.policy_layers)
    common = {"learning_rate": float(settings.learning_rate), "gamma": float(settings.gamma), "seed": int(seed),
              "device": _device(settings), "verbose": 0, "policy_kwargs": {"net_arch": net, "activation_fn": act}}
    algo = settings.algo
    if algo == "PPO":
        n_steps = int(settings.n_steps)
        return PPO("MlpPolicy", env, n_steps=n_steps, batch_size=min(int(settings.batch_size), n_steps), n_epochs=int(settings.n_epochs),
                   ent_coef=float(settings.ent_coef), clip_range=float(settings.clip_range), gae_lambda=float(settings.gae_lambda), **common)
    if algo == "A2C":
        return A2C("MlpPolicy", env, n_steps=int(settings.n_steps), ent_coef=float(settings.ent_coef),
                   gae_lambda=float(settings.gae_lambda), **common)
    if algo == "DQN":
        return DQN("MlpPolicy", env, buffer_size=int(settings.buffer_size), learning_starts=int(settings.learning_starts),
                   batch_size=int(settings.batch_size), train_freq=int(settings.train_freq),
                   target_update_interval=int(settings.target_update_interval),
                   exploration_fraction=float(settings.exploration_fraction), **common)
    if algo == "SAC":
        return SAC("MlpPolicy", env, buffer_size=int(settings.buffer_size), learning_starts=int(settings.learning_starts),
                   batch_size=int(settings.batch_size), train_freq=int(settings.train_freq), tau=float(settings.tau), **common)
    raise ValueError(f"Algorithme inconnu : {algo}")


VAL_CHECKS = 10          # contrôles de validation pendant l'entraînement (le meilleur point de contrôle est gardé)


def train_agent(core: TradingCore, settings: RLSettings, seed: int, start: int, end: int,
                on_progress: Callable[[int, int], None] | None = None,
                validate: Callable[[Callable[[np.ndarray], float]], float] | None = None):
    """Entraîne un agent sur les lignes [start, end) de `core` pendant `settings.total_timesteps` pas. `on_progress(fait, total)` est
    appelé périodiquement (nombre de pas).

    `validate(politique) -> score` (plus haut = meilleur), s'il est fourni, est appelé `VAL_CHECKS` fois pendant l'entraînement et à la fin ;
    les poids du meilleur contrôle sont rechargés avant de rendre le modèle (arrêt précoce sans couper l'entraînement : sur un signal faible,
    plus d'entraînement apprend le bruit -- moteur 1 : 80 000 pas faisaient pire que 30 000). Le détail est dans `model.patrick_validation`."""
    require_rl()
    import copy

    from stable_baselines3.common.callbacks import BaseCallback

    from patrick.rl.env import TradingEnv

    env = TradingEnv(core, settings, start=start, end=end, seed=seed)
    model = build_model(env, settings, seed)
    total = int(settings.total_timesteps)
    every = max(total // VAL_CHECKS, 1)
    track: dict = {"best_score": None, "best_step": None, "scores": [], "state": None}

    def check(step: int) -> None:
        score = float(validate(policy_from_model(model, settings)))
        track["scores"].append([int(step), score if np.isfinite(score) else None])
        if np.isfinite(score) and (track["best_score"] is None or score > track["best_score"]):
            track.update(best_score=score, best_step=int(step), state=copy.deepcopy(model.policy.state_dict()))

    class _Progress(BaseCallback):
        def __init__(self):
            super().__init__()
            self._next = 0
            self._next_check = every

        def _on_step(self) -> bool:
            if on_progress is not None and self.num_timesteps >= self._next:
                on_progress(self.num_timesteps, total)
                self._next = self.num_timesteps + max(total // 20, 500)
            if validate is not None and self.num_timesteps >= self._next_check:
                check(self.num_timesteps)
                self._next_check += every
            return True

    model.learn(total_timesteps=total, callback=_Progress())
    if validate is not None:
        if not track["scores"] or track["scores"][-1][0] < model.num_timesteps:
            check(model.num_timesteps)
        if track["state"] is not None:
            model.policy.load_state_dict(track["state"])
    model.patrick_validation = {k: v for k, v in track.items() if k != "state"}
    return model


def policy_from_model(model, settings: RLSettings) -> Callable[[np.ndarray], float]:
    """`obs -> position cible`, déterministe (pas d'exploration en évaluation)."""
    from patrick.rl.env import action_to_position

    def policy(obs: np.ndarray) -> float:
        action, _state = model.predict(np.asarray(obs, dtype=np.float32), deterministic=True)
        return action_to_position(action, settings)

    return policy


def validation_info(model) -> dict | None:
    """Détail de la validation d'un agent entraîné par `train_agent` (meilleur score, pas du meilleur contrôle, scores), ou None."""
    return getattr(model, "patrick_validation", None)


def ensemble_policy(policies: list[Callable[[np.ndarray], float]]) -> Callable[[np.ndarray], float]:
    """Position moyenne de plusieurs agents (graines différentes) : chacun voit la même observation, y compris la position
    réellement tenue par l'ensemble."""
    if len(policies) == 1:
        return policies[0]
    return lambda obs: float(np.mean([p(obs) for p in policies]))
