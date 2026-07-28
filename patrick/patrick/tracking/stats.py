"""Requêtes de validité statistique (Phase 2) sur la base `patrick.db` — pont
entre les fonctions pures de `patrick.validation` (dsr/pbo/diebold_mariano,
qui ne connaissent pas SQLite) et l'historique des runs persistés (Phase 1).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from patrick.validation.pbo import compute_pbo


def count_cumulative_trials(conn: sqlite3.Connection, target: str, horizon: int | None = None) -> int:
    """Nombre total d'essais (`trial`) réalisés pour cette cible, tout
    l'historique de runs confondu — pas seulement le run courant (Phase 2.2).
    C'est ce nombre, pas celui d'un seul run, qui doit corriger un Sharpe/PBO :
    chercher la meilleure config sur 50 runs successifs revient à en avoir
    essayé bien plus qu'un run isolé ne le suggère."""
    if horizon is not None:
        row = conn.execute(
            "SELECT COUNT(*) FROM trial JOIN run ON trial.run_id = run.run_id "
            "WHERE run.target = ? AND run.horizon = ?",
            (target, horizon),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM trial JOIN run ON trial.run_id = run.run_id "
            "WHERE run.target = ?",
            (target,),
        ).fetchone()
    return int(row[0]) if row else 0


def pbo_for_target(conn: sqlite3.Connection, target: str, horizon: int, regime: str,
                    metric: str = "F1_dir") -> dict:
    """PBO (cf. `validation.pbo.compute_pbo`) sur tous les essais historiques
    d'un (cible, horizon, régime) donné — pas seulement ceux du run courant :
    plus l'historique de runs est long, plus l'estimation est significative.
    Les trials aux folds incomplets (crash, fold trop court) sont exclus de la
    matrice plutôt que remplis de force, pour ne pas fausser les moyennes
    IS/OOS par bloc."""
    rows = conn.execute(
        "SELECT trial.trial_id, fold_metric.fold_index, fold_metric.value "
        "FROM trial "
        "JOIN run ON trial.run_id = run.run_id "
        "JOIN fold_metric ON fold_metric.trial_id = trial.trial_id "
        "WHERE run.target = ? AND run.horizon = ? AND trial.regime = ? "
        "AND fold_metric.split = 'test' AND fold_metric.metric = ?",
        (target, horizon, regime, metric),
    ).fetchall()
    if not rows:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan}

    df = pd.DataFrame(rows, columns=["trial_id", "fold_index", "value"])
    pivot = df.pivot_table(index="trial_id", columns="fold_index", values="value").dropna()
    if pivot.empty:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan}
    return compute_pbo(pivot.values)
