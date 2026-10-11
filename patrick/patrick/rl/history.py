"""Suppression d'un run de reinforcement learning depuis l'Historique.

Un run RL est une ligne de la table `job` (pas de table `run`). Deux cas, selon qu'il a produit un Sharpe ou non :

- **terminé (`done`)** : la ligne RESTE (statut `done`, configuration intacte), marquée `phase = 'deleted'`, avec son résultat et son
  journal vidés. Elle continue donc de compter dans le Sharpe déflaté des prochains runs sur la même cible
  (`rl.run.count_prior_rl_runs`) : un Sharpe choisi parmi N tentatives est gonflé, et supprimer les tentatives décevantes ne doit pas
  le cacher -- même règle que `trial_registry` côté ML, qu'on n'élague jamais. La colonne `status` est contrainte à
  queued/running/done/error (migration 0002) : on ne touche pas au schéma d'une base partagée avec un worker en cours, d'où la phase ;
- **en échec (`error`)** : aucun Sharpe, rien à conserver, la ligne disparaît.

Les fichiers du run (résultat, CSV hors échantillon, modèles du dernier pli) sont supprimés eux aussi, mais seulement ceux listés dans
son propre résultat ET situés dans son dossier de sortie ; rien n'est supprimé si un autre run RL utilise le même dossier.
"""
from __future__ import annotations

import json
import os
import sqlite3

RL_JOB_FILTER = '%"kind":"rl"%'
DELETED_PHASE = "deleted"


def is_live_rl_job(conn: sqlite3.Connection, job_id: str) -> bool:
    """Vrai si `job_id` est un run RL qui n'a pas été supprimé."""
    return conn.execute("SELECT 1 FROM job WHERE job_id = ? AND config_json LIKE ? AND phase != ?",
                        (job_id, RL_JOB_FILTER, DELETED_PHASE)).fetchone() is not None


def is_deleted_rl_job(conn: sqlite3.Connection, job_id: str) -> bool:
    return conn.execute("SELECT 1 FROM job WHERE job_id = ? AND config_json LIKE ? AND phase = ?",
                        (job_id, RL_JOB_FILTER, DELETED_PHASE)).fetchone() is not None


def live_rl_job_ids(conn: sqlite3.Connection, job_ids: list[str]) -> set[str]:
    """Parmi `job_ids`, ceux qui sont des runs RL non supprimés."""
    if not job_ids:
        return set()
    marks = ", ".join("?" for _ in job_ids)
    rows = conn.execute(f"SELECT job_id FROM job WHERE job_id IN ({marks}) AND config_json LIKE ? AND phase != ?",
                        (*job_ids, RL_JOB_FILTER, DELETED_PHASE)).fetchall()
    return {r[0] for r in rows}


def _output_dir(config_json: str | None) -> str:
    try:
        config = json.loads(config_json or "")
    except (TypeError, ValueError):
        return ""
    output = config.get("output") if isinstance(config, dict) else None
    out_dir = output.get("dir") if isinstance(output, dict) else None
    return out_dir if isinstance(out_dir, str) else ""


def _shared_with_another_run(conn: sqlite3.Connection, job_id: str, root: str) -> bool:
    rows = conn.execute("SELECT config_json FROM job WHERE job_id != ? AND config_json LIKE ? AND phase != ?",
                        (job_id, RL_JOB_FILTER, DELETED_PHASE)).fetchall()
    return any(_output_dir(cfg) and os.path.realpath(_output_dir(cfg)) == root for (cfg,) in rows)


def _remove_files(conn: sqlite3.Connection, job_id: str, config_json: str, result_json: str | None) -> int:
    out_dir = _output_dir(config_json)
    if not out_dir or not result_json:
        return 0
    try:
        artifacts = (json.loads(result_json) or {}).get("artifacts") or {}
    except (TypeError, ValueError, AttributeError):
        return 0
    root = os.path.realpath(out_dir)
    if _shared_with_another_run(conn, job_id, root):
        return 0
    removed = 0
    for path in artifacts.values() if isinstance(artifacts, dict) else ():
        if not isinstance(path, str):
            continue
        real = os.path.realpath(path)
        try:
            inside = os.path.commonpath([root, real]) == root and real != root
        except ValueError:                          # autre lecteur : forcément hors du dossier
            inside = False
        if inside and os.path.isfile(real):
            os.remove(real)
            removed += 1
    for folder in (os.path.join(root, "models"), root):
        try:
            os.rmdir(folder)                        # seulement s'il est vide : jamais de suppression récursive
        except OSError:
            pass
    return removed


def delete_rl_run(conn: sqlite3.Connection, job_id: str) -> dict:
    """Supprime un run RL terminé ou en échec. `LookupError` s'il n'existe pas (ou n'est pas un run RL), `ValueError` s'il est en cours
    ou en file (le stopper d'abord). Renvoie `{"kept_as_trial": bool, "files_removed": int}`."""
    row = conn.execute("SELECT status, config_json, result_json FROM job WHERE job_id = ? AND config_json LIKE ? AND phase != ?",
                       (job_id, RL_JOB_FILTER, DELETED_PHASE)).fetchone()
    if row is None:
        raise LookupError(job_id)
    status, config_json, result_json = row
    if status not in ("done", "error"):
        raise ValueError(f"Un run RL {status} ne peut pas être supprimé : arrête-le d'abord.")
    with conn:
        if status == "done":
            changed = conn.execute("UPDATE job SET phase = ?, result_json = NULL, log_tail = '[]' WHERE job_id = ? AND status = 'done'",
                                   (DELETED_PHASE, job_id)).rowcount
        else:
            changed = conn.execute("DELETE FROM job WHERE job_id = ? AND status = 'error'", (job_id,)).rowcount
    if changed != 1:
        raise ValueError("Ce run RL vient de changer d'état : réessaie.")
    return {"kept_as_trial": status == "done", "files_removed": _remove_files(conn, job_id, config_json, result_json)}
