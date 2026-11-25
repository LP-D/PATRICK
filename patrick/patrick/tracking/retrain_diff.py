"""Ce qui a changé entre deux champions successifs d'une même paire (FO18 du 25/11).

Le modèle en titre d'une paire cible × horizon est remplacé au fil des réentraînements ; chaque champion est archivé (`model_archive` :
variables retenues, hyperparamètres, métriques de test et de holdout). Ici on compare le champion en titre au dernier champion qu'il a remplacé :
variables entrées et sorties, hyperparamètres modifiés, écarts des métriques. Lecture seule de l'archive.
"""
from __future__ import annotations

import json
import sqlite3

METRICS = ("AUC_dir", "AUC_ovr_4cls", "Brier_up", "F1_dir", "MCC_4cls")


def _load(raw: str | None):
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _current(conn: sqlite3.Connection, target: str, horizon: int) -> dict | None:
    """Le champion en titre, décrit comme une ligne d'archive (variables lues dans les métadonnées du modèle exporté)."""
    from patrick.tracking import champions
    row = conn.execute("SELECT run_id, promoted_at FROM champion WHERE target = ? AND horizon = ?", (target, horizon)).fetchone()
    if row is None:
        return None
    trial = champions.best_trial(conn, row[0]) or {}
    meta = champions.model_meta(trial.get("artifact_path"))
    params = meta.get("best_params") or _load(trial.get("params_json")) or {}
    tid = trial.get("trial_id")
    return {"run_id": row[0], "decided_at": row[1], "algo": trial.get("algo"), "n_features": trial.get("n_features"),
            "features": meta.get("feature_names"), "params": params,
            "test": champions._metrics(conn, tid, "test") if tid else None, "holdout": champions._metrics(conn, tid, "holdout") if tid else None}


def last_two(conn: sqlite3.Connection, target: str, horizon: int) -> list[dict]:
    """[champion en titre, dernier champion remplacé] (l'archive ne garde que les champions REMPLACÉS : `role = 'replaced_champion'`)."""
    current = _current(conn, target, horizon)
    row = conn.execute(
        "SELECT run_id, decided_at, algo, n_features, feature_names_json, params_json, wf_metrics_json, holdout_metrics_json "
        "FROM model_archive WHERE target = ? AND horizon = ? AND role = 'replaced_champion' ORDER BY decided_at DESC, archive_id DESC LIMIT 1",
        (target, horizon)).fetchone()
    out = [current] if current else []
    if row is not None:
        keys = ("run_id", "decided_at", "algo", "n_features", "features", "params", "test", "holdout")
        d = dict(zip(keys, row, strict=True))
        for k in ("features", "params", "test", "holdout"):
            d[k] = _load(d[k])
        out.append(d)
    return out


def diff(conn: sqlite3.Connection, target: str, horizon: int) -> dict | None:
    """`{new, old, features_in, features_out, params_changed, metrics}` ; None s'il n'y a pas deux champions archivés."""
    pair = last_two(conn, target, horizon)
    if len(pair) < 2:
        return None
    new, old = pair
    f_new, f_old = set(new["features"] or []), set(old["features"] or [])
    p_new, p_old = new["params"] or {}, old["params"] or {}
    params = {k: (p_old.get(k), p_new.get(k)) for k in sorted(set(p_new) | set(p_old)) if p_old.get(k) != p_new.get(k)}
    metrics = {}
    for split in ("test", "holdout"):
        a, b = old[split] or {}, new[split] or {}
        for m in METRICS:
            if a.get(m) is not None or b.get(m) is not None:
                metrics[f"{split}:{m}"] = (a.get(m), b.get(m))
    return {"new": {k: new[k] for k in ("run_id", "decided_at", "algo", "n_features")},
            "old": {k: old[k] for k in ("run_id", "decided_at", "algo", "n_features")},
            "features_in": sorted(f_new - f_old), "features_out": sorted(f_old - f_new), "features_kept": len(f_new & f_old),
            "params_changed": params, "metrics": metrics}
