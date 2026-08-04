"""Phase 7 (interface) -- requêtes LECTURE SEULE pour parcourir l'historique
des runs déjà persistés en base : aucun nouveau calcul de modèle, aucune
influence sur un run en cours. Sert `webapp/app.py` (`/runs`, `/runs/{id}`,
`/targets/{ticker}`, `/universe`) -- les mêmes briques de validité (PBO,
Diebold-Mariano, FDR, stabilité des features, diagnostic holdout) que
`tracking/report.py`/`tracking/stats.py`, jamais réimplémentées : recalculées
à la volée sur demande (pas de cache), donc toujours à jour avec le dernier
run de la cible concernée -- contrairement à `report.py`, qui ne peut afficher
holdout/DM/PBO que pour un run lancé depuis l'interface web (limite du
mécanisme `job.result_json`), ces requêtes marchent aussi pour un `patrick
run`/`patrick resume` en CLI : `dm_result` (migration 0009) et
`fold_metric[split='holdout']` sont écrits par `pipeline/engine.py`
indépendamment de tout `job_id`.
"""
from __future__ import annotations

import json
import sqlite3

from patrick.config import defaults as D
from patrick.selection import stability as stability_module
from patrick.tracking import db as trackdb
from patrick.tracking import holdout_diagnostic as trackholdout
from patrick.tracking import stats as trackstats
from patrick.validation.cpcv import n_paths as cpcv_n_paths
from patrick.validation.cpcv import path_performance_distribution


def _config_field(config_json: str | None, *path, default=None):
    if not config_json:
        return default
    try:
        node = json.loads(config_json)
    except (TypeError, ValueError):
        return default
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def _run_scheme(config_json: str | None) -> str:
    return _config_field(config_json, "validation", "scheme", default="walkforward")


def _run_name(config_json: str | None) -> str | None:
    return _config_field(config_json, "name")


def _best_trial_id(conn: sqlite3.Connection, run_id: str) -> int | None:
    row = conn.execute(
        "SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1 LIMIT 1", (run_id,)
    ).fetchone()
    return row[0] if row else None


def _avg_metric(conn: sqlite3.Connection, trial_id: int, splits: tuple[str, ...],
                 metric: str = "F1_dir") -> float | None:
    placeholders = ",".join("?" for _ in splits)
    row = conn.execute(
        f"SELECT AVG(value) FROM fold_metric WHERE trial_id = ? AND split IN ({placeholders}) "
        "AND metric = ?",
        (trial_id, *splits, metric),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _dm_result_for_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT baseline, dm_stat, p_value, computed_at FROM dm_result WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    return {"baseline": row[0], "dm_stat": row[1], "p_value": row[2], "computed_at": row[3]}


def list_runs(conn: sqlite3.Connection, *, target: str | None = None,
              status: str | None = None, scheme: str | None = None,
              limit: int = 200) -> list[dict]:
    """P7.1 -- explorateur `/runs` : une ligne par run, les plus récents
    d'abord. `scheme` filtre après lecture (pas une colonne `run`, seulement
    présent dans `config_json`) -- acceptable, l'historique d'un usage local
    mono-utilisateur reste de taille modeste."""
    clauses, params = [], []
    if target:
        clauses.append("run.target = ?")
        params.append(target)
    if status:
        clauses.append("run.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT run.run_id, run.target, run.horizon, run.status, run.started_at, "
        f"run.finished_at, run.n_trials, run.config_json, dm.p_value "
        f"FROM run LEFT JOIN dm_result dm ON dm.run_id = run.run_id "
        f"{where} ORDER BY run.started_at DESC, run.rowid DESC LIMIT ?",
        (*params, limit),
    ).fetchall()

    out = []
    for run_id, tgt, horizon, status_, started_at, finished_at, n_trials, config_json, dm_p in rows:
        run_scheme = _run_scheme(config_json)
        if scheme and run_scheme != scheme:
            continue
        best_id = _best_trial_id(conn, run_id)
        best_f1 = (_avg_metric(conn, best_id, ("test", "test_path")) if best_id is not None else None)
        out.append({
            "run_id": run_id, "target": tgt, "horizon": horizon, "status": status_,
            "started_at": started_at, "finished_at": finished_at, "n_trials": n_trials,
            "name": _run_name(config_json), "scheme": run_scheme,
            "best_f1_dir": best_f1, "dm_p_value": dm_p,
        })
    return out


def list_distinct_targets(conn: sqlite3.Connection) -> list[dict]:
    """Cibles ayant au moins un run en base, avec compteurs -- alimente le
    filtre de `/runs` et la table `/universe` (croisée avec
    `DEFAULT_TARGET_GROUPS`, cf. `universe_overview`)."""
    rows = conn.execute(
        "SELECT target, COUNT(*), SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), "
        "MAX(started_at) FROM run GROUP BY target ORDER BY MAX(started_at) DESC"
    ).fetchall()
    return [{"target": t, "n_runs": n, "n_done": n_done, "last_started_at": last}
            for t, n, n_done, last in rows]


def _trials_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, is_best "
        "FROM trial WHERE run_id = ? ORDER BY is_best DESC, trial_id", (run_id,),
    ).fetchall()
    trials = []
    for trial_id, regime, algo, sampler, n_features, selector, is_best in rows:
        trials.append({
            "trial_id": trial_id, "regime": regime, "algo": algo, "sampler": sampler,
            "n_features": n_features, "selector": selector, "is_best": bool(is_best),
            "test_f1_dir": _avg_metric(conn, trial_id, ("test", "test_path")),
            "holdout_f1_dir": _avg_metric(conn, trial_id, ("holdout",)),
        })
    return trials


