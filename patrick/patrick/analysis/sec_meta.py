"""Sections « structure » d'un run : identité, protocole de validation, plis, essais, variables, holdout et live, chemins CPCV."""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3

import numpy as np
import pandas as pd

from patrick.analysis import frames
from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx, iso
from patrick.analysis.sec_predict import _scores


# ----------------------------------------------------------------------------------------------------------- aperçu
def _run_name(config: dict, run: dict) -> str:
    n = config.get("name")
    return n if isinstance(n, str) and n else run["run_id"]


def overview(ctx: Ctx) -> dict:
    """Identité du run, de l'essai retenu, effectifs par échantillon, chiffres de tête (test, holdout, live) et runs voisins."""
    from patrick.tracking import stats as trackstats
    fr, conn = ctx.fr, ctx.conn
    run, trial, cfg = fr.run, fr.trial, fr.config
    d = fr.df
    heads = {}
    for name in ("test", "holdout"):
        g = d[(d["split_name"] == name) & d["ut"].notna()]
        g = ctx.one_path(g)
        if len(g):
            heads[name] = _scores(g)
    live = d[(d["split_name"] == "live") & d["ut"].notna()]
    if len(live):
        heads["live"] = _scores(live)
    params = {}
    with contextlib.suppress(TypeError, ValueError):
        params = json.loads(trial.get("params_json") or "{}")
    val = cfg.get("validation") or {}
    siblings = []
    for r in conn.execute(
            "SELECT run_id, started_at, status, config_json FROM run WHERE target = ? AND horizon = ? AND run_id != ? "
            "ORDER BY started_at DESC LIMIT 12", (run["target"], run["horizon"], run["run_id"])):
        name = None
        with contextlib.suppress(TypeError, ValueError):
            name = (json.loads(r[3]) or {}).get("name")
        siblings.append({"run_id": r[0], "started_at": r[1], "status": r[2], "name": name or r[0]})
    reads = trackstats.holdout_reads(conn, run["target"], fr.horizon)
    return {"run": {**{k: run[k] for k in ("run_id", "target", "horizon", "status", "started_at", "finished_at", "snapshot_id",
                                           "config_hash", "git_sha", "seed", "n_trials")}, "name": _run_name(cfg, run)},
            "trial": {"trial_id": trial["trial_id"], "algo": trial["algo"], "sampler": trial["sampler"], "n_features": trial["n_features"],
                      "selector": trial["selector"], "regime": trial["regime"], "category": trial.get("category"), "params": params,
                      "is_best": trial.get("is_best")},
            "scheme": val.get("scheme", "walkforward"), "splits": frames.quick_split_counts(d), "headline": heads,
            "has_levels": fr.levels is not None, "is_alpha": fr.is_alpha, "notes": fr.notes,
            "cumulative_trials": trackstats.count_cumulative_trials(conn, run["target"], fr.horizon),
            "holdout_reads": reads, "siblings": siblings,
            "levels_range": [iso(fr.levels.index[0]), iso(fr.levels.index[-1])] if fr.levels is not None else None}


# ------------------------------------------------------------------------------------------------------- protocole
def _fold_sizes(conn: sqlite3.Connection, trial_id: int) -> dict[tuple[str, int], dict[str, float]]:
    out: dict[tuple[str, int], dict[str, float]] = {}
    for split, fold, metric, value in conn.execute(
            "SELECT split, fold_index, metric, value FROM fold_metric WHERE trial_id = ? "
            "AND metric IN ('n_train', 'effective_n_train', 'n_test')", (trial_id,)):
        out.setdefault((split, int(fold)), {})[metric] = value
    return out


