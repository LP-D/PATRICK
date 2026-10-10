"""Configuration schema for a run (loaded from a YAML) — pydantic for
validation + defaults, not for performance: a run loads its config only once.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_serializer, model_validator

from patrick.config import defaults as D
from patrick.config.target_label import run_label


class AlignmentSpec(BaseModel):
    """Décalages temporels décidés pour UN run (`data/alignment.py`) et rejoués à l'identique par la prédiction live,
    l'explication et la reprise. `version == 0` (défaut, et valeur de tous les runs antérieurs) : aucun décalage ajouté,
    donc un ancien modèle reçoit exactement les entrées de son entraînement."""
    version: int = 0
    column_lags: dict[str, int] = Field(default_factory=dict)   # colonne -> nombre de barres de retard
    dropped: list[str] = Field(default_factory=list)            # colonnes retirées (fuite non corrigeable par un retard)
    drop_future: bool = False   # retire les lignes datées après aujourd'hui (une cible FRED publiée en différé en crée)
    reasons: dict[str, str] = Field(default_factory=dict)       # colonne -> motif lisible


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
    # Garde anti-fuite (`data/alignment.py`) : décale les séries de marché dont la date recouvre déjà la fenêtre du label
    # (cible FRED publiée avec retard, séries cotées dans un autre fuseau). `False` = comportement antérieur, réservé aux
    # audits de dégradation. La décision prise est écrite dans `alignment` pour que le run reste reproductible.
    leak_guard: bool = True
    alignment: AlignmentSpec = Field(default_factory=AlignmentSpec)
    # Cible alpha (docs/superpowers/specs/2026-10-06-cible-alpha-beta-point-in-time-design.md) : "raw" = rendement
    # brut de la cible (défaut, comportement historique); "alpha" = rendement excédentaire `actif - β * benchmark`.
    # `benchmark` vide = déterminé automatiquement (features/benchmark.py), sinon choix manuel; le validateur de
    # `RunConfig` y écrit le benchmark retenu et sa provenance pour que le run reste reproductible.
    target_kind: Literal["raw", "alpha"] = "raw"
    benchmark: str | None = None
    benchmark_source: Literal["auto", "manual"] | None = None

    def run_label(self) -> str:
        """Étiquette de cible de ce run en base (`run.target`) : le symbole, ou `symbole__alpha_benchmark`
        (voir `config/target_label.py`)."""
        return run_label(self.target_symbol, self.target_kind, self.benchmark)

    def raw_cache_key(self) -> str:
        """Clé du snapshot de données de ce run dans le data lake. Une cible alpha a la sienne : le snapshot brut
        `raw_<cible>` ne contient pas le benchmark, et lui servir ce cache donnerait un run sans benchmark."""
        return f"raw_{self.run_label()}"


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
    # F01 -- how FRED observations are placed in time (`data/ingest.py`):
    # "alfred" (`data/alfred.py`) uses the ALFRED first releases indexed on their true
    # publication date, where ALFRED archives them (needs FRED_API_KEY, falls back to
    # "publication_lag" with a warning). It is the default of every NEW run (web form,
    # YAML, `D.DEFAULT_FRED_POINT_IN_TIME`); the schema default stays "publication_lag" so
    # that a config stored before 2026-10-10 -- which has no such key, or an explicit
    # "publication_lag" -- is reloaded by predict/explain/resume with the alignment it was
    # trained with;
    # "publication_lag" re-indexes every observation on its estimated release date
    # (`data/publication_lag.py`, the series as revised today);
    # "reference_date" is the pre-F01, LEAKY behavior, kept only so that
    # `patrick audit degradation` can measure what F01 changes.
    fred_point_in_time: Literal["publication_lag", "alfred", "reference_date"] = "publication_lag"
    # Candidate-universe reduction (`selection/universe_reduction.py`):
    # hierarchical clustering on 1-|corr| of returns, one representative per
    # cluster, decided INSIDE each fold from its training bars only (walk-
    # forward fold, holdout, CPCV combination, final model). None (default)
    # = no reduction -- never a silent filter; values below
    # `AGGRESSIVE_CORR_THRESHOLD` are accepted but warned about.
    reduction_corr_threshold: float | None = Field(default=None, gt=0.0, le=1.0)
    reduction_lookback: int = Field(default=252, ge=20)


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
    # CHANTIER (feature/equity-asset-class, suite) -- anciennete minimale
    # d'historique (annees) exigee a l'ingestion (`data/ingest.py`), remplace
    # le 20 fige en dur. Validee sur la valeur SOUMISE uniquement
    # (`webapp/forms.py::_parse... ` / `cli.py --min-history-years`), jamais
    # ici (pas de bounds pydantic, meme convention que le reste de RunConfig).
    min_history_years: int = D.DEFAULT_MIN_HISTORY_YEARS


class TechnicalLookbacksConfig(BaseModel):
    """Phase 3 (feature/hyperparams-lookbacks): rolling-window lookbacks for
    `features/technical.py`, previously fixed function-default parameters
    never threaded through `RunConfig` (`feature/hyperparams-ui` exposed
    n_trials/top_k/cv_splits/algos/optuna_bounds but explicitly left this
    out). Defaults are IDENTICAL to the historical hardcoded values -- an
    unmodified run keeps computing exactly the same technical features as
    before this field existed.

    Like the rest of `RunConfig` (no bounds/validators enforced by pydantic
    here, per the module docstring), range validation happens in
    `webapp/forms.py::_parse_technical_lookbacks` before this ever reaches
    `model_validate` from the web form, AND defensively again in
    `pipeline/engine.py::_sanitize_lookback_windows` right before
    `features/technical.py` is called -- the second guard also protects a
    hand-edited YAML/CLI run, which never goes through the web form. Both
    exist because a window<=0 is not merely "wasteful" here: `returns()`
    silently computes a look-ahead (future-leaking) value for a NEGATIVE
    window (pandas `Series.pct_change(periods=negative)` never raises), and
    `ohlc_vol_windows` values below 2 raise `ZeroDivisionError` inside
    `yang_zhang_vol` (`(window - 1)` in its denominator) -- see
    `tests/test_technical_lookbacks.py` for both measured behaviors."""
    returns_windows: list[int] = Field(default_factory=lambda: list(D.DEFAULT_RETURNS_WINDOWS))
    zscore_windows: list[int] = Field(default_factory=lambda: list(D.DEFAULT_ZSCORE_WINDOWS))
    ma_ratio_windows: list[int] = Field(default_factory=lambda: list(D.DEFAULT_MA_RATIO_WINDOWS))
    rolling_vol_windows: list[int] = Field(default_factory=lambda: list(D.DEFAULT_ROLLING_VOL_WINDOWS))
    ohlc_vol_windows: list[int] = Field(default_factory=lambda: list(D.DEFAULT_OHLC_VOL_WINDOWS))


class FeaturesConfig(BaseModel):
    """Which feature families to build (all reused from the VIX project)."""
    families: list[str] = Field(default_factory=lambda: list(D.DEFAULT_FEATURE_FAMILIES))
    vol_models: list[str] = Field(default_factory=lambda: list(D.DEFAULT_VOL_MODELS))
    interact_top_base: int = 40
    interact_top_pairs: int = 20
    interact_final_n: int = 30
    pool_prefilter: int = D.DEFAULT_POOL_PREFILTER
    # Phase 2 (feature/guida-features-full) -- master switch for the Guida
    # factor taxonomy: the 14-lookback grid (`config.defaults.GUIDA_LOOKBACKS`)
    # applied to technical/spike/macro, plus the three "estimated" families
    # (carry, cross-sectional momentum, idiosyncratic volatility -- see
    # `features/guida.py`). False (default): exactly the pre-existing feature
    # pool, unchanged -- this is a research toggle (scan-cost impact measured,
    # not yet judged for a default-on switch), never flipped on here.
    enable_guida_features: bool = D.DEFAULT_ENABLE_GUIDA_FEATURES
    # CHANTIER (feature/equity-asset-class) -- master switch for equity
    # fundamentals features (`features/equity_fundamentals.py`,
    # `data/sources/fundamentals_source.py`): fiscalDateEnding + value,
    # reindexed onto the daily pool. False (default): exactly the
    # pre-existing feature pool, unchanged -- same "off by default research
    # toggle" convention as `enable_guida_features` above. Only has an
    # effect when the run's target is an equity symbol
    # (`config.equity_universe.EQUITY_UNIVERSE`); a no-op otherwise.
    enable_fundamentals_features: bool = D.DEFAULT_ENABLE_FUNDAMENTALS_FEATURES
    technical_lookbacks: TechnicalLookbacksConfig = Field(default_factory=TechnicalLookbacksConfig)


class ValidationConfig(BaseModel):
    # Phase 6.1 (P6.1) -- CPCV as an ALTERNATIVE to walk-forward, never a
    # replacement: "walkforward" remains the default, unchanged behavior for
    # every existing run. See patrick/validation/cpcv.py for the computed
    # justification of the default n_groups/k_test_groups (makes PBO
    # satisfiable per guard C5, MIN_BLOCKS=6).
    scheme: Literal["walkforward", "cpcv"] = "walkforward"
    n_groups: int = D.DEFAULT_CPCV_N_GROUPS
    k_test_groups: int = D.DEFAULT_CPCV_K_TEST_GROUPS
    n_wf_folds: int = Field(default=D.DEFAULT_N_WF_FOLDS, ge=1)
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
    # CHANTIER A (feature/regime-detection-hmm) -- HMM volatility regime
    # detection (features/regime_detection.py::detect_regime). Off by
    # default, same stance as purge/calibration/stacking. threshold_mode
    # ("quantile" derives cutoffs from the train-only distribution of
    # P(highest-variance state); "fixed" uses threshold_values verbatim as
    # absolute probability cutoffs) and threshold_values are exposed here
    # rather than hardcoded, same pattern as dm_alpha/fdr_alpha on the web
    # routes.
    regime_detection_enabled: bool = D.DEFAULT_REGIME_DETECTION_ENABLED
    regime_threshold_mode: Literal["quantile", "fixed"] = D.DEFAULT_REGIME_THRESHOLD_MODE
    regime_threshold_values: tuple[float, float] = D.DEFAULT_REGIME_THRESHOLD_VALUES


class SelectionConfig(BaseModel):
    method: Literal["shap", "rfe", "lasso"] = D.DEFAULT_SELECTION_METHOD
    n_features_grid: list[int] = Field(default_factory=lambda: list(D.DEFAULT_N_FEATURES_GRID))
    shap_sample: int = D.DEFAULT_SHAP_SAMPLE
    # exhaustive: every candidate on every fold. staged: whole grid on the FIRST fold, then the finalists on the
    # later folds. total_window: every candidate fitted ONCE and scored on the whole out-of-sample window (split
    # 'valid', fold 0), then only the finalists on the walk-forward folds.
    screening_mode: Literal["exhaustive", "staged", "total_window"] = "exhaustive"
    screening_finalists_per_group: int = Field(default=8, ge=1, le=100)
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


class DeepConfig(BaseModel):
    """Réglages communs des réseaux de neurones (`models/deep.py`) : MLP, GRU, LSTM, CNN1D, Transformer. Absent (`None`) pour tout run
    de machine learning : un run qui n'en parle pas garde exactement son hachage de configuration d'avant (`pipeline/engine.py::
    _config_hash`). Bornes : `config.defaults.DEEP_BOUNDS`."""
    hidden_size: int = Field(D.DEFAULT_DEEP["hidden_size"], ge=4, le=512)       # largeur des couches / taille de l'état caché
    n_layers: int = Field(D.DEFAULT_DEEP["n_layers"], ge=1, le=6)
    dropout: float = Field(D.DEFAULT_DEEP["dropout"], ge=0.0, le=0.8)
    lookback: int = Field(D.DEFAULT_DEEP["lookback"], ge=2, le=252)             # fenêtre des modèles séquentiels (barres)
    epochs: int = Field(D.DEFAULT_DEEP["epochs"], ge=1, le=500)                 # plafond ; l'arrêt anticipé peut s'arrêter avant
    batch_size: int = Field(D.DEFAULT_DEEP["batch_size"], ge=8, le=4096)
    learning_rate: float = Field(D.DEFAULT_DEEP["learning_rate"], ge=1e-5, le=0.1)
    weight_decay: float = Field(D.DEFAULT_DEEP["weight_decay"], ge=0.0, le=0.1)
    patience: int = Field(D.DEFAULT_DEEP["patience"], ge=0, le=100)             # 0 = pas d'arrêt anticipé
    val_fraction: float = Field(D.DEFAULT_DEEP["val_fraction"], ge=0.0, le=0.4) # fin (temporelle) de l'entraînement gardée en validation
    grad_clip: float = Field(D.DEFAULT_DEEP["grad_clip"], ge=0.0, le=100.0)     # 0 = pas de coupure
    class_weight: Literal["balanced", "none"] = D.DEFAULT_DEEP["class_weight"]
    n_seeds: int = Field(D.DEFAULT_DEEP["n_seeds"], ge=1, le=10)                # réseaux moyennés (graines différentes)
    device: Literal["auto", "cpu", "cuda"] = D.DEFAULT_DEEP["device"]
    n_heads: int = Field(D.DEFAULT_DEEP["n_heads"], ge=1, le=16)                # Transformer
    kernel_size: int = Field(D.DEFAULT_DEEP["kernel_size"], ge=2, le=9)         # CNN1D
    threads: int = Field(D.DEFAULT_DEEP["threads"], ge=1, le=64)


class ModelsConfig(BaseModel):
    algos: list[str] = Field(default_factory=lambda: list(D.DEFAULT_ML_ALGOS))
    deep: DeepConfig | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_deep(self, handler):
        """Un run de machine learning garde EXACTEMENT sa configuration sérialisée d'avant (`config_json` en base, exports) : la clé
        `deep` n'apparaît que lorsqu'elle porte des réglages de réseaux."""
        data = handler(self)
        if isinstance(data, dict) and data.get("deep") is None:
            data.pop("deep", None)
        return data
    calibration: bool = D.DEFAULT_CALIBRATION_ENABLED
    # Roadmap bloc 3: isotonic (non-parametric, needs more rows) or sigmoid
    # (Platt, 2 parameters per class, stabler on the ~7% of a fold's train
    # it is fitted on). Only used when `calibration` is True.
    calibration_method: Literal["isotonic", "sigmoid"] = "isotonic"
    stacking: bool = D.DEFAULT_STACKING_ENABLED


class TuningConfig(BaseModel):
    enabled: bool = D.DEFAULT_TUNING_ENABLED
    top_k: int = D.DEFAULT_TUNING_TOP_K
    n_trials: int = D.DEFAULT_TUNING_N_TRIALS
    cv_splits: int = D.DEFAULT_TUNING_CV_SPLITS
    # True (default) = select `top_k` independently for each horizon. Since
    # scores across horizons are not directly comparable, this guarantees each
    # horizon gets its own tuning budget. `top_k=1` tunes only its best scan
    # model by default; larger values retain broader exploratory searches.
    optuna_select_top_k_per_horizon: bool = D.DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON
    # Phase 1 (feature/hyperparams-ui): per-algo Optuna search-space bounds
    # (`{algo: {param: [low, high]}}`), forwarded to
    # `tuning/optuna_runner.py::suggest_params`. Used to have NO config
    # surface at all -- fixed in code. Defaults to `D.DEFAULT_OPTUNA_BOUNDS`,
    # identical to those former hardcoded values, so an unmodified run keeps
    # searching exactly the same space. Like the rest of `RunConfig` (no
    # bounds/validators enforced by pydantic here, per the module docstring),
    # range/shape validation happens in `webapp/forms.py::
    # _parse_optuna_bounds` before this ever reaches `model_validate` from
    # the web form; `suggest_params` itself falls back to the default for any
    # algo/param missing or malformed here, so a hand-edited YAML with a
    # partial override degrades gracefully rather than raising deep inside a
    # run.
    optuna_bounds: dict[str, dict[str, list[float]]] = Field(
        default_factory=lambda: {a: dict(p) for a, p in D.DEFAULT_OPTUNA_BOUNDS.items()}
    )


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

    @model_validator(mode="after")
    def _resolve_alpha_benchmark(self):
        from patrick.features.benchmark import resolve_benchmark

        obj = self.objective
        if obj.target_kind != "alpha":
            if obj.benchmark or obj.benchmark_source:
                raise ValueError("benchmark n'a de sens que pour target_kind='alpha'")
            return self
        if obj.target_source != "yfinance":
            raise ValueError("cible alpha : seules les cibles yfinance sont prises en charge (cible FRED refusée)")
        if obj.benchmark_source:                       # config déjà résolue (run relancé, repris) : on ne la réinterprète pas
            if not obj.benchmark or obj.benchmark.strip().upper() == obj.target_symbol.strip().upper():
                raise ValueError("benchmark enregistré invalide")
            choice_symbol, choice_source = obj.benchmark, obj.benchmark_source
        else:
            choice = resolve_benchmark(obj.target_symbol, obj.benchmark, obj.target_source)
            choice_symbol, choice_source = choice.symbol, choice.source
        obj.benchmark, obj.benchmark_source = choice_symbol, choice_source
        if choice_symbol not in self.universe.yf_tickers:     # téléchargé, décalé et nettoyé comme tout l'univers
            self.universe.yf_tickers = [*self.universe.yf_tickers, choice_symbol]
        return self

    @model_validator(mode="after")
    def _check_deep_models(self):
        """Réseaux de neurones : le DL n'a ni sa propre validation ni ses propres échantillonneurs, il hérite de ceux du run, avec deux
        incompatibilités explicites. Un modèle à fenêtre lit des lignes CONSÉCUTIVES : un échantillonneur qui réordonne ou synthétise
        des lignes (SMOTE...) comme la validation CPCV (groupes non contigus) en détruiraient le sens."""
        algos = set(self.models.algos)
        sequence = algos & set(D.SEQUENCE_DL_ALGOS)
        if sequence:
            if any(name != "none" for name in self.sampler.candidates):
                raise ValueError(f"les modèles à fenêtre ({', '.join(sorted(sequence))}) exigent le sampler « none » : un "
                                 "sur-échantillonneur réordonne et synthétise des lignes")
            if self.validation.scheme == "cpcv":
                raise ValueError(f"les modèles à fenêtre ({', '.join(sorted(sequence))}) ne tournent pas en CPCV (lignes non contiguës)")
        return self

    @property
    def family(self) -> str:
        """« dl » si tous les algorithmes du run sont des réseaux de neurones, sinon « ml » (page de lancement d'origine)."""
        algos = self.models.algos
        return "dl" if algos and all(a in D.ALL_DL_ALGOS for a in algos) else "ml"

    @classmethod
    def from_yaml(cls, path: str) -> RunConfig:
        import yaml

        from patrick.config import defaults as D

        with open(path) as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):                   # un YAML neuf suit le défaut des nouveaux runs (ALFRED)
            raw.setdefault("universe", {}).setdefault("fred_point_in_time", D.DEFAULT_FRED_POINT_IN_TIME)
        return cls.model_validate(raw)
