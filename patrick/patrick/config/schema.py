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
    # Rapport de correction, C7 -- Phase 0.4 (alignement as-of par classe d'actif,
    # `data/ingest.py::_apply_session_lag`) était jusqu'ici inconditionnelle, sans
    # bascule : ajoutée UNIQUEMENT pour que `patrick audit degradation` puisse la
    # désactiver sélectivement et mesurer son impact. False (défaut) = comportement
    # de production inchangé (correction toujours appliquée) pour tout run existant.
    disable_session_lag: bool = False


class UniverseConfig(BaseModel):
    """Le pool de tickers/séries dont sont dérivées les features (pas la cible)."""
    yf_tickers: list[str] = Field(default_factory=list)
    fred_series: dict[str, str] = Field(default_factory=dict)
    start_date: str = "2000-01-01"
    yf_coverage: float = 0.85
    # Rapport de correction, C7 -- Phase 0.5 (vintages ALFRED, `data/sources/
    # fred_source.py`) existait comme capacité mais n'était appelée nulle part
    # dans `ingest()` : ajouté ici pour que la config puisse la déclencher, et
    # que `patrick audit degradation` puisse mesurer son impact. None (défaut) =
    # comportement de production inchangé (pas de vintage, séries "telles que
    # révisées aujourd'hui"). Limite assumée : une SEULE date de vintage globale
    # pour tout l'historique (pas un vintage par fold walk-forward) -- protège
    # contre les révisions survenues APRÈS cette date, pas contre le look-ahead
    # de révision propre à chaque coupure de fold. Documenté, pas résolu ici
    # (hors périmètre C7 : mesurer l'impact des corrections existantes, pas en
    # construire une nouvelle plus fine).
    vintage_realtime_date: str | None = None


class DataQualityConfig(BaseModel):
    """Phase 6.5 (P6.5) -- portes de qualité de données à l'ingestion
    (`data/quality.py`). `enabled=False` restaure le comportement d'avant
    P6.5 (aucune exclusion au-delà du filtre de couverture déjà en place) --
    jamais le défaut : une brique de qualité inactive sans le dire serait
    exactement la même classe de défaut que le repli FRED silencieux déjà
    corrigé (cf. contrainte transversale, rapport de correction phase 6)."""
    enabled: bool = True
    max_frozen_run: int = D.DEFAULT_QUALITY_MAX_FROZEN_RUN
    max_gap_bdays: int = D.DEFAULT_QUALITY_MAX_GAP_BDAYS
    max_robust_z: float = D.DEFAULT_QUALITY_MAX_ROBUST_Z
    max_universe_exclusion_frac: float = D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC


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
    # Rapport de correction, D3 : garde de taille de fold déjà existante
    # (vérifiée, pas ajoutée) -- `_FoldContext.prepare`/`_evaluate_holdout`
    # excluent (désormais avec avertissement explicite, cf. `pipeline/engine.py`)
    # tout fold sous ce seuil plutôt que de calculer des métriques sur trop peu
    # de lignes. 20 conservé (déjà la valeur en place) : la cible a 4 classes
    # (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT), à peu près équilibrées par
    # construction (seuils par quartile fittés sur le train) -- règle usuelle
    # d'au moins ~5 observations par catégorie pour qu'un MCC/F1 par classe/AUC
    # one-vs-rest ne soit pas dégénéré (effectif nul dans une classe) donne
    # 5 x 4 = 20, exactement la valeur déjà en place.
    min_test_rows: int = 20
    holdout_months: int = D.DEFAULT_HOLDOUT_MONTHS


class SelectionConfig(BaseModel):
    method: Literal["shap", "rfe", "lasso"] = D.DEFAULT_SELECTION_METHOD
    n_features_grid: list[int] = Field(default_factory=lambda: list(D.DEFAULT_N_FEATURES_GRID))
    shap_sample: int = D.DEFAULT_SHAP_SAMPLE
    # Phase 6.3 (P6.3) -- stabilité de la sélection entre folds (Jaccard +
    # fréquence de sélection, `selection/stability.py`). True (défaut) : jamais
    # un défaut silencieusement désactivé (contrainte transversale phase 6).
    track_stability: bool = True


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
    # Rapport d'audit, C3 : True (défaut) = `top_k` est sélectionné INDÉPENDAMMENT
    # pour chaque horizon (chaque horizon reçoit ses propres `top_k` configs
    # affinées par `n_trials` essais Optuna) -- corrige la sélection globale
    # cross-horizon d'origine, qui pouvait allouer 100% du budget Optuna à un
    # seul horizon. False = ancien comportement (top_k global tous horizons
    # confondus), conservé pour compatibilité explicite.
    optuna_select_top_k_per_horizon: bool = D.DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON


class OutputConfig(BaseModel):
    dir: str = "runs"
    seed: int = D.DEFAULT_SEED


class RunConfig(BaseModel):
    name: str
    objective: ObjectiveConfig
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    data_quality: DataQualityConfig = Field(default_factory=DataQualityConfig)
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