def protocol(ctx: Ctx) -> dict:
    """Le découpage temporel réellement utilisé : fenêtres d'entraînement (extension à partir du début), purge, test de chaque pli,
    holdout final. Les dates de test viennent des prédictions stockées ; le début et la fin de l'entraînement sont estimés."""
    fr, conn = ctx.fr, ctx.conn
    val = (fr.config.get("validation") or {})
    sizes = _fold_sizes(conn, fr.trial["trial_id"])
    h = fr.horizon
    purge_bars = h if val.get("purge", True) else 0
    embargo = val.get("embargo_bars") if val.get("embargo_enabled", True) else 0
    data_start = iso(fr.levels.index[0]) if fr.levels is not None else None
    folds = []
    d = ctx.one_path(fr.df[fr.df["split_name"].isin(["test", "holdout"])])
    for (split, fold), g in d.groupby(["split_name", "fold"]):
        start = g["ts"].min()
        train_end = None
        if fr.levels is not None:
            pos = fr.levels.index.searchsorted(start)
            k = pos - 1 - purge_bars - (embargo or 0)
            if k >= 0:
                train_end = iso(fr.levels.index[k])
        sz = sizes.get((split, int(fold)), {})
        folds.append({"fold": int(fold), "split": split, "test_start": iso(start), "test_end": iso(g["ts"].max()), "n_pred": len(g),
                      "n_train": sz.get("n_train"), "effective_n_train": sz.get("effective_n_train"), "n_test": sz.get("n_test"),
                      "train_start": data_start, "train_end": train_end})
    folds.sort(key=lambda f: f["test_start"])
    cpcv = None
    if fr.is_cpcv:
        from patrick.validation.cpcv import n_paths
        ng, kt = val.get("n_groups"), val.get("k_test_groups")
        cpcv = {"n_groups": ng, "k_test_groups": kt, "n_paths": n_paths(ng, kt) if ng and kt else None}
    allts = [f["test_start"] for f in folds] + [f["test_end"] for f in folds]
    return {"available": bool(folds), "scheme": val.get("scheme", "walkforward"), "folds": folds, "cpcv": cpcv,
            "config": {"n_wf_folds": val.get("n_wf_folds"), "min_train_frac": val.get("min_train_frac"), "purge": val.get("purge"),
                       "embargo_enabled": val.get("embargo_enabled"), "embargo_bars": val.get("embargo_bars"),
                       "holdout_months": val.get("holdout_months"), "min_train_rows": val.get("min_train_rows"),
                       "min_test_rows": val.get("min_test_rows"), "horizon": h, "purge_bars": purge_bars},
            "range": [data_start or (min(allts) if allts else None), max(allts) if allts else None]}


# ----------------------------------------------------------------------------------------------------------------- plis
def folds(ctx: Ctx) -> dict:
    """Toutes les métriques stockées pli par pli (test, holdout, validation interne) et les baselines du run."""
    from patrick.tracking import history
    conn, fr = ctx.conn, ctx.fr
    blocks = history.fold_metrics(conn, fr.trial["trial_id"])
    base_rows = conn.execute("SELECT baseline, split, metric, value FROM baseline_metric WHERE run_id = ? ORDER BY baseline, split, metric",
                             (fr.run["run_id"],)).fetchall()
    baselines: dict[str, dict] = {}
    for b, split, metric, value in base_rows:
        baselines.setdefault(b, {}).setdefault(split, {})[metric] = value
    dm = [dict(zip(("baseline", "kind", "dm_stat", "p_value", "sample", "n_obs"), r, strict=True)) for r in conn.execute(
        "SELECT baseline, kind, dm_stat, p_value, sample, n_obs FROM dm_result WHERE run_id = ?", (fr.run["run_id"],))]
    return {"available": bool(blocks), "blocks": blocks, "baselines": baselines, "dm": dm,
            "metric_order": list(history.METRIC_ORDER)}


# ---------------------------------------------------------------------------------------------------------------- essais
def trials(ctx: Ctx) -> dict:
    """Tous les essais du run (candidats du criblage et affinés), leurs scores test / holdout, décisions de criblage, dépenses
    d'exploration enregistrées pour cette cible et cet horizon."""
    from patrick.tracking import db as trackdb
    conn, fr = ctx.conn, ctx.fr
    run_id = fr.run["run_id"]
    rows = conn.execute(
        "SELECT t.trial_id, t.regime, t.algo, t.sampler, t.n_features, t.selector, t.is_best, t.category, "
        "(SELECT AVG(value) FROM fold_metric WHERE trial_id = t.trial_id AND split IN ('test','test_path') AND metric = 'F1_dir'), "
        "(SELECT AVG(value) FROM fold_metric WHERE trial_id = t.trial_id AND split IN ('test','test_path') AND metric = 'Acc_dir'), "
        "(SELECT AVG(value) FROM fold_metric WHERE trial_id = t.trial_id AND split = 'holdout' AND metric = 'F1_dir'), "
        "(SELECT AVG(value) FROM fold_metric WHERE trial_id = t.trial_id AND split IN ('test','test_path') AND metric = 'AUC_ovr_4cls') "
        "FROM trial t WHERE t.run_id = ? ORDER BY t.is_best DESC, t.trial_id", (run_id,)).fetchall()
    keys = ("trial_id", "regime", "algo", "sampler", "n_features", "selector", "is_best", "category", "f1_dir", "acc_dir", "holdout_f1",
            "auc")
    items = [dict(zip(keys, r, strict=True)) for r in rows]
    for it in items:
        it["is_best"] = bool(it["is_best"])
    reg = conn.execute("SELECT source, SUM(n_trials) FROM trial_registry WHERE target = ? AND horizon = ? GROUP BY source",
                       (fr.run["target"], fr.horizon)).fetchall()
    return {"available": bool(items), "trials": items, "screening": trackdb.list_screening_decisions(conn, run_id),
            "registry": [{"source": s, "n": int(n or 0)} for s, n in reg],
            "n_in_run": len(items), "best_id": fr.trial["trial_id"]}


