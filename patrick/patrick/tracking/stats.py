"""Requêtes de validité statistique (Phase 2) sur la base `patrick.db` — pont
entre les fonctions pures de `patrick.validation` (dsr/pbo/diebold_mariano,
qui ne connaissent pas SQLite) et l'historique des runs persistés (Phase 1).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from patrick.validation.fdr import benjamini_hochberg
from patrick.validation.pbo import compute_pbo
from patrick.validation.pbo_reliability import pbo_reliability


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
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan,
                "reliability": pbo_reliability(np.empty((0, 0)))}
    result = compute_pbo(pivot.values)
    # Rapport de correction, C5 -- diagnostic de fiabilité calculé séparément
    # (cf. `validation/pbo_reliability.py`, n'importe/ne modifie pas
    # `compute_pbo`) : intervalle de confiance par bootstrap + refus explicite
    # sous un nombre minimal de blocs -- un PBO ponctuel isolé n'est pas
    # interprétable seul (cf. rapport d'audit, section E).
    result["reliability"] = pbo_reliability(pivot.values)
    return result


def pbo_for_target_cpcv(conn: sqlite3.Connection, target: str, horizon: int, regime: str,
                         metric: str = "F1_dir") -> dict:
    """Phase 6.1 (P6.1) -- PBO branché sur les CHEMINS de backtest CPCV
    (`validation/cpcv.py::path_assignment`) plutôt que sur les blocs
    walk-forward -- raison d'être principale de cette brique : avec
    `n_groups=7`/`k_test_groups=2` par défaut, 6 chemins sont TOUJOURS
    disponibles par (cible, horizon, régime) dès qu'un seul run CPCV a
    tourné, contre potentiellement moins de `MIN_BLOCKS` blocs walk-forward
    (garde C5) sur un historique de runs encore court. Même mécanisme que
    `pbo_for_target` (`compute_pbo` non modifié, cf. C5), juste une source
    différente : `split='test_path'` (fold_index=chemin), écrit par
    `pipeline/engine.py::_run_cpcv_scan`, jamais mélangé avec les métriques
    par combinaison (`split='test'`, fold_index=combinaison)."""
    rows = conn.execute(
        "SELECT trial.trial_id, fold_metric.fold_index, fold_metric.value "
        "FROM trial "
        "JOIN run ON trial.run_id = run.run_id "
        "JOIN fold_metric ON fold_metric.trial_id = trial.trial_id "
        "WHERE run.target = ? AND run.horizon = ? AND trial.regime = ? "
        "AND fold_metric.split = 'test_path' AND fold_metric.metric = ?",
        (target, horizon, regime, metric),
    ).fetchall()
    if not rows:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan,
                "reliability": pbo_reliability(np.empty((0, 0)))}

    df = pd.DataFrame(rows, columns=["trial_id", "fold_index", "value"])
    pivot = df.pivot_table(index="trial_id", columns="fold_index", values="value").dropna()
    if pivot.empty:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan,
                "reliability": pbo_reliability(np.empty((0, 0)))}
    result = compute_pbo(pivot.values)
    result["reliability"] = pbo_reliability(pivot.values)
    return result


def fdr_across_targets(conn: sqlite3.Connection, alpha: float = 0.10,
                        kind: str = "class_specific") -> dict:
    """Phase 6.4 (P6.4) -- correction FDR (Benjamini-Hochberg) à travers
    TOUTES les cibles ayant un résultat Diebold-Mariano dans l'historique de
    runs (`dm_result`, migration 0009) : pour chaque cible, la MEILLEURE
    (plus petite) p-value DM obtenue sur n'importe lequel de ses runs est
    retenue -- essayer plusieurs cibles et ne retenir que la meilleure
    soulève le même problème de tests multiples qu'essayer plusieurs configs
    sur une seule cible (section 4, METHODOLOGY.md), à l'échelle des cibles
    cette fois. `compute_pbo`/`benjamini_hochberg` eux-mêmes ne sont jamais
    modifiés ici (même discipline que C5/P6.1) -- seule la requête source
    change.

    `kind` (Phase X5, migration 0010) : filtre sur `"class_specific"` (défaut
    -- la comparaison propre à la classe d'actif de chaque cible, le résultat
    PRINCIPAL) ou `"common"` (persistance de classe, comparaison secondaire
    permettant de vérifier les classes entre elles sur un pied d'égalité) --
    jamais les deux mélangées dans un même MIN, ce qui ferait concurrence
    entre deux comparaisons de nature différente pour la même cible."""
    rows = conn.execute(
        "SELECT run.target, MIN(dm_result.p_value) FROM dm_result "
        "JOIN run ON dm_result.run_id = run.run_id "
        "WHERE dm_result.kind = ? "
        "GROUP BY run.target",
        (kind,),
    ).fetchall()
    p_values = {target: p for target, p in rows}
    return benjamini_hochberg(p_values, alpha=alpha)
