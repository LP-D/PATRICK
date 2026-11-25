"""Vues inter-runs de la page `/analyses` : liste de TOUS les entraînements (ML, DL, RL), carte cible × horizon, distribution des scores
par algorithme. Lecture seule, quelques requêtes groupées (aucune requête par run). Les scores sont ceux du panneau d'un modèle (ADR 0023 :
AUC de direction, Brier, MCC, bonne direction), test et holdout."""
from __future__ import annotations

import contextlib
import json
import sqlite3

import numpy as np

from patrick.analysis import stats_core as sc
from patrick.config.target_label import ALPHA_SEP
from patrick.validation import metric_panel


def _rl_rows(conn: sqlite3.Connection) -> list[dict]:
    """Runs RL : les chiffres de tête sont lus par `json_extract` dans SQLite (le résultat d'un run pèse ~130 Ko, une centaine de runs
    pèsent des dizaines de Mo : les parcourir en Python prenait 10 s)."""
    from patrick.rl import reading as rl_reading

    rows = conn.execute(
        "SELECT job_id, status, phase, created_at, started_at, finished_at, config_json, "
        f"json_extract(result_json, '$.stats.n_trials'), {rl_reading.sql_columns()} FROM job "
        "WHERE config_json LIKE '%\"kind\":\"rl\"%' AND phase != 'deleted' ORDER BY created_at DESC, rowid DESC").fetchall()
    out = []
    for job_id, status, phase, created, started, finished, cfg_json, n_trials, *values in rows:
        cfg: dict = {}
        with contextlib.suppress(TypeError, ValueError):
            cfg = json.loads(cfg_json) or {}
        obj, rl = cfg.get("objective") or {}, cfg.get("rl") or {}
        done = status == "done"
        fields = dict(zip(rl_reading.FIELD_KEYS, values, strict=True))
        rd = rl_reading.derive(fields, obj.get("target_symbol"), done=done)
        sharpe, total, mdd, sh_bh, dsr = (fields[k] for k in ("sharpe", "total_return", "max_drawdown", "sharpe_buy_hold", "dsr"))
        out.append({"id": job_id, "kind": "rl", "family": "rl", "target": obj.get("target_symbol"), "horizon": (obj.get("horizons") or [1])[0],
                    "name": cfg.get("name"), "status": status, "phase": phase, "started_at": started or created, "finished_at": finished,
                    "scheme": "walkforward", "algo": rl.get("algo"), "n_features": rl.get("max_features"), "f1_test": None, "f1_holdout": None,
                    "auc_test": None, "panel_test": None, "panel_holdout": None, "dm_p": None, "suspect": None, "n_trials": n_trials if done else None,
                    "sharpe": sharpe if done else None, "sharpe_bh": sh_bh if done else None, "total_return": total if done else None,
                    "max_dd": mdd if done else None, "dsr": dsr if done else None, "url": f"/runs/{job_id}/analyse",
                    "verdict": rd["verdict"], "engine": rd["engine"], "excess": rd["excess"]})
    return out


def _ml_rows(conn: sqlite3.Connection) -> list[dict]:
    """Runs ML / DL : mêmes agrégats groupés que la page Historique, sans la répartition des classes (3 s de plus, inutile ici)."""
    from patrick.tracking import db as trackdb
    from patrick.validation import suspicion
    rows = conn.execute("SELECT run_id, target, horizon, status, started_at, finished_at, config_json, n_trials FROM run "
                        "WHERE is_archived = 0 ORDER BY started_at DESC").fetchall()
    ids = [r[0] for r in rows]
    f1 = trackdb.batch_best_f1_dir(conn, ids)
    dm = trackdb.batch_dm_results(conn, ids)
    bench = trackdb.batch_baseline_f1_dir(conn, ids)
    head = trackdb.batch_best_metrics(conn, ids)
    best = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT run_id, algo, n_features, sampler FROM trial WHERE is_best = 1")}
    out = []
    for run_id, target, horizon, status, started, finished, cfg_json, n_trials in rows:
        cfg: dict = {}
        with contextlib.suppress(TypeError, ValueError):
            cfg = json.loads(cfg_json) if cfg_json else {}
        algo, n_feat, sampler = best.get(run_id, (None, None, None))
        hm = head.get(run_id, {})
        test_m, hold_m = hm.get("test", {}), hm.get("holdout", {})
        family = trackdb.run_family(cfg)
        out.append({"id": run_id, "kind": family, "family": family, "target": target, "horizon": horizon, "name": cfg.get("name"),
                    "status": status, "phase": None, "started_at": started, "finished_at": finished,
                    "scheme": (cfg.get("validation") or {}).get("scheme", "walkforward"), "algo": algo, "sampler": sampler,
                    "n_features": n_feat, "f1_test": f1.get(run_id), "f1_holdout": hold_m.get("F1_dir"), "auc_test": test_m.get("AUC_ovr_4cls"),
                    "auc_holdout": hold_m.get("AUC_ovr_4cls"), "panel_test": metric_panel.panel(test_m), "panel_holdout": metric_panel.panel(hold_m),
                    "dm_p": (dm.get(run_id) or {}).get("p_value"),
                    "dm_sample": (dm.get(run_id) or {}).get("sample"), "suspect": bool(suspicion.suspect_reason(hold_m) or suspicion.suspect_reason(test_m)),
                    "n_trials": n_trials, "benchmark_f1": bench.get(run_id), "alpha": ALPHA_SEP in (target or ""),
                    "url": f"/runs/{run_id}/analyse"})
    return out


