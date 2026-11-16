"""Configuration d'un run de reinforcement learning (`RLRunConfig`) : mêmes blocs de données que `RunConfig` (cible, univers, qualité,
familles de variables), plus un bloc `rl` (environnement, agent, validation).

Dépendance : aucune (ni PyTorch ni Gymnasium) ; seuls `config/defaults.py` et `config/schema.py` sont importés, de sorte que la page /rl
et la validation d'une soumission fonctionnent même sans les extras `rl`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from patrick.config import defaults as D
from patrick.config.schema import (
    DataQualityConfig,
    FeaturesConfig,
    ObjectiveConfig,
    OutputConfig,
    RunConfig,
    UniverseConfig,
)

_R = D.DEFAULT_RL
_B = D.RL_BOUNDS
# Réglages que portait toute configuration du moteur 1 (les clés du moteur 2 en moins) : leur présence complète signe un ancien enregistrement.
_ENGINE2_KEYS = frozenset({"rebalance_every", "train_cost_mult", "val_frac", "gate"})
_ENGINE1_KEYS = frozenset(D.DEFAULT_RL) - _ENGINE2_KEYS


def _f(key: str, **kw):
    lo, hi = _B[key]
    return Field(_R[key], ge=lo, le=hi, **kw)


class RLSettings(BaseModel):
    """Environnement, agent et validation walk-forward. Bornes : `config.defaults.RL_BOUNDS`.

    `engine_version` : 2 depuis la refonte du 2026-11-16 (ADR 0022). Une configuration enregistrée avant (aucun des réglages du moteur 2)
    reçoit les valeurs du moteur 1 pour les réglages absents (`RL_LEGACY_SETTINGS`) : relancer ou relire un ancien run garde son moteur."""
    engine_version: int = D.RL_ENGINE_VERSION
    # ---- environnement : ce que l'agent voit, ce qu'il peut faire, ce qu'on le récompense de faire
    action_space: Literal["discrete", "continuous"] = _R["action_space"]
    n_levels: int = _f("n_levels")                         # positions discrètes (3 : plat / demi / long, ou court / plat / long)
    allow_short: bool = _R["allow_short"]
    max_leverage: float = _f("max_leverage")               # |position| maximale (1 = capital investi une fois)
    cost_bps: float = _f("cost_bps")                       # frais, en points de base du notionnel échangé
    slippage_bps: float = _f("slippage_bps")               # glissement, idem
    reward: Literal["excess", "log", "pnl", "dsr"] = _R["reward"]
    risk_aversion: float = _f("risk_aversion")             # pénalité λ · (rendement de la période)² (récompenses « excess », « pnl » et « log »)
    dsr_eta: float = _f("dsr_eta")                         # vitesse d'oubli du ratio de Sharpe différentiel
    obs_lookback: int = _f("obs_lookback")                 # lignes de variables empilées dans l'observation
    include_position: bool = _R["include_position"]        # la position courante fait partie de l'observation
    episode_length: int = _f("episode_length")             # en barres ; 0 : tout le segment ; sinon fenêtres de cette longueur
    random_start: bool = _R["random_start"]
    rebalance_every: int = _f("rebalance_every")           # barres entre deux décisions (la position est tenue entre les deux)
    train_cost_mult: float = _f("train_cost_mult")         # multiplicateur des frais à l'entraînement (l'évaluation paie les vrais frais)
    max_features: int = _f("max_features")
    feature_selection: Literal["correlation", "none"] = _R["feature_selection"]
    # ---- agent
    algo: Literal["PPO", "A2C", "DQN", "SAC"] = _R["algo"]
    policy_layers: int = _f("policy_layers")
    policy_units: int = _f("policy_units")
    activation: Literal["tanh", "relu"] = _R["activation"]
    learning_rate: float = _f("learning_rate")
    gamma: float = _f("gamma")
    total_timesteps: int = _f("total_timesteps")           # pas d'entraînement PAR pli et PAR graine
    n_steps: int = _f("n_steps")                           # PPO / A2C
    batch_size: int = _f("batch_size")
    n_epochs: int = _f("n_epochs")                         # PPO
    ent_coef: float = _f("ent_coef")                       # PPO / A2C
    clip_range: float = _f("clip_range")                   # PPO
    gae_lambda: float = _f("gae_lambda")                   # PPO / A2C
    buffer_size: int = _f("buffer_size")                   # DQN / SAC
    learning_starts: int = _f("learning_starts")
    train_freq: int = _f("train_freq")
    target_update_interval: int = _f("target_update_interval")   # DQN
    exploration_fraction: float = _f("exploration_fraction")     # DQN
    tau: float = _f("tau")                                       # SAC
    n_seeds: int = _f("n_seeds")                           # agents entraînés (graines différentes) dont la position est moyennée
    device: Literal["auto", "cpu", "cuda"] = _R["device"]
    threads: int = _f("threads")
    # ---- validation walk-forward
    n_folds: int = _f("n_folds")
    min_train_frac: float = _f("min_train_frac")
    retrain: Literal["expanding", "rolling"] = _R["retrain"]
    rolling_bars: int = _f("rolling_bars")
    bootstrap_samples: int = _f("bootstrap_samples")
    val_frac: float = _f("val_frac")                       # part finale de l'entraînement réservée à la validation (0 = aucune)
    gate: bool = _R["gate"]                                # repli sur l'achat-conservation quand l'agent ne la bat pas en validation

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data):
        """Configuration du moteur 1 : un enregistrement COMPLET d'avant la refonte (tous les réglages du moteur 1, aucun du moteur 2, pas
        d'`engine_version` ; vrai des 463 configurations RL en base le 2026-11-16). Ses réglages absents prennent leur valeur du moteur 1.
        Un dictionnaire partiel (API, tests) reçoit les défauts du moteur 2."""
        if isinstance(data, dict) and "engine_version" not in data and _ENGINE1_KEYS <= set(data) and not _ENGINE2_KEYS & set(data):
            data = {**D.RL_LEGACY_SETTINGS, **data, "engine_version": 1}
        return data

    @property
    def benchmark_position(self) -> float:
        """Position de l'achat-conservation dans cet environnement (le capital investi une fois, sans dépasser le levier permis)."""
        return min(1.0, float(self.max_leverage))

    @model_validator(mode="after")
    def _check(self):
        if self.algo in D.RL_DISCRETE_ONLY and self.action_space != "discrete":
            raise ValueError(f"{self.algo} exige des actions discrètes (action_space = discrete)")
        if self.algo in D.RL_CONTINUOUS_ONLY and self.action_space != "continuous":
            raise ValueError(f"{self.algo} exige une action continue (action_space = continuous)")
        if self.algo == "PPO" and self.batch_size > self.n_steps:
            raise ValueError("PPO : la taille de lot ne peut pas dépasser le nombre de pas par mise à jour (n_steps)")
        if self.action_space == "discrete" and not self.allow_short and self.n_levels < 2:
            raise ValueError("au moins 2 niveaux de position")
        if self.gate and self.val_frac <= 0:
            raise ValueError("le repli sur l'achat-conservation se décide en validation : part de validation > 0 (ou repli désactivé)")
        return self

    def positions(self) -> list[float]:
        """Positions possibles (fractions du capital, déjà multipliées par le levier maximal) pour des actions discrètes."""
        lo = -1.0 if self.allow_short else 0.0
        n = max(2, int(self.n_levels))
        step = (1.0 - lo) / (n - 1)
        return [round((lo + i * step) * self.max_leverage, 10) for i in range(n)]


