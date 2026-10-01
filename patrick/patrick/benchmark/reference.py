"""Dataset synthétique + configurations de référence du benchmark.

Pourquoi synthétique : le pipeline réel télécharge Yahoo/FRED (réseau, données
révisées) -- irreproductible d'un jour à l'autre. Ici le snapshot est fabriqué
par une graine fixe, écrit dans un `DataStore` isolé, puis rejoué via
`run_pipeline(snapshot_id=...)` (le chemin `patrick resume`). Identité du
snapshot = `data_hash` (hash de contenu) ; le `snapshot_id` complet embarque la
date du jour et n'est donc pas comparable d'un jour à l'autre.

Limite assumée : ce n'est PAS une mesure sur ^GSPC réel. Les proportions entre
phases dépendent de la taille de l'univers / des horizons / de la grille ;
`REFERENCE` en fixe une, documentée dans le rapport.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from patrick.config.schema import RunConfig

TARGET_SYMBOL = "^SYN"          # colonne `IDX_SYN` après `clean_symbol`
DATA_SEED = 20260930
PIPELINE_SEED = 42

_NUMERIC_PACKAGES = ("numpy", "pandas", "scipy", "scikit-learn", "xgboost", "lightgbm", "catboost", "shap",
                     "numba", "optuna", "imbalanced-learn", "statsmodels", "arch", "pykalman", "hmmlearn",
                     "joblib", "pyarrow", "duckdb")
THREAD_ENV_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                   "VECLIB_MAXIMUM_THREADS", "PATRICK_FEATURE_CACHE")


@dataclass(frozen=True)
class DatasetSpec:
    n_days: int
    n_tickers: int
    n_fred: int
    start: str = "2012-01-02"
    seed: int = DATA_SEED


@dataclass(frozen=True)
class ProfileSpec:
    """Tout ce qui définit un run reproductible ; sérialisé dans le rapport."""
    name: str
    dataset: DatasetSpec
    horizons: tuple[int, ...]
    n_wf_folds: int
    n_features_grid: tuple[int, ...]
    algos: tuple[str, ...]
    samplers: tuple[str, ...]
    vol_models: tuple[str, ...]
    shap_sample: int
    pool_prefilter: int
    holdout_months: int
    tuning_top_k: int
    tuning_n_trials: int
    tuning_cv_splits: int
    cpcv_n_groups: int = 5
    cpcv_k_test_groups: int = 2

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self)))


# Benchmark de référence : assez lourd pour que chaque phase pèse, assez court
# pour être relancé en quelques dizaines de minutes.
REFERENCE = ProfileSpec(
    name="reference", dataset=DatasetSpec(n_days=2600, n_tickers=30, n_fred=6),
    horizons=(1, 5), n_wf_folds=4, n_features_grid=(6, 10, 14), algos=("XGBoost", "LightGBM", "RandomForest", "CatBoost"),
    samplers=("SMOTE",), vol_models=("egarch", "kalman", "hmm"), shap_sample=300, pool_prefilter=200,
    holdout_months=12, tuning_top_k=2, tuning_n_trials=20, tuning_cv_splits=3)

# Profil des tests (secondes) : mêmes chemins de code, taille minimale.
TINY = ProfileSpec(
    name="tiny", dataset=DatasetSpec(n_days=1100, n_tickers=2, n_fred=1),
    horizons=(3,), n_wf_folds=3, n_features_grid=(4,), algos=("XGBoost", "LightGBM"), samplers=("SMOTE",),
    vol_models=("kalman",), shap_sample=80, pool_prefilter=40, holdout_months=12,
    tuning_top_k=1, tuning_n_trials=2, tuning_cv_splits=2, cpcv_n_groups=5, cpcv_k_test_groups=2)

PROFILES = {"reference": REFERENCE, "tiny": TINY}


def make_raw(ds: DatasetSpec) -> pd.DataFrame:
    """Prix/niveaux synthétiques déterministes (volatilité en grappes + facteur
    commun + un peu de prévisibilité retardée pour que la sélection trouve
    quelque chose). Colonnes : `IDX_SYN` (cible), `T01..`, `F01..`."""
    rng = np.random.default_rng(ds.seed)
    idx = pd.bdate_range(ds.start, periods=ds.n_days)
    n = ds.n_days
    factor = np.zeros(n)
    vol = np.full(n, 0.01)
    shocks = rng.normal(size=n)
    for t in range(1, n):
        vol[t] = np.sqrt(1e-6 + 0.08 * (vol[t - 1] * shocks[t - 1]) ** 2 + 0.9 * vol[t - 1] ** 2)
        factor[t] = 0.06 * factor[t - 1] + vol[t] * shocks[t]
    cols: dict[str, np.ndarray] = {}
    tgt_ret = 0.35 * np.roll(factor, 1) + 0.008 * rng.normal(size=n)
    cols["IDX_SYN"] = 1000.0 * np.exp(np.cumsum(tgt_ret))
    for i in range(ds.n_tickers):
        beta = rng.uniform(0.3, 1.2)
        r = beta * factor + 0.01 * rng.normal(size=n) + (0.03 * np.roll(tgt_ret, 1) if i % 3 == 0 else 0.0)
        cols[f"T{i + 1:02d}"] = 50.0 * np.exp(np.cumsum(r))
    for j in range(ds.n_fred):
        cols[f"F{j + 1:02d}"] = np.cumsum(rng.normal(0, 0.02, n)) + 0.5 * np.cumsum(factor) * (j % 2)
    return pd.DataFrame(cols, index=idx)


def make_config(spec: ProfileSpec, scheme: str, out_dir: str, name: str | None = None) -> RunConfig:
    ds = spec.dataset
    return RunConfig.model_validate({
        "name": name or f"bench_{spec.name}_{scheme}",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": list(spec.horizons), "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": [f"T{i + 1:02d}" for i in range(ds.n_tickers)],
                     "fred_series": {f"F{j + 1:02d}": f"F{j + 1:02d}" for j in range(ds.n_fred)},
                     "start_date": ds.start},
        "features": {"families": ["technical", "interactions", "spike", "vol_models", "macro"],
                     "vol_models": list(spec.vol_models), "interact_top_base": 10, "interact_top_pairs": 5,
                     "interact_final_n": 4 if spec.name == "tiny" else 12, "pool_prefilter": spec.pool_prefilter},
        "validation": {"scheme": scheme, "n_wf_folds": spec.n_wf_folds, "min_train_frac": 0.5,
                       "holdout_months": spec.holdout_months, "n_groups": spec.cpcv_n_groups,
                       "k_test_groups": spec.cpcv_k_test_groups},
        "selection": {"method": "shap", "n_features_grid": list(spec.n_features_grid),
                      "shap_sample": spec.shap_sample},
        "sampler": {"candidates": list(spec.samplers)},
        "models": {"algos": list(spec.algos)},
        "tuning": {"enabled": scheme == "walkforward", "top_k": spec.tuning_top_k,
                   "n_trials": spec.tuning_n_trials, "cv_splits": spec.tuning_cv_splits},
        "output": {"dir": out_dir, "seed": PIPELINE_SEED},
    })


def config_digest(config: RunConfig) -> str:
    """Hash de la configuration résolue, hors chemin de sortie (qui change
    d'un run à l'autre sans changer la méthode)."""
    d = json.loads(config.model_dump_json())
    d["output"].pop("dir", None)
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def capture_environment() -> dict:
    import threadpoolctl
    blas = sorted({f"{lib['internal_api']}:{lib.get('architecture')}:{lib.get('num_threads')}"
                   for lib in threadpoolctl.threadpool_info()})
    return {
        "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
        "python": sys.version.split()[0], "cpu_count_logical": os.cpu_count(),
        "packages": {p: _version(p) for p in _NUMERIC_PACKAGES},
        "thread_env": {k: os.environ.get(k) for k in THREAD_ENV_VARS},
        "threadpools": blas,
    }
