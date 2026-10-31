"""Répartition haut / bas des classes réelles et prédites d'un run, lue dans la table `prediction`.

La cible a 4 classes (baisse forte, baisse faible, hausse faible, hausse forte : `features/target.py`) ; « haut » = hausse faible ou
forte (classes 2 et 3), « bas » = classes 0 et 1. Les mouvements quasi nuls sont retirés de la cible, donc haut + bas = 100 %.

À quoi ça sert : un modèle qui répondrait presque toujours « hausse » (ou « baisse ») peut afficher un bon score sur un marché qui
monte. SMOTE rééquilibre l'ENTRAÎNEMENT, pas ce que le modèle prédit ensuite : cette répartition lit les prédictions réelles sur les
échantillons d'évaluation (test walk-forward ou chemins CPCV, puis holdout), jamais l'entraînement."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable

UP_FROM = 2              # classes 2 et 3 = hausse
ONE_SIDED_ABOVE = 0.70   # au-delà, le modèle prédit « presque toujours » du même côté
N_CLASSES = 4
_SPLITS = {"test": "test", "test_path": "test", "holdout": "holdout"}      # split de la table -> libellé affiché


def summarize(rows: Iterable[tuple[int, int, int]]) -> dict | None:
    """`rows` : (classe réelle, classe prédite, effectif). `None` si l'échantillon est vide."""
    true_n, pred_n = [0] * N_CLASSES, [0] * N_CLASSES
    for y_true, y_pred, n in rows:
        if 0 <= y_true < N_CLASSES and 0 <= y_pred < N_CLASSES:
            true_n[y_true] += n
            pred_n[y_pred] += n
    total = sum(true_n)
    if total == 0:
        return None
    true = [c / total for c in true_n]
    pred = [c / total for c in pred_n]
    true_up, pred_up = sum(true[UP_FROM:]), sum(pred[UP_FROM:])
    return {"n": total, "true": true, "pred": pred,
            "true_up": true_up, "true_down": 1.0 - true_up, "pred_up": pred_up, "pred_down": 1.0 - pred_up,
            "pred_one_sided": max(pred_up, 1.0 - pred_up) > ONE_SIDED_ABOVE}


def counts_sql(n_trials: int) -> str:
    """Effectifs (essai, échantillon, classe réelle, classe prédite). `+split` (plus unaire) interdit à SQLite d'utiliser
    `idx_pred_split` : sans statistiques, dès ~20 essais il le préférait à la clé primaire et balayait toute la table (> 100 s sur
    4,8 Go) ; la lecture doit rester une recherche par `trial_id`."""
    ph = ",".join("?" for _ in range(n_trials))
    return ("SELECT trial_id, split, CAST(y_true AS INTEGER), CAST(y_pred AS INTEGER), COUNT(*) FROM prediction "
            f"WHERE trial_id IN ({ph}) AND +split IN ('test', 'test_path', 'holdout') AND y_true IS NOT NULL "
            "GROUP BY trial_id, split, 3, 4")


def for_trials(conn: sqlite3.Connection, trial_ids: list[int]) -> dict[int, dict[str, dict]]:
    """`{trial_id: {"test": résumé, "holdout": résumé}}` ; un essai sans prédiction évaluée est absent. Une seule requête
    (≤ 16 lignes par essai et par échantillon) : les prédictions `live` et celles sans classe réelle sont ignorées."""
    if not trial_ids:
        return {}
    grouped: dict[int, dict[str, list[tuple[int, int, int]]]] = {}
    for trial_id, split, y_true, y_pred, n in conn.execute(counts_sql(len(trial_ids)), trial_ids):
        grouped.setdefault(trial_id, {}).setdefault(_SPLITS[split], []).append((y_true, y_pred, n))
    out: dict[int, dict[str, dict]] = {}
    for trial_id, by_split in grouped.items():
        summaries = {name: s for name, rows in by_split.items() if (s := summarize(rows)) is not None}
        if summaries:
            out[trial_id] = summaries
    return out


def for_runs(conn: sqlite3.Connection, run_ids: list[str], best_trial_by_run: dict[str, int] | None = None) -> dict[str, dict[str, dict]]:
    """Même résultat pour le meilleur essai de chaque run, indexé par `run_id`. `best_trial_by_run` : essais déjà choisis (le meilleur
    provisoire d'un run interrompu compris), sinon `is_best = 1`."""
    if not run_ids:
        return {}
    if best_trial_by_run is None:
        ph = ",".join("?" for _ in run_ids)
        best_trial_by_run = dict(conn.execute(f"SELECT run_id, trial_id FROM trial WHERE run_id IN ({ph}) AND is_best = 1", run_ids))
    best = {run_id: best_trial_by_run[run_id] for run_id in run_ids if run_id in best_trial_by_run}
    by_trial = for_trials(conn, list(best.values()))
    return {run_id: by_trial[trial_id] for run_id, trial_id in best.items() if trial_id in by_trial}