def _baselines_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT baseline, metric, value FROM baseline_metric "
        "WHERE run_id = ? AND split = 'test' ORDER BY baseline, metric", (run_id,),
    ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for baseline, metric, value in rows:
        out.setdefault(baseline, {})[metric] = value
    return [{"baseline": b, "metrics": m} for b, m in out.items()]


def _path_distribution_for_trial(conn: sqlite3.Connection, trial_id: int) -> dict | None:
    rows = conn.execute(
        "SELECT value FROM fold_metric WHERE trial_id = ? AND split = 'test_path' AND metric = 'F1_dir'",
        (trial_id,),
    ).fetchall()
    if not rows:
        return None
    return path_performance_distribution({i: v for i, (v,) in enumerate(rows)})


def run_detail(conn: sqlite3.Connection, run_id: str, fdr_alpha: float = 0.10) -> dict | None:
    """P7.2 -- page détail `/runs/{id}` : mêmes briques que `report.py`
    (jamais recalculées différemment), mais renvoyées en structure Python pour
    un gabarit Jinja plutôt qu'en HTML déjà formaté."""
    run = trackdb.get_run(conn, run_id)
    if run is None:
        return None
    config = json.loads(run["config_json"]) if run.get("config_json") else {}
    val_cfg = config.get("validation", {})
    scheme = val_cfg.get("scheme", "walkforward")
    is_cpcv = scheme == "cpcv"

    trials = _trials_for_run(conn, run_id)
    best_trial = next((t for t in trials if t["is_best"]), None)
    path_distributions = ({t["trial_id"]: _path_distribution_for_trial(conn, t["trial_id"])
                            for t in trials} if is_cpcv else {})

    cpcv_info = None
    if is_cpcv:
        n_groups_cfg, k_test_cfg = val_cfg.get("n_groups"), val_cfg.get("k_test_groups")
        cpcv_info = {
            "n_groups": n_groups_cfg, "k_test_groups": k_test_cfg,
            "n_paths": cpcv_n_paths(n_groups_cfg, k_test_cfg) if n_groups_cfg and k_test_cfg else None,
        }

    regime = best_trial["regime"] if best_trial else (trials[0]["regime"] if trials else "GLOBAL")
    pbo = (trackstats.pbo_for_target_cpcv(conn, run["target"], run["horizon"], regime)
           if is_cpcv else trackstats.pbo_for_target(conn, run["target"], run["horizon"], regime))

    dm_result = None if is_cpcv else _dm_result_for_run(conn, run_id)
    holdout_metrics = None if is_cpcv else (best_trial["holdout_f1_dir"] if best_trial else None)
    holdout_diag = trackholdout.spearman_test_vs_holdout(conn, run_id, metric="F1_dir")

    fdr_result = trackstats.fdr_across_targets(conn, alpha=fdr_alpha)
    target_fdr = fdr_result["results"].get(run["target"])

    quality_issues = trackdb.list_data_quality_issues(conn, run["snapshot_id"])
    feature_stability = trackdb.get_feature_stability(conn, run_id)

    return {
        "run": run,
        "config": config,
        "scheme": scheme,
        "is_cpcv": is_cpcv,
        "cpcv_info": cpcv_info,
        "trials": trials,
        "best_trial": best_trial,
        "path_distributions": path_distributions,
        "baselines": _baselines_for_run(conn, run_id),
        "cumulative_trials": trackstats.count_cumulative_trials(conn, run["target"], run["horizon"]),
        "pbo": pbo,
        "pbo_label": "chemins CPCV" if is_cpcv else "blocs walk-forward",
        "dm_result": dm_result,
        "holdout_f1_dir": holdout_metrics,
        "holdout_diag": holdout_diag,
        "fdr_result": fdr_result,
        "target_fdr": target_fdr,
        "data_quality_enabled": config.get("data_quality", {}).get("enabled", True),
        "quality_issues": quality_issues,
        "stability_enabled": config.get("selection", {}).get("track_stability", True),
        "feature_stability": feature_stability,
        "min_mean_jaccard_warning": stability_module.MIN_MEAN_JACCARD_WARNING,
    }