# -------------------------------------------------------------------------------------------------------------- variables
_FAMILIES = (
    ("interaction", re.compile(r"__(prod|minus|plus|ratio|div)__")),
    ("volatility_model", re.compile(r"(heston|egarch|garch|semivar|kalman|vrp)")),
    ("momentum", re.compile(r"_ret_\d+d$")),
    ("zscore", re.compile(r"_zscore_\d+d$")),
    ("trend", re.compile(r"(_vs_ma\d+|_ma\d+|_macd)")),
    ("oscillator", re.compile(r"_(rsi|stoch|bb|roc)_?\d*d?$")),
    ("volatility", re.compile(r"_(vol|rv|atr)_\d+d$")),
    ("memory", re.compile(r"(hurst|autocorr|acf|entropy)")),
    ("lag", re.compile(r"_lag\d+$")),
)


def feature_family(name: str) -> str:
    for fam, rx in _FAMILIES:
        if rx.search(name):
            return fam
    return "level_other"


def _native_importance(trial: dict) -> dict | None:
    """Importance native du modèle exporté (arbres : `feature_importances_`, linéaires : |coef|) ; `None` si le fichier manque ou
    n'expose rien. Chargement en lecture seule du joblib de l'essai gagnant, noms lus dans le même paquet."""
    path = trial.get("artifact_path")
    if not path or not os.path.exists(path) or os.path.getsize(path) > 400 * 1024 * 1024:
        return None
    try:
        import warnings

        import joblib
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                       # modèle enregistré avec une autre version de scikit-learn
            bundle = joblib.load(path)
        model, names = bundle.get("model"), list(bundle.get("feature_names") or [])
    except Exception:  # noqa: BLE001 -- fichier d'un autre environnement (bibliothèque absente, version) : section simplement vide
        return None
    imp = getattr(model, "feature_importances_", None)
    if imp is None and hasattr(model, "coef_"):
        imp = np.mean(np.abs(np.atleast_2d(model.coef_)), axis=0)
    if imp is None and hasattr(model, "get_feature_importance"):
        with contextlib.suppress(Exception):
            imp = model.get_feature_importance()
    if imp is None or len(imp) != len(names) or not names:
        return None
    imp = np.asarray(imp, dtype=float)
    total = float(imp.sum()) or 1.0
    return {"names": names, "values": imp / total, "kind": type(model).__name__}


def features(ctx: Ctx) -> dict:
    """Variables du modèle : importance native du modèle exporté, fréquence de sélection pli par pli (stabilité), familles."""
    from patrick.tracking import db as trackdb
    conn, fr = ctx.conn, ctx.fr
    rows = conn.execute("SELECT feature, selection_freq FROM feature_stability WHERE run_id = ? ORDER BY selection_freq DESC, feature",
                        (fr.run["run_id"],)).fetchall()
    stab = trackdb.get_feature_stability(conn, fr.run["run_id"])
    freq = [{"feature": f, "freq": float(v), "family": feature_family(f)} for f, v in rows]
    native = _native_importance(fr.trial)
    imp = None
    if native:
        order = np.argsort(-native["values"])[:40]
        imp = [{"feature": native["names"][i], "value": float(native["values"][i]), "family": feature_family(native["names"][i])}
               for i in order]
    fam: dict[str, float] = {}
    if native:
        for n, v in zip(native["names"], native["values"], strict=True):
            fam[feature_family(n)] = fam.get(feature_family(n), 0.0) + float(v)
    elif freq:
        tot = sum(r["freq"] for r in freq) or 1.0
        for r in freq:
            fam[r["family"]] = fam.get(r["family"], 0.0) + r["freq"] / tot
    return {"available": bool(freq or imp), "selection": freq[:60], "n_selection": len(freq), "importance": imp,
            "importance_kind": native["kind"] if native else None,
            "families": sorted(({"family": k, "share": v} for k, v in fam.items()), key=lambda r: -r["share"]),
            "stability": stab, "n_features": fr.trial["n_features"]}


