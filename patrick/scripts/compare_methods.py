"""Méthode 2 contre méthode 3 sur le holdout d'un run enregistré, sans toucher à la production (ADR 0011).

Rejoue le meilleur essai d'un run stocké (même snapshot, même nombre de variables, même échantillonneur, même algorithme, mêmes hyperparamètres) deux fois : réserve de variables de
la méthode 2 (niveaux bruts) puis de la méthode 3 (niveaux différenciés fractionnairement). Base, cache et cache de variables sont TEMPORAIRES ; seul le data lake est lu. Évalué sur tous
les jours du holdout (la population du live) : exactitude directionnelle, AUC de P(hausse), Brier de P(hausse) face au taux de hausse de l'entraînement, et part des variables retenues qui sont
des niveaux bruts.

Usage : python scripts/compare_methods.py <symbole> [horizon]   (écrit `compare_methods_<symbole>_h<horizon>.json` dans `PATRICK_COMPARE_OUT`, sinon le dossier temporaire)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "^GSPC"
HORIZON = int(sys.argv[2]) if len(sys.argv) > 2 else 5

from patrick import paths

REAL_DB_PATH = paths.db_path()                      # la vraie base, lue en lecture seule : relevée avant la redirection ci-dessous
tmp = tempfile.mkdtemp(prefix="methods_")
os.environ["PATRICK_DB_PATH"] = os.path.join(tmp, "p.db")
os.environ["PATRICK_CACHE_ROOT"] = os.path.join(tmp, "cache")
os.environ["PATRICK_FEATURE_CACHE_ROOT"] = os.path.join(tmp, "fcache")

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import RobustScaler

from patrick.config.schema import RunConfig
from patrick.data import alignment
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.features.alpha_target import run_target
from patrick.features.target import classify_return
from patrick.pipeline import engine as E
from patrick.tracking import db as trackdb
from patrick.validation.walkforward import build_fold_cuts

REAL_DB = "file:" + REAL_DB_PATH.replace("\\", "/") + "?mode=ro"
ro = sqlite3.connect(REAL_DB, uri=True, timeout=5)
row = ro.execute("""SELECT r.run_id, r.config_json, r.snapshot_id, r.seed, t.trial_id, t.regime, t.n_features, t.sampler, t.algo, t.params_json
                    FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1
                    JOIN dm_result d ON d.run_id = r.run_id AND d.sample = 'holdout'
                    WHERE r.status = 'done' AND r.horizon = ? AND r.target = ? AND t.algo NOT IN ('MLP', 'Stacking')
                    ORDER BY r.started_at DESC LIMIT 1""", (HORIZON, SYMBOL)).fetchone()
if row is None:
    sys.exit(f"aucun run terminé pour {SYMBOL} h={HORIZON}")
run_id, cfg_json, snap_id, seed, trial_id, regime, n_feat, sampler, algo, params_json = row
print(f"run {run_id} trial {trial_id} regime={regime} N={n_feat} {sampler} {algo} snapshot={snap_id}")
base_cfg = RunConfig.model_validate_json(cfg_json)
target_col = clean_symbol(base_cfg.objective.target_symbol)
raw = DataStore().load(f"raw_{base_cfg.objective.target_symbol}", snapshot_id=snap_id)
raw = alignment.apply_spec(raw, base_cfg.objective.alignment)
conn = trackdb.connect()
all_dates = raw.index
n_wf = E._walk_forward_span(all_dates, base_cfg.validation.holdout_months, base_cfg.validation.min_train_frac)
fold_cuts = build_fold_cuts(all_dates[:n_wf], base_cfg.validation.n_wf_folds, base_cfg.validation.min_train_frac)
hs = all_dates[n_wf]
best_params = E._parse_params(params_json)


def is_raw_level(name: str) -> bool:
    return name in raw.columns or name.endswith("_level") or any(name.endswith(f"_lag{k}") for k in (1, 5, 10))


def evaluate(method: int) -> dict:
    cfg = base_cfg.model_copy(deep=True)
    cfg.validation.method_version = method
    t0 = time.time()
    base_pool = E.build_base_feature_pool(raw, cfg, target_col)
    builder = E._FoldPoolBuilder(raw, cfg, target_col, base_pool, fold_cuts, conn=conn, snapshot_id=snap_id)
    feature_pool = [c for c in builder.get(fold_cuts[0]).columns if c != target_col]
    universe = E._FoldUniverse(raw, target_col, cfg)
    pool = builder.get(n_wf)
    fp = universe.features(feature_pool, universe.prefix_mask(n_wf), "holdout")
    price = pool[target_col].astype(float)
    ret = price.shift(-HORIZON) / price - 1
    target_series, reg_r, thr = run_target(pool, cfg, target_col, HORIZON, n_wf)
    idx = target_series.index
    tr, te = np.asarray(idx < hs), np.asarray(idx >= hs)
    if regime != "GLOBAL":
        sel = reg_r.reindex(idx).fillna("NORMAL").values == regime
        tr, te = tr & sel, te & sel
    if hasattr(E, "non_flat_mask"):
        tr = tr & E.non_flat_mask(target_series)
    y_tr = target_series.values[tr].astype(int)
    all_te_idx = pool.index[(pool.index >= hs) & ret.reindex(pool.index).notna().values]
    Xdf = pool[fp]
    sc = RobustScaler()
    X_tr = E._finite_scaled(sc.fit_transform(E._finite_features(Xdf.reindex(idx).values[tr], "tr")), "tr")
    X_all = E._finite_scaled(sc.transform(E._finite_features(Xdf.reindex(all_te_idx).values, "te")), "te")
    r_all = ret.reindex(all_te_idx).values
    g = thr.get("GLOBAL")
    y_all = np.array([classify_return(r, "GLOBAL", {"GLOBAL": g}) for r in r_all])
    cols = E._select(conn, target_col, HORIZON, f"{snap_id}|m{method}", cfg, X_tr, y_tr, n_feat, seed)
    _met, y_pred, _conf, p_up = E._fit_eval_full(X_tr[:, cols], y_tr, X_all[:, cols], y_all, sampler, algo, seed,
                                                 calibration=cfg.models.calibration, calibration_method=cfg.models.calibration_method,
                                                 calibration_gap=HORIZON, **best_params)
    up_true = (r_all > 0).astype(float)
    up_pred = np.asarray(y_pred) >= 2
    kept = [fp[c] for c in cols]
    out = {"method": method, "n_holdout": len(all_te_idx), "n_pool": len(fp), "kept": kept,
           "share_raw_level_kept": float(np.mean([is_raw_level(k) for k in kept])) if kept else 0.0,
           "acc_all": float((up_true.astype(bool) == up_pred).mean()), "seconds": round(time.time() - t0)}
    if p_up is not None:
        p = np.asarray(p_up, dtype=float)
        base_rate = float((target_series.values[tr] >= 2).mean())
        out["brier_model"] = float(np.mean((p - up_true) ** 2))
        out["brier_train_rate"] = float(np.mean((base_rate - up_true) ** 2))
        if len(set(up_true)) == 2:
            out["auc_all"] = float(roc_auc_score(up_true, p))
    return out


results = [evaluate(2), evaluate(3)]
for r in results:
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "kept"})
print("variables retenues (méthode 2) :", results[0]["kept"])
print("variables retenues (méthode 3) :", results[1]["kept"])
out_path = os.path.join(os.environ.get("PATRICK_COMPARE_OUT", tmp), f"compare_methods_{clean_symbol(SYMBOL)}_h{HORIZON}.json")
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump({"symbol": SYMBOL, "horizon": HORIZON, "run_id": run_id, "results": results}, fh, indent=1)
print("OK", out_path)