def target_detail(conn: sqlite3.Connection, target: str, fdr_alpha: float = 0.10) -> dict | None:
    """P7.3 -- page `/targets/{ticker}` : vue agrégée de tout l'historique de
    runs pour UNE cible (tous horizons/schémas confondus)."""
    runs = conn.execute(
        "SELECT run_id, horizon, status, started_at, finished_at, config_json, n_trials "
        "FROM run WHERE target = ? ORDER BY started_at DESC, rowid DESC", (target,),
    ).fetchall()
    if not runs:
        return None

    run_rows = []
    horizons = set()
    for run_id, horizon, status_, started_at, finished_at, config_json, n_trials in runs:
        horizons.add(horizon)
        best_id = _best_trial_id(conn, run_id)
        best_f1 = (_avg_metric(conn, best_id, ("test", "test_path")) if best_id is not None else None)
        run_rows.append({
            "run_id": run_id, "horizon": horizon, "status": status_,
            "started_at": started_at, "finished_at": finished_at,
            "name": _run_name(config_json), "scheme": _run_scheme(config_json),
            "n_trials": n_trials,
            "best_f1_dir": best_f1, "dm_result": _dm_result_for_run(conn, run_id),
        })

    fdr_result = trackstats.fdr_across_targets(conn, alpha=fdr_alpha)
    target_fdr = fdr_result["results"].get(target)

    pbo_by_horizon = {}
    for horizon in sorted(horizons):
        pbo_by_horizon[horizon] = {
            "walkforward": trackstats.pbo_for_target(conn, target, horizon, "GLOBAL"),
            "cpcv": trackstats.pbo_for_target_cpcv(conn, target, horizon, "GLOBAL"),
        }

    return {
        "target": target,
        "runs": run_rows,
        "n_runs": len(run_rows),
        "cumulative_trials": trackstats.count_cumulative_trials(conn, target),
        "pbo_by_horizon": pbo_by_horizon,
        "fdr_result": fdr_result,
        "target_fdr": target_fdr,
    }


def station_verdict(conn: sqlite3.Connection, fdr_alpha: float = 0.10) -> dict:
    """Les deux seuls chiffres que le produit sait établir sur TOUT
    l'historique : ce qui tient, et ce que ça a coûté.

    « Ce qui tient » = cibles dont la meilleure p-value Diebold-Mariano survit
    à la correction Benjamini-Hochberg ENTRE cibles. C'est le critère de sortie
    du produit, et c'est aussi le seul chiffre honnête à cette échelle :
    essayer 550 cibles et ne garder que la significative est exactement le
    biais que `fdr_across_targets` mesure (section 4, METHODOLOGY.md).

    `survivors = None` quand aucune cible n'a de résultat DM. C'est l'état
    NOMINAL d'une base jeune, pas un cas limite : `0 / 0` se lirait comme un
    échec alors que la mesure n'est simplement pas encore calculable, et le
    produit refuse d'imprimer une mesure non interprétable. L'appelant doit
    distinguer les deux.

    Aucun calcul nouveau : `fdr_across_targets` est celui de `/targets/{t}`,
    les comptes sont des agrégats directs. Lecture seule."""
    fdr = trackstats.fdr_across_targets(conn, alpha=fdr_alpha)
    n_tested = fdr["n_tested"]
    trials = conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0]
    runs, targets = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT target) FROM run"
    ).fetchone()
    return {
        "survivors": fdr["n_bh_significant"] if n_tested else None,
        "n_tested": n_tested,
        "alpha": fdr["alpha"],
        "cumulative_trials": trials,
        "n_runs": runs,
        "n_targets": targets,
    }


def universe_overview(conn: sqlite3.Connection) -> list[dict]:
    """P7.5 -- `/universe` : croise l'univers configurable de cibles
    (`config/defaults.py::DEFAULT_TARGET_GROUPS`, déjà utilisé par le
    formulaire de lancement) avec l'historique réel de runs -- aucune donnée
    nouvelle, juste la jointure des deux."""
    history = {h["target"]: h for h in list_distinct_targets(conn)}
    groups = []
    for group_name, items in D.DEFAULT_TARGET_GROUPS.items():
        source = "fred" if group_name == D.FRED_TARGET_GROUP else "yfinance"
        symbols = []
        for symbol, label in items:
            h = history.get(symbol)
            symbols.append({
                "symbol": symbol, "label": label, "source": source,
                "n_runs": h["n_runs"] if h else 0,
                "n_done": h["n_done"] if h else 0,
                "last_started_at": h["last_started_at"] if h else None,
            })
        groups.append({"group": group_name, "symbols": symbols})
    return groups