def training_index(conn: sqlite3.Connection) -> dict:
    """Tous les entraînements, du plus récent au plus ancien, avec leurs chiffres de tête et le lien vers leur analyse."""
    rows = _ml_rows(conn) + _rl_rows(conn)
    rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"rows": rows, "counts": counts, "n": len(rows)}


def maps(conn: sqlite3.Connection, index: dict | None = None) -> dict:
    """Carte cible × horizon (dernier run terminé de chaque couple), distribution par algorithme, nuage RL (Sharpe agent contre
    acheter-garder)."""
    rows = (index or training_index(conn))["rows"]
    done = [r for r in rows if r["status"] == "done" and r["kind"] in ("ml", "dl")]
    cells: dict[tuple, dict] = {}
    for r in done:                                        # rows triées du plus récent au plus ancien : le premier de chaque couple gagne
        key = (r["target"], r["horizon"])
        if key not in cells:
            cells[key] = {"target": r["target"], "horizon": r["horizon"], "run_id": r["id"], "panel_test": r["panel_test"],
                          "panel_holdout": r["panel_holdout"], "algo": r["algo"], "suspect": r["suspect"]}
    horizons = sorted({c["horizon"] for c in cells.values()})
    targets = sorted({c["target"] for c in cells.values()})
    by_algo: dict[str, dict[str, dict[str, list[float]]]] = {}
    for r in done:
        a = r["algo"] or "?"
        d = by_algo.setdefault(a, {key: {"test": [], "holdout": []} for key in metric_panel.PANEL_KEYS})
        for key in metric_panel.PANEL_KEYS:
            for split in ("test", "holdout"):
                v = (r[f"panel_{split}"] or {}).get(key)
                if v is not None:
                    d[key][split].append(v)

    def box(v: list[float]) -> dict | None:
        if not v:
            return None
        a = np.asarray(v, dtype=float)
        return {"n": len(a), "min": float(a.min()), "q1": float(np.percentile(a, 25)), "median": float(np.median(a)),
                "q3": float(np.percentile(a, 75)), "max": float(a.max()), "mean": float(a.mean())}

    algos = [{"algo": a, "metrics": {key: {"test": box(d[key]["test"]), "holdout": box(d[key]["holdout"])} for key in metric_panel.PANEL_KEYS}}
             for a, d in by_algo.items()]
    algos.sort(key=lambda x: -(x["metrics"]["AUC_dir"]["holdout"]["median"] if x["metrics"]["AUC_dir"]["holdout"] else -1))
    rl = [{"id": r["id"], "target": r["target"], "algo": r["algo"], "sharpe": r["sharpe"], "sharpe_bh": r["sharpe_bh"], "dsr": r["dsr"],
           "verdict": r.get("verdict"), "engine": r.get("engine"), "excess": r.get("excess")}
          for r in rows if r["kind"] == "rl" and r["sharpe"] is not None]
    panel = [{"key": m.key, "higher": m.higher_is_better, "chance": m.chance, "percent": m.percent} for m in metric_panel.PANEL]
    return sc.jsonable({"cells": list(cells.values()), "horizons": horizons, "targets": targets, "algos": algos, "rl": rl, "panel": panel})
