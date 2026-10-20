"""Explorateur de variables inter-runs : quelles variables les sélecteurs retiennent-ils, pour quelles cibles, et avec quelle stabilité d'un pli
à l'autre ? Lecture seule de `feature_stability` (fréquence de sélection par run) et `run_feature_stability` (stabilité de Jaccard).

Limite assumée : l'importance SHAP globale, la dépendance partielle et les interactions exigent de reconstruire la matrice de variables du run
et de rejouer son modèle (minutes de calcul) : elles ne sont pas calculées à l'ouverture d'une page. Ce qui est lu ici est exactement ce que
chaque run a enregistré."""
from __future__ import annotations

import re
import sqlite3

import numpy as np

from patrick.analysis import stats_core as sc
from patrick.analysis.sec_meta import feature_family

_CUT = re.compile(r"(_ret_\d|_zscore_\d|_vs_ma\d|_ma\d|_vol_\d|_rv_\d|_lag\d|_rsi|_hurst|_semivar|_heston|_egarch|_kalman|_garch|_macd|_atr|_skew|_kurt|_roc|_stoch|_bb_|_acf|_entropy|__)")
TOP_FEATURES = 400


def base_series(name: str) -> str:
    """Série d'entrée d'une variable : le nom avant la première transformation reconnue (`IDX_GSPC_zscore_10d` → `IDX_GSPC`)."""
    m = _CUT.search(name)
    return name[:m.start()] if m and m.start() > 0 else name


def _done_runs(conn: sqlite3.Connection) -> dict[str, tuple]:
    return {rid: (target, horizon) for rid, target, horizon in conn.execute(
        "SELECT run_id, target, horizon FROM run WHERE status = 'done' AND is_archived = 0")}


def overview(conn: sqlite3.Connection) -> dict:
    runs = _done_runs(conn)
    jacc = {rid: j for rid, j in conn.execute("SELECT run_id, mean_jaccard FROM run_feature_stability WHERE mean_jaccard IS NOT NULL")}
    feats: dict[str, dict] = {}
    by_target_family: dict[str, dict[str, float]] = {}
    series: dict[str, dict] = {}
    runs_with = set()
    for rid, feat, freq in conn.execute("SELECT run_id, feature, selection_freq FROM feature_stability"):
        if rid not in runs:
            continue
        runs_with.add(rid)
        target = runs[rid][0]
        d = feats.setdefault(feat, {"feature": feat, "runs": 0, "freq_sum": 0.0, "full": 0, "targets": set()})
        d["runs"] += 1
        d["freq_sum"] += freq
        d["full"] += int(freq >= 0.999)
        d["targets"].add(target)
        fam = feature_family(feat)
        tf = by_target_family.setdefault(target, {})
        tf[fam] = tf.get(fam, 0.0) + freq
        s = series.setdefault(base_series(feat), {"series": base_series(feat), "runs": set(), "weight": 0.0, "features": set()})
        s["runs"].add(rid)
        s["weight"] += freq
        s["features"].add(feat)
    items = []
    for d in feats.values():
        items.append({"feature": d["feature"], "family": feature_family(d["feature"]), "series": base_series(d["feature"]), "runs": d["runs"],
                      "targets": len(d["targets"]), "mean_freq": d["freq_sum"] / d["runs"], "always": d["full"]})
    items.sort(key=lambda r: (-r["runs"], -r["mean_freq"]))
    fam_w: dict[str, float] = {}
    for it in items:
        fam_w[it["family"]] = fam_w.get(it["family"], 0.0) + it["runs"] * it["mean_freq"]
    tot = sum(fam_w.values()) or 1.0
    top_series = sorted(({"series": s["series"], "runs": len(s["runs"]), "features": len(s["features"]), "weight": s["weight"]} for s in series.values()),
                        key=lambda r: -r["weight"])[:40]
    targets = sorted(by_target_family, key=lambda t: -sum(by_target_family[t].values()))[:30]
    fams = sorted(fam_w, key=lambda f: -fam_w[f])
    matrix = []
    for t in targets:
        row_tot = sum(by_target_family[t].values()) or 1.0
        matrix.append({"target": t, "shares": {f: by_target_family[t].get(f, 0.0) / row_tot for f in fams}, "n": round(row_tot)})
    vals = np.array(list(jacc.values())) if jacc else np.array([])
    return sc.jsonable({
        "n_features": len(items), "n_runs": len(runs_with), "n_runs_total": len(runs),
        "jaccard": {"n": len(vals), "mean": float(vals.mean()) if len(vals) else None, "median": float(np.median(vals)) if len(vals) else None,
                    "share_low": float((vals < 0.5).mean()) if len(vals) else None},
        "features": items[:TOP_FEATURES], "families": [{"family": f, "share": fam_w[f] / tot} for f in fams], "series": top_series,
        "matrix": {"families": fams, "rows": matrix}})


def feature_detail(conn: sqlite3.Connection, feature: str, limit: int = 120) -> dict:
    runs = _done_runs(conn)
    rows = conn.execute("SELECT run_id, selection_freq FROM feature_stability WHERE feature = ? ORDER BY selection_freq DESC", (feature,)).fetchall()
    ids = [r[0] for r in rows if r[0] in runs][:limit]
    meta = {}
    if ids:
        ph = ",".join("?" for _ in ids)
        for rid, algo, n, f1 in conn.execute(
                f"SELECT t.run_id, t.algo, t.n_features, (SELECT AVG(value) FROM fold_metric WHERE trial_id = t.trial_id AND split IN ('test','test_path') "
                f"AND metric = 'F1_dir') FROM trial t WHERE t.is_best = 1 AND t.run_id IN ({ph})", ids):
            meta[rid] = (algo, n, f1)
    items = [{"run_id": rid, "target": runs[rid][0], "horizon": runs[rid][1], "freq": freq, "algo": (meta.get(rid) or (None,))[0],
              "n_features": (meta.get(rid) or (None, None))[1], "f1": (meta.get(rid) or (None, None, None))[2]} for rid, freq in rows if rid in runs][:limit]
    return sc.jsonable({"feature": feature, "family": feature_family(feature), "series": base_series(feature), "runs": items,
                        "n_runs": sum(1 for r in rows if r[0] in runs), "targets": sorted({i["target"] for i in items})})
