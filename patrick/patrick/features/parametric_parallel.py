"""Construction PARALLÈLE du pool paramétrique (Sprint 2, optimisation exacte).

Même résultat que la boucle séquentielle de `engine._build_parametric_pool`,
colonne par colonne, dans le même ordre :

- chaque colonne `raw` est indépendante (un modèle par série) : les tâches sont
  distribuées à des processus (loky) et réassemblées DANS L'ORDRE des colonnes ;
- un worker reçoit tout ce dont il a besoin (série, noms de modèles, bornes de
  fit) -- jamais un nom de profil, jamais une connexion SQLite ;
- le cache SQLite des modèles de vol (migration 0015) est lu ET écrit dans le
  processus parent, dans le même ordre que la version séquentielle ;
- aucune graine n'est modifiée (elles sont des paramètres par défaut des
  fonctions de modèle) ; les variables de threads BLAS/OpenMP sont héritées
  telles quelles par les workers : `n_jobs` x threads BLAS ne doit pas dépasser
  le nombre de cœurs (à la charge de l'appelant, voir `resolve_jobs`).

Activation : `PATRICK_PARAMETRIC_JOBS=<n>` (défaut 1 = code séquentiel d'origine).
"""
from __future__ import annotations

import os

import pandas as pd
from joblib import Parallel, delayed

from patrick.features import spike, vol_models

ENV_JOBS = "PATRICK_PARAMETRIC_JOBS"


def resolve_jobs(n_columns: int) -> int:
    """1 (séquentiel) sauf si `PATRICK_PARAMETRIC_JOBS` demande explicitement plus.
    Plafonné au nombre de colonnes et au nombre de cœurs logiques."""
    try:
        requested = int(os.environ.get(ENV_JOBS, "1"))
    except ValueError:
        return 1
    return max(1, min(requested, n_columns, os.cpu_count() or 1))


def _column_task(series: pd.Series, col: str, models: list[str], run_vol: bool, run_spike: bool,
                 fit_end_idx: int | None, test_end_idx: int | None,
                 cached: dict[str, pd.DataFrame | None]) -> tuple[list[pd.DataFrame], dict[str, pd.DataFrame]]:
    """Exécuté dans un worker. `cached[m]` : résultat déjà lu en cache par le
    parent (ou None). Renvoie les morceaux de la colonne (mêmes objets que la
    boucle séquentielle) et les résultats NEUFS à écrire en cache."""
    parts: list[pd.DataFrame] = []
    fresh: dict[str, pd.DataFrame] = {}
    if run_vol:
        selected = [m for m in models if m in vol_models._PARAMETRIC_MODELS]
        if selected:
            frames = []
            for m in selected:
                if cached.get(m) is not None:
                    frames.append(cached[m])
                else:
                    res = vol_models._timed_model_call(m, vol_models._PARAMETRIC_MODELS[m], series,
                                                       fit_end_idx, test_end_idx)
                    fresh[m] = res
                    frames.append(res)
            df = pd.concat(frames, axis=1)
            df.columns = [f"{col}_{c}" for c in df.columns]
            parts.append(df)
        else:
            parts.append(pd.DataFrame(index=series.index))
    if run_spike:
        parts.append(spike.build_spike_features_parametric(series, prefix=col, fit_end_idx=fit_end_idx))
    return parts, fresh


def build_parts(raw: pd.DataFrame, families: list[str], models: list[str], fit_end_idx: int | None,
                test_end_idx: int | None, conn, snapshot_id: str | None, n_jobs: int) -> list[pd.DataFrame]:
    """Liste de morceaux, dans l'ordre exact de la boucle séquentielle."""
    run_vol = "vol_models" in families
    run_spike = "spike" in families
    use_cache = conn is not None and snapshot_id is not None
    selected = [m for m in models if m in vol_models._PARAMETRIC_MODELS]

    cached_by_col: dict[str, dict[str, pd.DataFrame | None]] = {}
    for col in raw.columns:
        cached_by_col[col] = {}
        if run_vol and use_cache:
            for m in selected:     # même ordre de lecture que la version séquentielle
                cached_by_col[col][m] = vol_models.lookup_cached_parametric_model(
                    conn, snapshot_id, col, m, raw[col], fit_end_idx, test_end_idx)

    results = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(_column_task)(raw[col], col, models, run_vol, run_spike, fit_end_idx, test_end_idx,
                              cached_by_col[col]) for col in raw.columns)

    parts: list[pd.DataFrame] = []
    for col, (col_parts, fresh) in zip(raw.columns, results, strict=True):
        if use_cache:
            for m in selected:     # mêmes écritures, même ordre
                if m in fresh:
                    vol_models.store_cached_parametric_model(conn, snapshot_id, col, m, raw[col],
                                                             fit_end_idx, test_end_idx, fresh[m])
        parts.extend(col_parts)
    return parts
