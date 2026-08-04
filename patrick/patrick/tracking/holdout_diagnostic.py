"""Rapport d'audit (session de correction), C4 -- diagnostic holdout EN LECTURE
SEULE : `fold_metric[split='holdout']` (Phase 2.1) n'est peuplé que pour le
trial gagnant (`is_best=1`), jamais pour l'ensemble de la grille SCAN, rendant
impossible toute corrélation de rang test/holdout (audit, section E : n=1,
non calculable). `holdout_diagnostic` (migration 0004) stocke le score holdout
de TOUS les trials de la grille dans une table SÉPARÉE, pour permettre ce
diagnostic.

CONTRAINTE STRUCTURELLE, NON NÉGOCIABLE : ce module ne doit JAMAIS être
importé par `patrick/selection/*`, `patrick/pipeline/leaderboard.py`, ni
`patrick/tuning/*` -- le holdout ne doit jamais influencer un choix de config,
seulement le documenter après coup. Garanti par
`tests/test_holdout_diagnostic_isolation.py` (inspection statique des imports
de ces modules), pas seulement par convention.
"""
from __future__ import annotations

import sqlite3

import numpy as np
from scipy import stats


def write_holdout_diagnostic(conn: sqlite3.Connection, trial_id: int, metrics: dict) -> None:
    rows = [(trial_id, name, float(value))
            for name, value in metrics.items() if value is not None and value == value]  # exclut NaN
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO holdout_diagnostic (trial_id, metric, value) VALUES (?, ?, ?)",
            rows,
        )


def read_holdout_diagnostic_for_run(conn: sqlite3.Connection, run_id: str,
                                     metric: str = "F1_dir") -> list[dict]:
    """Lecture SEULE, pour rapport/diagnostic -- ne doit jamais être appelée
    depuis la sélection/le leaderboard/le tuning (cf. docstring de module)."""
    rows = conn.execute(
        "SELECT hd.trial_id, hd.value FROM holdout_diagnostic hd "
        "JOIN trial t ON t.trial_id = hd.trial_id "
        "WHERE t.run_id = ? AND hd.metric = ?",
        (run_id, metric),
    ).fetchall()
    return [{"trial_id": r[0], "value": r[1]} for r in rows]


def spearman_test_vs_holdout(conn: sqlite3.Connection, run_id: str, metric: str = "F1_dir") -> dict:
    """Corrélation de rang de Spearman entre le classement des trials de ce run
    sur TEST (moyenne `fold_metric[split='test']` par trial) et sur HOLDOUT
    (`holdout_diagnostic`) -- diagnostic de généralisation de la procédure de
    sélection (rapport d'audit, section E), affiché en LECTURE SEULE (rapport),
    jamais utilisé pour choisir une config."""
    test_rows = conn.execute(
        "SELECT trial_id, AVG(value) FROM fold_metric "
        "WHERE split = 'test' AND metric = ? AND trial_id IN "
        "(SELECT trial_id FROM trial WHERE run_id = ?) GROUP BY trial_id",
        (metric, run_id),
    ).fetchall()
    test_map = dict(test_rows)
    holdout_map = {r["trial_id"]: r["value"] for r in read_holdout_diagnostic_for_run(conn, run_id, metric)}

    common = sorted(set(test_map) & set(holdout_map))
    if len(common) < 3:
        return {"rho": float("nan"), "p_value": float("nan"), "n_trials": len(common)}

    test_vals = [test_map[t] for t in common]
    holdout_vals = [holdout_map[t] for t in common]
    rho, p = stats.spearmanr(test_vals, holdout_vals)
    rho = float(rho) if np.isfinite(rho) else float("nan")
    p = float(p) if np.isfinite(p) else float("nan")
    return {"rho": rho, "p_value": p, "n_trials": len(common)}