# ---------------------------------------------------------------------------------------------------- holdout et live
def holdout_live(ctx: Ctx) -> dict:
    """Écart entre le test walk-forward et le holdout, lectures enregistrées du holdout, et suivi des prédictions live."""
    from patrick.tracking import stats as trackstats
    conn, fr = ctx.conn, ctx.fr
    d = fr.df
    cmp = {}
    for name in ("test", "holdout"):
        g = ctx.one_path(d[(d["split_name"] == name) & d["ut"].notna()])
        if len(g):
            cmp[name] = _scores(g)
    reads = trackstats.holdout_reads(conn, fr.run["target"], fr.horizon)
    acc_rows = conn.execute(
        "SELECT accessed_at, purpose, run_id, holdout_start, holdout_end, n_rows FROM holdout_access WHERE target = ? AND horizon = ? "
        "ORDER BY accessed_at DESC LIMIT 25", (fr.run["target"], fr.horizon)).fetchall()
    access = [dict(zip(("accessed_at", "purpose", "run_id", "holdout_start", "holdout_end", "n_rows"), r, strict=True)) for r in acc_rows]
    live = d[d["split_name"] == "live"].sort_values("ts")
    items = []
    for r in live.tail(60).itertuples(index=False):
        resolved = not pd.isna(r.ut)
        items.append({"t": iso(r.ts), "yp": int(r.yp), "p": None if pd.isna(r.p_up) else round(float(r.p_up), 4),
                      "ut": None if not resolved else int(r.ut), "ok": (bool((r.ut >= 0.5) == bool(r.up)) if resolved else None),
                      "calibrated": None if pd.isna(r.p_cal) else bool(r.p_cal)})
    res = live[live["ut"].notna()]
    k = int(((res["ut"] >= 0.5) == res["up"]).sum()) if len(res) else 0
    lo, hi = sc.wilson(k, len(res))
    drop = None
    if "test" in cmp and "holdout" in cmp and cmp["test"]["acc"] is not None and cmp["holdout"]["acc"] is not None:
        drop = cmp["holdout"]["acc"] - cmp["test"]["acc"]
    return {"available": bool(cmp or items), "compare": cmp, "acc_drop": drop, "reads": reads, "access": access,
            "live": {"items": items, "n": len(live), "resolved": len(res), "hits": k,
                     "hit_rate": (k / len(res)) if len(res) else None, "lo": lo, "hi": hi}}


# ------------------------------------------------------------------------------------------------------- chemins CPCV
def paths(ctx: Ctx) -> dict:
    """CPCV : distribution des métriques sur les chemins de backtest (un chemin = une reconstruction complète de l'historique)."""
    fr, conn = ctx.fr, ctx.conn
    if not fr.is_cpcv:
        return {"available": False, "reason": "not_cpcv"}
    by: dict[int, dict[str, float]] = {}
    for fold, metric, value in conn.execute(
            "SELECT fold_index, metric, value FROM fold_metric WHERE trial_id = ? AND split = 'test_path'", (fr.trial["trial_id"],)):
        by.setdefault(int(fold), {})[metric] = value
    if not by:
        return {"available": False, "reason": "no_paths"}
    metrics = sorted({m for v in by.values() for m in v})
    summary = {}
    for m in metrics:
        vals = np.array([v[m] for v in by.values() if m in v], dtype=float)
        if len(vals):
            summary[m] = {"mean": float(vals.mean()), "std": float(vals.std(ddof=1)) if len(vals) > 1 else None,
                          "q05": float(np.percentile(vals, 5)), "median": float(np.median(vals)), "q95": float(np.percentile(vals, 95)),
                          "min": float(vals.min()), "max": float(vals.max()), "n": len(vals)}
    return {"available": True, "paths": [{"path": p, **v} for p, v in sorted(by.items())], "summary": summary, "metrics": metrics}


# ------------------------------------------------------------------------------------------------------------ carnet
def notes(ctx: Ctx) -> dict:
    """Notes du carnet de recherche liées à ce run, et celles de la même cible et du même horizon (sans doublon)."""
    from patrick.tracking import research_notes
    fr = ctx.fr
    mine = research_notes.list_notes(ctx.conn, run_id=fr.run["run_id"], include_archived=True)
    ids = {n["note_id"] for n in mine}
    related = [n for n in research_notes.list_notes(ctx.conn, target=fr.run["target"], horizon=fr.horizon) if n["note_id"] not in ids]
    return {"available": True, "run_id": fr.run["run_id"], "target": fr.run["target"], "horizon": fr.horizon, "notes": mine, "related": related[:50]}
