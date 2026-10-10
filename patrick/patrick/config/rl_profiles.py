"""Profils d'entraînement du reinforcement learning (page /rl) : même mécanique que `training_profiles` et `dl_profiles` -- un profil est un
PATCH sur la vue du formulaire (`webapp/forms_rl.py::to_view_rl`, clés plates `rl_<réglage>`), que l'utilisateur relit avant de lancer.

`cost` : durée relative d'un run (low ≈ 2-5 min, medium ≈ 10-30 min, high ≈ 1 h et plus) sur un processeur sans carte graphique.
"""
from __future__ import annotations

from patrick.config.training_profiles import TrainingProfile, apply_patch

__all__ = ["BY_KEY", "PROFILES", "apply_patch", "gallery", "get"]

PROFILES: tuple[TrainingProfile, ...] = (
    TrainingProfile("rl_quick", "low", {
        "rl_total_timesteps": 10000, "rl_n_folds": 3, "rl_policy_units": 32, "rl_policy_layers": 1, "rl_n_steps": 256,
        "rl_max_features": 10, "families": ["technical", "spike"]}, icon="zap"),
    TrainingProfile("rl_standard", "medium", {}, icon="layers"),
    TrainingProfile("rl_long_only", "medium", {"rl_allow_short": False}, icon="trending-up"),
    TrainingProfile("rl_risk_aware", "medium", {"rl_reward": "dsr", "rl_dsr_eta": 0.02}, icon="shield"),
    TrainingProfile("rl_costly", "medium", {
        "rl_cost_bps": 15.0, "rl_slippage_bps": 5.0, "rl_risk_aversion": 0.1, "rl_episode_length": 504}, icon="coins"),
    TrainingProfile("rl_continuous", "high", {
        "rl_algo": "SAC", "rl_action_space": "continuous", "rl_total_timesteps": 40000, "rl_learning_starts": 2000,
        "rl_batch_size": 128}, icon="activity"),
    TrainingProfile("rl_dqn", "medium", {
        "rl_algo": "DQN", "rl_action_space": "discrete", "rl_n_levels": 5, "rl_total_timesteps": 40000, "rl_learning_starts": 2000,
        "rl_batch_size": 64}, icon="layers"),
    TrainingProfile("rl_ensemble", "high", {"rl_n_seeds": 3, "rl_total_timesteps": 30000}, icon="layers"),
    TrainingProfile("rl_memory", "high", {
        "rl_obs_lookback": 20, "rl_policy_units": 128, "rl_policy_layers": 2, "rl_total_timesteps": 80000, "rl_max_features": 12},
        icon="clock"),
    TrainingProfile("rl_prudent", "medium", {"rl_n_folds": 6, "rl_bootstrap_samples": 3000, "rl_retrain": "rolling", "rl_rolling_bars": 1500},
                    icon="eye"),
)

BY_KEY: dict[str, TrainingProfile] = {p.key: p for p in PROFILES}


def get(key: str) -> TrainingProfile | None:
    return BY_KEY.get(key)


def gallery(base_view: dict) -> list[dict]:
    """Profils avec le nombre de réglages qu'ils changent par rapport à la configuration de départ."""
    return [{"key": p.key, "cost": p.cost, "n_changes": sum(1 for k, v in p.patch.items() if base_view.get(k) != v)} for p in PROFILES]
