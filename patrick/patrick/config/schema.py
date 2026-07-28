"""Schéma de configuration d'un run (chargé depuis un YAML) — pydantic pour la
validation + les défauts, pas pour la performance : un run charge sa config une
seule fois.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from patrick.config import defaults as D


class ObjectiveConfig(BaseModel):
    """L'actif/indicateur à prédire et la définition de la cible."""
    target_symbol: str
    target_source: Literal["yfinance", "fred"] = "yfinance"
    horizons: list[int] = Field(default_factory=lambda: list(D.DEFAULT_HORIZONS))
    flat_thr: float = D.DEFAULT_FLAT_THR
    regimes: list[str] = Field(default_factory=lambda: list(D.DEFAULT_REGIMES))


class UniverseConfig(BaseModel):
    """Le pool de tickers/séries dont sont dérivées les features (pas la cible)."""
    yf_tickers: list[str] = Field(default_factory=list)
    fred_series: dict[str, str] = Field(default_factory=dict)
    start_date: str = "2000-01-01"
    yf_coverage: float = 0.85


class FeaturesConfig(BaseModel):
    """Quelles familles de features construire (toutes réutilisées du projet VIX)."""
    families: list[str] = Field(default_factory=lambda: list(D.DEFAULT_FEATURE_FAMILIES))
    vol_models: list[str] = Field(default_factory=lambda: list(D.DEFAULT_VOL_MODELS))
    interact_top_base: int = 40
    interact_top_pairs: int = 20
    interact_final_n: int = 30
    pool_prefilter: int = D.DEFAULT_POOL_PREFILTER


class ValidationConfig(BaseModel):
    n_wf_folds: int = D.DEFAULT_N_WF_FOLDS
    min_train_frac: float = D.DEFAULT_MIN_TRAIN_FRAC
    purge: bool = D.DEFAULT_PURGE_ENABLED
    embargo_enabled: bool = D.DEFAULT_EMBARGO_ENABLED
    embargo_bars: int | None = D.DEFAULT_EMBARGO_BARS
    min_train_rows: int = 100
    min_test_rows: int = 20
    holdout_months: int = D.DEFAULT_HOLDOUT_MONTHS


class SelectionConfig(BaseModel):
    method: Literal["shap", "rfe", "lasso"] = D.DEFAULT_SELECTION_METHOD
    n_features_grid: list[int] = Field(default_factory=lambda: list(D.DEFAULT_N_FEATURES_GRID))
    shap_sample: int = D.DEFAULT_SHAP_SAMPLE


class SamplerConfig(BaseModel):
    candidates: list[str] = Field(default_factory=lambda: list(D.DEFAULT_SAMPLER))


class ModelsConfig(BaseModel):
    algos: list[str] = Field(default_factory=lambda: list(D.DEFAULT_ML_ALGOS))
    calibration: bool = D.DEFAULT_CALIBRATION_ENABLED
    stacking: bool = D.DEFAULT_STACKING_ENABLED


class TuningConfig(BaseModel):
    enabled: bool = D.DEFAULT_TUNING_ENABLED
    top_k: int = D.DEFAULT_TUNING_TOP_K
    n_trials: int = D.DEFAULT_TUNING_N_TRIALS
    cv_splits: int = D.DEFAULT_TUNING_CV_SPLITS


class OutputConfig(BaseModel):
    dir: str = "runs"
    seed: int = D.DEFAULT_SEED


class RunConfig(BaseModel):
    name: str
    objective: ObjectiveConfig
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    sampler: SamplerConfig = Field(default_factory=SamplerConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    tuning: TuningConfig = Field(default_factory=TuningConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "RunConfig":
        import yaml

        with open(path) as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)
