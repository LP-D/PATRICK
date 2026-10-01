"""Calcul parallèle ORDONNÉ des tâches pures du scan (Sprint 2, optimisation exacte).

Principe : les calculs coûteux et sans effet de bord (classement SHAP, fit +
évaluation d'un modèle) sont envoyés à des processus (loky) ; TOUT le reste
(lectures/écritures SQLite, leaderboard, création d'essais, ordre des écritures)
reste dans le processus parent, dans l'ordre exact de la version séquentielle.
Les résultats reviennent dans l'ordre des tâches : aucun résultat ne dépend du
nombre de workers.

- Un worker reçoit uniquement des arguments explicites (tableaux, noms, graine) :
  jamais une connexion SQLite, jamais un nom de profil.
- Graines : celles que la version séquentielle passe déjà (aucune n'est dérivée
  de l'ordre d'exécution).
- Threads : les workers utilisent le même nombre de threads BLAS/OpenMP que le
  parent (`inner_max_num_threads`), pour des résultats numériques identiques ;
  `n_jobs` x threads ne doit pas dépasser le nombre de cœurs (à la charge de
  l'utilisateur : réglage « workers » + variables OMP_NUM_THREADS).

Activation : `PATRICK_SCAN_JOBS=<n>` ou réglage de la page « Lancer »
(`patrick.settings`) ; défaut 1 = code séquentiel d'origine.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

from joblib import Parallel, delayed, parallel_config

from patrick import settings
from patrick.resource_budget import cap_workers

ENV_JOBS = "PATRICK_SCAN_JOBS"


def resolve_jobs(task_count: int | None = None, input_bytes: int = 0) -> int:
    """`PATRICK_SCAN_JOBS` (prioritaire), sinon le réglage de l'interface ;
    1 = séquentiel. Plafonné au nombre de cœurs logiques."""
    env = os.environ.get(ENV_JOBS)
    if env is not None:
        try:
            requested = int(env)
        except ValueError:
            return 1
    else:
        requested = settings.get_scan_jobs()
    return cap_workers(requested, task_count, input_bytes)


def _blas_threads() -> int | None:
    try:
        import threadpoolctl
        counts = [lib["num_threads"] for lib in threadpoolctl.threadpool_info()
                  if lib.get("user_api") == "blas"]
        return max(counts) if counts else None
    except Exception:  # noqa: BLE001 -- purely informational; falls back to joblib's default
        return None


def _resolve(name: str) -> Callable[..., Any]:
    """Fonctions de calcul pur envoyables par NOM (résolues dans le worker, où le moteur
    n'est jamais instrumenté : un wrapper de profilage n'est pas sérialisable)."""
    from patrick.pipeline import engine
    from patrick.selection.registry import select_features
    return {"fit_eval_full": engine._fit_eval_full, "fit_eval": engine._fit_eval,
            "select_features": select_features}[name]


def _dispatch(name: str, args: tuple, kwargs: dict) -> Any:
    return _resolve(name)(*args, **kwargs)


def _deduplicate_tasks(tasks: Sequence[tuple[str | Callable[..., Any], tuple, dict]],
                       keys: Sequence[Any]) -> tuple[list, list[int]]:
    if len(keys) != len(tasks):
        raise ValueError("deduplication keys must match the task count")
    unique = []
    positions = {}
    task_indexes = []
    for task, key in zip(tasks, keys, strict=True):
        if key not in positions:
            positions[key] = len(unique)
            unique.append(task)
        task_indexes.append(positions[key])
    return unique, task_indexes


def run_ordered(tasks: Sequence[tuple[str | Callable[..., Any], tuple, dict]], jobs: int,
                deduplicate_keys: Sequence[Any] | None = None) -> list:
    """Exécute chaque tâche `(fonction ou nom, args, kwargs)` et renvoie les résultats
    DANS L'ORDRE des tâches. `jobs <= 1` ou une seule tâche : exécution directe
    dans ce processus (même code que la version séquentielle)."""
    unique, task_indexes = (_deduplicate_tasks(tasks, deduplicate_keys) if deduplicate_keys is not None
                            else (list(tasks), list(range(len(tasks)))))
    if jobs <= 1 or len(unique) <= 1:
        results = [(_resolve(fn) if isinstance(fn, str) else fn)(*args, **kwargs)
                   for fn, args, kwargs in unique]
    else:
        with parallel_config(backend="loky", n_jobs=min(jobs, len(unique)),
                             inner_max_num_threads=_blas_threads()):
            results = Parallel()(
                delayed(_dispatch)(fn, args, kwargs) if isinstance(fn, str) else delayed(fn)(*args, **kwargs)
                for fn, args, kwargs in unique)
    return [results[i] for i in task_indexes]
