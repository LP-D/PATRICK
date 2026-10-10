"""Un run de reinforcement learning, du téléchargement au fichier de résultats.

Appelé par `worker.py` pour un job dont la configuration porte `"kind": "rl"` ; la sortie standard (marqueurs `[RL-DATA]`, `[RL-TRAIN]`,
`[RL-EVAL]`, `[RL-PROGRESS] fait/total`, `[RL-SAVE]`) alimente la barre d'avancement du job. Écrit dans `config.output.dir` :
`rl_result.json` (tout le résultat), `rl_oos.csv` (une ligne par date hors échantillon) et les modèles du dernier pli (`models/`).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

import numpy as np
import pandas as pd

from patrick.data.ingest import ingest
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.rl import data as rl_data
from patrick.rl import walkforward
from patrick.rl.config import RLRunConfig


def count_prior_rl_runs(db_path: str | None, target: str, exclude_job: str | None = None) -> int:
    """Nombre de runs RL TERMINÉS sur cette cible (hors le job courant) : chacun est un essai de plus dans le Sharpe déflaté, pour la
    même raison que les configurations Optuna comptent dans celui du ML (un Sharpe choisi parmi N tentatives est gonflé). Un run en
    échec n'a produit aucun Sharpe : il ne compte pas."""
    if not db_path or not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM job WHERE status = 'done' AND job_id != ? "
                               "AND config_json LIKE '%\"kind\":\"rl\"%' AND config_json LIKE ?",
                               (exclude_job or "", f'%"target_symbol":"{target}"%')).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return int(row[0] or 0)


def _native(obj):
    if isinstance(obj, dict):
        return {str(k): _native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_native(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_native(v) for v in obj.tolist()]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    return obj


def run_rl(config: RLRunConfig, store: DataStore | None = None, db_path: str | None = None, job_id: str | None = None,
           force_ingest: bool = False, progress=print) -> dict:
    from patrick.pipeline.engine import _align_raw
    from patrick.rl import agents

    agents.require_rl()
    t0 = time.time()
    store = store or DataStore()
    run_cfg = config.to_run_config()
    progress(f"[RL-DATA] ingestion de {config.objective.target_symbol} et de son univers")
    raw = ingest(config.objective, config.universe, store, force=force_ingest, data_quality=config.data_quality)
    raw = _align_raw(raw, run_cfg, resumed=False)
    target_col = clean_symbol(config.objective.target_symbol)
    data = rl_data.build_rl_data(raw, config, target_col)
    n_trials = count_prior_rl_runs(db_path, config.objective.target_symbol, exclude_job=job_id) + 1

    out_dir = config.output.dir
    os.makedirs(out_dir, exist_ok=True)
    models_dir = os.path.join(out_dir, "models")
    last_fold = {"index": -1}
    saved: list[str] = []

    def on_model(fold_index: int, seed_index: int, model) -> None:
        if fold_index != last_fold["index"]:
            last_fold["index"] = fold_index
            saved.clear()
        os.makedirs(models_dir, exist_ok=True)
        path = os.path.join(models_dir, f"{config.name}_last_fold_seed{seed_index + 1}.zip")
        model.save(path)
        saved.append(path)

    result = walkforward.run_walkforward(
        data, config, agents.train_agent, agents.policy_from_model, agents.ensemble_policy, progress=progress,
        n_trials=n_trials, on_model=on_model)
    oos = result.pop("oos")
    progress(f"[RL-SAVE] écriture des résultats dans {out_dir}")
    csv_path = os.path.join(out_dir, "rl_oos.csv")
    pd.DataFrame({"date": oos["dates"], "position": oos["position"], "net_return": oos["net"], "cost": oos["cost"],
                  "buy_hold_return": oos["buy_hold"], "momentum_return": oos["momentum"]}).to_csv(csv_path, index=False)
    payload = {
        "kind": "rl", "name": config.name, "target": config.objective.target_symbol, "algo": config.rl.algo,
        "start": f"{data.dates[0]:%Y-%m-%d}", "end": f"{data.dates[-1]:%Y-%m-%d}", "n_rows": data.n,
        "n_features_pool": int(data.features.shape[1]), "warnings": data.warnings, **result,
        "elapsed_s": time.time() - t0, "config": json.loads(config.model_dump_json()),
        "artifacts": {"result_json": os.path.join(out_dir, "rl_result.json"), "oos_csv": csv_path,
                      **{f"model_seed{i + 1}": p for i, p in enumerate(saved)}},
    }
    payload = _native(payload)
    with open(os.path.join(out_dir, "rl_result.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, allow_nan=False)
    progress(f"[RL-SAVE] terminé en {payload['elapsed_s']:.0f} s")
    return payload
