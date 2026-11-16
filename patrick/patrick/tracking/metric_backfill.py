"""Rattrapage du panneau de métriques (ADR 0023) pour les modèles évalués avant qu'il existe.

`AUC_dir` et `Acc_dir_p` ne sont calculés à chaque évaluation que depuis le 2026-10-31 (ADR 0013) : sur 4 317 meilleurs essais, 726
seulement les avaient au 2026-11-16, alors que les listes et les aperçus se lisent désormais sur `AUC_dir · Brier_up · MCC_4cls ·
Acc_dir_p`. Les prédictions de test et de holdout de ces essais sont en base (`prediction` : classe réelle 0-3, classe prédite,
P(hausse)) : chaque mesure manquante est recalculée pli par pli, avec les fonctions mêmes de l'évaluation (`validation/direction.py`,
`models/calibration.brier_score`, `validation/metrics`), puis ajoutée à `fold_metric`.

Ajout seulement (`INSERT OR IGNORE`) : une mesure déjà présente n'est jamais réécrite, aucune autre table n'est touchée. Idempotent :
une deuxième passe ne fait rien. Lignes `live` (classe réelle binaire, pas 0-3) et chemins CPCV (`path_id >= 0`) ignorés.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

import numpy as np
from sklearn.metrics import matthews_corrcoef

from patrick.models import calibration as calibration_lib
from patrick.validation import direction as direction_lib

SPLITS = ("test", "holdout")      # `valid` : aucune prédiction gardée
DIRECTION_METRICS = (direction_lib.METRIC_AUC, direction_lib.METRIC_F1, direction_lib.METRIC_ACC)
BACKFILLED = (*DIRECTION_METRICS, "Brier_up", "MCC_4cls")
MIN_ROWS = 20            # un pli plus court ne donne pas une AUC lisible


def candidate_trials(conn: sqlite3.Connection) -> list[int]:
    """Essais qui portent des prédictions : meilleurs essais (`is_best`) et champions en titre."""
    ids = {r[0] for r in conn.execute("SELECT trial_id FROM trial WHERE is_best = 1")}
    ids |= {r[0] for r in conn.execute("SELECT trial_id FROM champion WHERE trial_id IS NOT NULL")}
    return sorted(ids)


def _present(conn: sqlite3.Connection, trial_ids: list[int]) -> dict[int, dict[str, set[str]]]:
    """`{trial_id: {split: {métriques présentes}}}` pour les mesures du rattrapage."""
    out: dict[int, dict[str, set[str]]] = {}
    m_ph = ",".join("?" for _ in BACKFILLED)
    s_ph = ",".join("?" for _ in SPLITS)
    for i in range(0, len(trial_ids), 400):
        chunk = trial_ids[i:i + 400]
        t_ph = ",".join("?" for _ in chunk)
        for trial_id, split, metric in conn.execute(
                f"SELECT DISTINCT trial_id, split, metric FROM fold_metric WHERE trial_id IN ({t_ph}) AND split IN ({s_ph}) "
                f"AND metric IN ({m_ph})", [*chunk, *SPLITS, *BACKFILLED]):
            out.setdefault(trial_id, {}).setdefault(split, set()).add(metric)
    return out


def _incomplete(present: dict[str, set[str]]) -> bool:
    """Le test, ou un autre jeu déjà mesuré, n'a pas toutes les mesures du rattrapage."""
    return any(not set(BACKFILLED) <= present.get(split, set()) for split in {"test", *present})


def fold_rows(y_class, y_pred, p_up) -> dict[str, float]:
    """Les mesures du rattrapage pour UN pli, lignes dans l'ordre chronologique. NaN / absentes quand elles ne se calculent pas."""
    y_class = np.asarray(y_class, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    p_up = np.asarray(p_up, dtype=float)
    out: dict[str, float] = {}
    keep = np.isfinite(y_class)
    if keep.sum() < MIN_ROWS:
        return out
    if np.isfinite(y_pred[keep]).all() and len(np.unique(y_class[keep])) >= 2:
        out["MCC_4cls"] = round(float(matthews_corrcoef(y_class[keep].astype(int), y_pred[keep].astype(int))), 4)
    has_p = keep & np.isfinite(p_up)
    if has_p.sum() >= MIN_ROWS:
        y_up = np.isin(y_class[has_p].astype(int), calibration_lib.UP_CLASSES).astype(float)
        out["Brier_up"] = calibration_lib.brier_score(p_up[has_p], y_up)
        out.update(direction_lib.direction_metrics(y_up, p_up[has_p]))
    return {k: v for k, v in out.items() if v is not None and np.isfinite(v)}


def backfill_trial(conn: sqlite3.Connection, trial_id: int, present: dict[str, set[str]]) -> int:
    """Calcule et ajoute les mesures manquantes d'un essai ; renvoie le nombre de lignes ajoutées (sans commit)."""
    missing_splits = [s for s in SPLITS if not set(BACKFILLED) <= present.get(s, set())]
    if not missing_splits:
        return 0
    s_ph = ",".join("?" for _ in missing_splits)
    rows = conn.execute(
        f"SELECT split, COALESCE(fold_index, 0), y_true, y_pred, p_up FROM prediction WHERE trial_id = ? AND split IN ({s_ph}) "
        "AND path_id = -1 ORDER BY split, fold_index, ts", [trial_id, *missing_splits]).fetchall()
    folds: dict[tuple[str, int], list[tuple]] = {}
    for split, fold, y_true, y_pred, p_up in rows:
        folds.setdefault((split, int(fold)), []).append((y_true, y_pred, p_up))
    inserts = []
    for (split, fold), items in folds.items():
        have = present.get(split, set())
        arr = np.array([[np.nan if v is None else v for v in item] for item in items], dtype=float)
        for metric, value in fold_rows(arr[:, 0], arr[:, 1], arr[:, 2]).items():
            if metric not in have:
                inserts.append((trial_id, fold, split, metric, float(value)))
    if inserts:
        conn.executemany("INSERT OR IGNORE INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, ?, ?, ?, ?)", inserts)
    return len(inserts)


def backfill(conn: sqlite3.Connection, trial_ids: list[int] | None = None, limit: int | None = None,
             progress: Callable[[int, int], None] | None = None, commit_every: int = 200) -> dict:
    """Rattrape le panneau des essais `trial_ids` (par défaut `candidate_trials`). Renvoie `{n_trials, n_touched, n_rows, seconds}`."""
    started = time.time()
    ids = candidate_trials(conn) if trial_ids is None else sorted(set(trial_ids))
    present = _present(conn, ids)
    todo = [t for t in ids if _incomplete(present.get(t, {}))]
    if limit is not None:
        todo = todo[:limit]
    n_rows = n_touched = 0
    for i, trial_id in enumerate(todo, 1):
        added = backfill_trial(conn, trial_id, present.get(trial_id, {}))
        n_rows += added
        n_touched += int(added > 0)
        if i % commit_every == 0:
            conn.commit()
            if progress is not None:
                progress(i, len(todo))
    conn.commit()
    return {"n_trials": len(todo), "n_touched": n_touched, "n_rows": n_rows, "seconds": round(time.time() - started, 1)}
