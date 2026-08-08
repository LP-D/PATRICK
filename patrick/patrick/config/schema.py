"""Configuration schema for a run (loaded from a YAML) — pydantic for
validation + defaults, not for performance: a run loads its config only once.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from patrick.config import defaults as D


class ObjectiveConfig(BaseModel):
    """The asset/indicator to predict and the target definition."""
    target_symbol: str
    target_source: Literal["yfinance", "fred"] = "yfinance"
    horizons: list[int] = Field(default_factory=lambda: list(D.DEFAULT_HORIZONS))
    flat_thr: float = D.DEFAULT_FLAT_THR
    regimes: list[str] = Field(default_factory=lambda: list(D.DEFAULT_REGIMES))
    # Correction report, C7 -- Phase 0.4 (per-asset-class as-of alignment,
    # `data/ingest.py::_apply_session_lag`) used to be unconditional, with no
    # toggle: added ONLY so that `patrick audit degradation` can selectively
    # disable it and measure its impact. False (default) = unchanged production
    # behavior (fix always applied) for every existing run.
    disable_session_lag: bool = False


class UniverseConfig(BaseModel):
    """The pool of tickers/series that features are derived from (not the target)."""
    yf_tickers: list[str] = Field(default_factory=list)
    fred_series: dict[str, str] = Field(default_factory=dict)
    start_date: str = "2000-01-01"
    yf_coverage: float = 0.85
    # Correction report, C7 -- Phase 0.5 (ALFRED vintages, `data/sources/
    # fred_source.py`) existed as a capability but was called nowhere in
    # `ingest()`: added here so the config can trigger it, and so that
    # `patrick audit degradation` can measure its impact. None (default) =
    # unchanged production behavior (no vintage, series "as revised today").
    # Accepted limitation: a SINGLE global vintage date for the entire history
    # (not one vintage per walk-forward fold) -- protects against revisions
    # that happened AFTER this date, not against the revision look-ahead
    # specific to each fold cut. Documented, not resolved here (out of scope
    # for C7: measure the impact of existing fixes, not build a finer new one).
    vintage_realtime_date: str | None = None


class DataQualityConfig(BaseModel):
    """Phase 6.5 (P6.5) -- data quality gates at ingestion
    (`data/quality.py`). `enabled=False` restores pre-P6.5 behavior (no
    exclusion beyond the coverage filter already in place) -- never the
    default: an inactive quality gate that doesn't say so would be exactly
    the same class of defect as the silent FRED fallback already fixed (see
    cross-cutting constraint, phase-6 correction report)."""
    enabled: bool = True
    max_frozen_run: int = D.DEFAULT_QUALITY_MAX_FROZEN_RUN
    max_gap_bdays: int = D.DEFAULT_QUALITY_MAX_GAP_BDAYS
    max_robust_z: float = D.DEFAULT_QUALITY_MAX_ROBUST_Z
    max_universe_exclusion_frac: float = D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC


class FeaturesConfig(BaseModel):
    """Which feature families to build (all reused from the VIX project)."""
    families: list[str] = Field(default_factory=lambda: list(D.DEFAULT_FEATURE_FAMILIES))
    vol_models: list[str] = Field(default_factory=lambda: list(D.DEFAULT_VOL_MODELS))
    interact_top_base: int = 40
    interact_top_pairs: int = 20
    interact_final_n: int = 30
    pool_prefilter: int = D.DEFAULT_POOL_PREFILTER


class ValidationConfig(BaseModel):
    # Phase 6.1 (P6.1) -- CPCV as an ALTERNATIVE to walk-forward, never a
    # replacement: "walkforward" remains the default, unchanged behavior for
    # every existing run. See patrick/validation/cpcv.py for the computed
    # justification of the default n_groups/k_test_groups (makes PBO
    # satisfiable per guard C5, MIN_BLOCKS=6).
    scheme: Literal["walkforward", "cpcv"] = "walkforward"
    n_groups: int = D.DEFAULT_CPCV_N_GROUPS
    k_test_groups: int = D.DEFAULT_CPCV_K_TEST_GROUPS
    n_wf_folds: int = D.DEFAULT_N_WF_FOLDS
    min_train_frac: float = D.DEFAULT_MIN_TRAIN_FRAC
    purge: bool = D.DEFAULT_PURGE_ENABLED
    embargo_enabled: bool = D.DEFAULT_EMBARGO_ENABLED
    embargo_bars: int | None = D.DEFAULT_EMBARGO_BARS
    min_train_rows: int = 100
    # Correction report, D3: fold-size guard that already existed (verified,
    # not added) -- `_FoldContext.prepare`/`_evaluate_holdout` exclude (now
    # with an explicit warning, see `pipeline/engine.py`) any fold below this
    # threshold rather than computing metrics on too few rows. 20 kept
    # (already the value in place): the target has 4 classes
    # (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT), roughly balanced by
    # construction (quartile thresholds fitted on train) -- the usual rule of
    # at least ~5 observations per category so that a per-class MCC/F1/AUC
    # one-vs-rest isn't degenerate (zero count in a class) gives 5 x 4 = 20,
    # exactly the value already in place.
    min_test_rows: int = 20
    holdout_months: int = Field(
        default=D.DEFAULT_HOLDOUT_MONTHS,
        ge=12,
        le=24,
        description="Holdout terminal window (months). Valid range: 12-24, default 15."
    )
    # Phase X5 -- Diebold-Mariano baseline selection per asset class of the
    # TARGET (`data/session_calendar.py::classify_asset_class`), rather than a
    # single "best on this fold" baseline across all classes. Each target
    # receives two DM comparisons: the best one (highest F1_dir on this fold)
    # among the candidates listed here for its class, AND class-agnostic
    # persistence (fixed common reference, never configurable here -- see
    # `pipeline/engine.py::_evaluate_diebold_mariano`) to compare classes on
    # an equal footing. Exposed in YAML (not hardcoded) to allow tuning
    # without code changes -- default values matching the per-class
    # literature (see block X report, consolidation session).
    baseline_by_asset_class: dict[str, list[str]] = Field(
        default_factory=lambda: dict(D.DEFAULT_BASELINE_BY_ASSET_CLASS)
    )


class SelectionConfig(BaseModel):
    method: Literal["shap", "rfe", "lasso"] = D.DEFAULT_SELECTION_METHOD
    n_features_grid: list[int] = Field(default_factory=lambda: list(D.DEFAULT_N_FEATURES_GRID))
    shap_sample: int = D.DEFAULT_SHAP_SAMPLE
    # Phase 6.3 (P6.3) -- selection stability across folds (Jaccard +
    # selection frequency, `selection/stability.py`). True (default): never a
    # silently disabled default (cross-cutting constraint, phase 6).
    track_stability: bool = True


class SamplerConfig(BaseModel):
    candidates: list[str] = Field(default_factory=lambda: list(D.DEFAULT_SAMPLER))


class SamplingConfig(BaseModel):
    """Phase 6.2 (P6.2) -- uniqueness weights + sequential bootstrap
    (`models/uniqueness.py`, `models/sequential_forest.py`). True (default):
    never a silently disabled default (cross-cutting constraint, phase 6).
    Concretely only applies (sample_weight passed to the classifier,
    sequential-bootstrap RandomForest) when `sampler_name="none"` -- SMOTE and
    the other oversamplers synthesize observations with no real date/span,
    to which a uniqueness weight cannot be properly attached (accepted
    limitation, documented in `pipeline/engine.py`). The effective sample
    size itself is ALWAYS computed and reported (a property of the label
    structure, independent of the sampler)."""
    uniqueness_weights: bool = True


class ModelsConfig(BaseModel):
    algos: list[str] = Field(default_factory=lambda: list(D.DEFAULT_ML_ALGOS))
    calibration: bool = D.DEFAULT_CALIBRATION_ENABLED
    stacking: bool = D.DEFAULT_STACKING_ENABLED


class TuningConfig(BaseModel):
    enabled: bool = D.DEFAULT_TUNING_ENABLED
    top_k: int = D.DEFAULT_TUNING_TOP_K
    n_trials: int = D.DEFAULT_TUNING_N_TRIALS
    cv_splits: int = D.DEFAULT_TUNING_CV_SPLITS
    # Audit report, C3: True (default) = `top_k` is selected INDEPENDENTLY for
    # each horizon (each horizon receives its own `top_k` configs refined by
    # `n_trials` Optuna trials) -- fixes the original global cross-horizon
    # selection, which could allocate 100% of the Optuna budget to a single
    # horizon. False = old behavior (global top_k across all horizons),
    # kept for explicit backward compatibility.
    optuna_select_top_k_per_horizon: bool = D.DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON


class OutputConfig(BaseModel):
    dir: str = "runs"
    seed: int = D.DEFAULT_SEED


class RunConfig(BaseModel):
    name: str = ""
    objective: ObjectiveConfig
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    data_quality: DataQualityConfig = Field(default_factory=DataQualityConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    sampler: SamplerConfig = Field(default_factory=SamplerConfig)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    tuning: TuningConfig = Field(default_factory=TuningConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="before")
    @classmethod
    def _default_name(cls, data):
        if isinstance(data, dict):
            target = data.get("objective", {}).get("target_symbol") if isinstance(data.get("objective"), dict) else None
            if not data.get("name"):
                target_name = str(target or "run")
                slug = target_name.replace("^", "IDX_").replace("-", "_").replace("/", "_").replace(" ", "_")
                data["name"] = f"{slug}_run"
        return data

    @classmethod
    def from_yaml(cls, path: str) -> "RunConfig":
        import yaml

        with open(path) as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)
