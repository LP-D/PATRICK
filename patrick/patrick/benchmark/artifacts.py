"""Artefacts de non-régression d'un run : ce que les optimisations EXACTES des
sprints suivants doivent reproduire à l'identique.

Chaque artefact est écrit en pleine précision (CSV/JSON) et résumé par un
digest sur sa forme normalisée (flottants arrondis à 10 décimales, comme
`tests/test_run_pipeline_golden.py`). Deux runs sont « identiques » ssi tous
leurs digests coïncident (`compare_baselines`).

Ce qui N'EST PAS disponible (documenté dans le rapport, non reconstruit) :
- probabilités complètes par classe : le pipeline ne persiste que
  `y_proba` (probabilité de la classe prédite) et `p_up` ;
- prédictions des essais Optuna internes (seuls leurs scores CV existent) ;
- graines/état interne des échantillonneurs par fit.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ND = 10  # décimales de comparaison, comme le golden master


def _norm(obj):
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else round(float(obj), ND)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.DataFrame):
        return _norm(obj.to_dict("records"))
    if isinstance(obj, pd.Timestamp):
        return str(obj)
    return obj


def _df_digest(df: pd.DataFrame) -> str:
    rounded = df.copy()
    for c in rounded.columns:
        if pd.api.types.is_float_dtype(rounded[c]):
            rounded[c] = rounded[c].round(ND)
    buf = io.StringIO()
    rounded.to_csv(buf, index=False, lineterminator="\n")
    return hashlib.sha256(buf.getvalue().encode()).hexdigest()


def _json_digest(obj) -> str:
    return hashlib.sha256(json.dumps(_norm(obj), sort_keys=True, default=str).encode()).hexdigest()


def _sql(conn: sqlite3.Connection, query: str) -> pd.DataFrame:
    cur = conn.execute(query)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


_TRIAL_KEY = ("run.horizon AS horizon, trial.regime, trial.algo, trial.sampler, trial.n_features, "
              "trial.selector, trial.params_json")


def _write_df(out_dir: str, name: str, df: pd.DataFrame, digests: dict) -> None:
    path = os.path.join(out_dir, name)
    df.to_csv(path, index=False, lineterminator="\n")  # pleine précision (repr)
    digests[name] = _df_digest(df)


def _write_json(out_dir: str, name: str, obj, digests: dict) -> None:
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        json.dump(_norm_full(obj), f, indent=1, sort_keys=True, default=str)
    digests[name] = _json_digest(obj)


def _norm_full(obj):
    """Comme `_norm` mais sans arrondi (fichier lisible, pleine précision)."""
    if isinstance(obj, dict):
        return {str(k): _norm_full(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_norm_full(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.DataFrame):
        return _norm_full(obj.to_dict("records"))
    return obj


def capture_baseline(result: dict, db_path: str, out_dir: str, optuna_db_path: str | None = None) -> dict:
    """Écrit les artefacts dans `out_dir`, renvoie `{artefact: digest}`."""
    os.makedirs(out_dir, exist_ok=True)
    digests: dict[str, str] = {}
    conn = sqlite3.connect(db_path)
    try:
        _write_df(out_dir, "leaderboard.csv", pd.DataFrame(result["leaderboard"]), digests)   # incl. features par fold
        _write_df(out_dir, "tuned.csv", pd.DataFrame(result["tuned"]), digests)              # incl. best_params
        _write_df(out_dir, "fold_metrics.csv", _sql(conn, (
            f"SELECT {_TRIAL_KEY}, fold_metric.fold_index, fold_metric.split, fold_metric.metric, fold_metric.value "
            "FROM fold_metric JOIN trial ON fold_metric.trial_id = trial.trial_id "
            "JOIN run ON trial.run_id = run.run_id "
            "ORDER BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11")), digests)
        pred_cols = [r[1] for r in conn.execute("PRAGMA table_info(prediction)")
                     if r[1] not in ("trial_id",)]
        pcols = ", ".join(f"prediction.{c}" for c in pred_cols)
        _write_df(out_dir, "predictions.csv", _sql(conn, (
            f"SELECT {_TRIAL_KEY}, {pcols} FROM prediction JOIN trial ON prediction.trial_id = trial.trial_id "
            "JOIN run ON trial.run_id = run.run_id "
            "ORDER BY 1, 2, 3, 4, 5, 6, 7, prediction.ts, prediction.split, prediction.fold_index")), digests)
        _write_df(out_dir, "feature_stability.csv", _sql(conn, (
            "SELECT run.horizon, feature_stability.feature, feature_stability.selection_freq "
            "FROM feature_stability JOIN run ON feature_stability.run_id = run.run_id ORDER BY 1, 2")), digests)
        _write_df(out_dir, "baseline_metrics.csv", _sql(conn, (
            "SELECT run.horizon, baseline_metric.baseline, baseline_metric.split, baseline_metric.metric, "
            "baseline_metric.value FROM baseline_metric JOIN run ON baseline_metric.run_id = run.run_id "
            "ORDER BY 1, 2, 3, 4")), digests)
        _write_df(out_dir, "dm_results.csv", _sql(conn, (
            "SELECT run.horizon, dm_result.kind, dm_result.baseline, dm_result.dm_stat, dm_result.p_value "
            "FROM dm_result JOIN run ON dm_result.run_id = run.run_id ORDER BY 1, 2, 3")), digests)
        _write_df(out_dir, "trial_registry.csv", _sql(conn, (
            "SELECT run.horizon, trial_registry.source, trial_registry.n_trials FROM trial_registry "
            "JOIN run ON trial_registry.run_id = run.run_id ORDER BY 1, 2, 3")), digests)
        _write_df(out_dir, "holdout_diagnostic.csv", _sql(
            conn, "SELECT * FROM holdout_diagnostic ORDER BY 1, 2"), digests)
        _write_df(out_dir, "run_rows.csv", _sql(conn, (
            "SELECT horizon, status, n_trials, seed FROM run ORDER BY horizon")), digests)
    finally:
        conn.close()

    if optuna_db_path and os.path.exists(optuna_db_path):
        _write_df(out_dir, "optuna_trials.csv", _optuna_trials(optuna_db_path), digests)

    def scrub(o):   # identifiants aléatoires / chemins : propres à chaque run, pas des résultats
        if isinstance(o, dict):
            return {k: scrub(v) for k, v in o.items() if k not in ("run_id", "model_path", "path", "archived_path")}
        if isinstance(o, (list, tuple)):
            return [scrub(v) for v in o]
        return o

    keep = ("final_best", "best_before_tuning", "holdout", "diebold_mariano", "cumulative_trials",
            "pbo", "holdout_diagnostic", "champions")
    _write_json(out_dir, "result_summary.json", scrub({k: result.get(k) for k in keep}), digests)   # champion + holdout + PBO

    exported = {}
    for h, path in sorted((result.get("model_paths") or {}).items()):
        bundle = joblib.load(path)
        names = list(bundle["feature_names"])
        X = np.random.default_rng(0).normal(size=(12, len(names)))
        exported[f"h{h}"] = {"features": names,
                             "proba_on_fixed_matrix": np.asarray(bundle["model"].predict_proba(X)).tolist()}
    _write_json(out_dir, "exported_models.json", exported, digests)

    digests["__all__"] = hashlib.sha256(json.dumps(sorted(digests.items())).encode()).hexdigest()
    with open(os.path.join(out_dir, "digests.json"), "w", encoding="utf-8") as f:
        json.dump(digests, f, indent=1, sort_keys=True)
    return digests


def _optuna_trials(optuna_db_path: str) -> pd.DataFrame:
    import optuna
    storage = f"sqlite:///{optuna_db_path}"
    frames = []
    for summary in sorted(optuna.get_all_study_summaries(storage), key=lambda s: s.study_name):
        study = optuna.load_study(study_name=summary.study_name, storage=storage)
        df = study.trials_dataframe(attrs=("number", "value", "params", "state", "intermediate_values"))
        # le nom d'étude embarque `config_hash`, lui-même dépendant du dossier de sortie
        df.insert(0, "study", re.sub(r"_[0-9a-f]{16}_", "_<config_hash>_", summary.study_name))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.astype({c: str for c in out.columns if out[c].dtype == object})


def compare_baselines(dir_a: str, dir_b: str) -> dict:
    """`{"identical": bool, "differences": [...]}` sur les digests ; pour les
    CSV de même forme, l'écart absolu maximal aide à juger « bruit flottant »
    vs « résultat différent »."""
    da = json.loads(Path(dir_a, "digests.json").read_text(encoding="utf-8"))
    db = json.loads(Path(dir_b, "digests.json").read_text(encoding="utf-8"))
    diffs = []
    for name in sorted(set(da) | set(db)):
        if name == "__all__" or da.get(name) == db.get(name):
            continue
        item = {"artifact": name, "a": da.get(name), "b": db.get(name)}
        if name.endswith(".csv") and name in da and name in db:
            a = pd.read_csv(os.path.join(dir_a, name))
            b = pd.read_csv(os.path.join(dir_b, name))
            if a.shape == b.shape and list(a.columns) == list(b.columns):
                num = a.select_dtypes("number").columns
                item["max_abs_diff"] = float(np.nanmax(np.abs(a[num].to_numpy() - b[num].to_numpy()))) if len(num) else 0.0
                item["n_rows_differing"] = int((~(a.fillna("∅").astype(str) == b.fillna("∅").astype(str)).all(axis=1)).sum())
            else:
                item["shape"] = [list(a.shape), list(b.shape)]
        diffs.append(item)
    return {"identical": not diffs, "differences": diffs}