class RLRunConfig(BaseModel):
    kind: Literal["rl"] = "rl"
    name: str = ""
    objective: ObjectiveConfig
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    data_quality: DataQualityConfig = Field(default_factory=DataQualityConfig)
    features: FeaturesConfig = Field(default_factory=lambda: FeaturesConfig(families=["technical", "spike", "macro"]))
    rl: RLSettings = Field(default_factory=RLSettings)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="before")
    @classmethod
    def _default_name(cls, data):
        if isinstance(data, dict) and not data.get("name"):
            obj = data.get("objective")
            target = obj.get("target_symbol") if isinstance(obj, dict) else None
            slug = str(target or "run").replace("^", "IDX_").replace("-", "_").replace("/", "_").replace(" ", "_")
            data["name"] = f"{slug}_rl"
        return data

    @model_validator(mode="after")
    def _check(self):
        if self.objective.target_source != "yfinance":
            raise ValueError("RL : seules les cibles cotées (yfinance) sont prises en charge, pas les séries FRED (pas de position possible)")
        if self.objective.target_kind != "raw":
            raise ValueError("RL : la cible alpha n'est pas prise en charge (la récompense est le P&L de la cible)")
        if not set(self.features.families) & set(D.RL_FEATURE_FAMILIES):
            raise ValueError("RL : choisis au moins une famille de variables causale (" + ", ".join(D.RL_FEATURE_FAMILIES) + ")")
        return self

    @property
    def family(self) -> str:
        return "rl"

    def feature_families(self) -> list[str]:
        """Familles réellement utilisées : EGARCH/HMM/interactions sont ajustés sur un échantillon (regard vers l'avenir) et exclus."""
        return [f for f in self.features.families if f in D.RL_FEATURE_FAMILIES]

    def to_run_config(self) -> RunConfig:
        """`RunConfig` portant seulement ce que l'ingestion et la construction des variables lisent."""
        features = self.features.model_copy(update={"families": self.feature_families()})
        return RunConfig(name=self.name, objective=self.objective, universe=self.universe, data_quality=self.data_quality,
                         features=features, output=self.output)
