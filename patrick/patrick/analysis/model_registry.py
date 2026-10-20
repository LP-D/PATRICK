"""Registre de modèles : un modèle « en titre » par couple cible × horizon, ses versions (les runs terminés qui ont un modèle exporté), son
historique de duels (archive), sa fiche automatique (données, configuration, métriques, suivi live, dérive, limites connues) et la promotion
manuelle d'une version (retour arrière compris).

Une version est un run terminé dont l'essai gagnant a un fichier de modèle exporté sur ce poste. Un modèle remplacé ou rejeté par un duel de
champions a vu ses lignes lourdes élaguées (`tracking/champions.py::prune_run`) : il reste dans l'archive à titre descriptif, il ne peut plus être
promu. La promotion manuelle ne ré-entraîne rien : elle désigne un modèle déjà exporté comme celui que l'application utilise."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime

from patrick.analysis import stats_core as sc
from patrick.tracking import champions

STALE_MODEL_DAYS = 90
MIN_LIVE_JUDGED = 30


def _versions(conn: sqlite3.Connection) -> dict[tuple[str, int], list[dict]]:
    """Toutes les versions (runs terminés avec modèle exporté), la plus récente d'abord, par couple."""
    rows = conn.execute(
        "SELECT r.target, r.horizon, r.run_id, r.started_at, r.finished_at, t.trial_id, t.algo, t.sampler, t.n_features, t.artifact_path "
        "FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 AND t.artifact_path IS NOT NULL "
        "WHERE r.status = 'done' AND r.is_archived = 0 ORDER BY r.started_at DESC, t.trial_id DESC").fetchall()
    keys = ("target", "horizon", "run_id", "started_at", "finished_at", "trial_id", "algo", "sampler", "n_features", "artifact_path")
    out: dict[tuple[str, int], list[dict]] = {}
    for r in rows:
        d = dict(zip(keys, r, strict=True))
        d["artifact_exists"] = bool(d["artifact_path"]) and os.path.exists(d["artifact_path"])
        out.setdefault((d["target"], int(d["horizon"])), []).append(d)
    return out


def _metrics(conn: sqlite3.Connection, trial_ids: list[int]) -> dict[int, dict]:
    if not trial_ids:
        return {}
    ph = ",".join("?" for _ in trial_ids)
    out: dict[int, dict] = {}
    for tid, split, metric, v in conn.execute(
            f"SELECT trial_id, split, metric, AVG(value) FROM fold_metric WHERE trial_id IN ({ph}) AND split IN ('test','test_path','holdout') "
            f"AND metric IN ('F1_dir','Acc_dir','AUC_ovr_4cls') GROUP BY trial_id, split, metric", trial_ids):
        out.setdefault(tid, {})[("holdout" if split == "holdout" else "test") + "_" + metric] = v
    return out


def _live(conn: sqlite3.Connection, trial_ids: list[int]) -> dict[int, dict]:
    if not trial_ids:
        return {}
    ph = ",".join("?" for _ in trial_ids)
    return {tid: {"n": int(n), "judged": int(j or 0), "hits": int(hits or 0)} for tid, n, j, hits in conn.execute(
        f"SELECT trial_id, COUNT(*), SUM(y_true IS NOT NULL), SUM(CASE WHEN y_true IS NOT NULL AND ((y_pred >= 2) = (y_true >= 0.5)) THEN 1 ELSE 0 END) "
        f"FROM prediction INDEXED BY sqlite_autoindex_prediction_1 WHERE trial_id IN ({ph}) AND split = 'live' GROUP BY trial_id", trial_ids)}


def overview(conn: sqlite3.Connection) -> dict:
    """Un modèle par couple : le champion explicite, sinon le dernier run (champion implicite, comme `champions.current`)."""
    from patrick.tracking import history
    versions = _versions(conn)
    explicit = {(c["target"], int(c["horizon"])): c for c in champions.list_champions(conn)}
    chosen: dict[tuple[str, int], dict] = {}
    for key, vs in versions.items():
        c = explicit.get(key)
        pick = next((v for v in vs if c and v["run_id"] == c["run_id"]), None) if c else None
        chosen[key] = {**(pick or vs[0]), "implicit": pick is None, "reason": c["reason"] if pick and c else "implicit_latest",
                       "promoted_at": c["promoted_at"] if pick and c else None}
    tids = [v["trial_id"] for v in chosen.values()]
    met, live = _metrics(conn, tids), _live(conn, tids)
    targets = sorted({k[0] for k in chosen})
    horizons = sorted({k[1] for k in chosen})
    badges = history.drift_badges(conn, targets, horizons) if chosen else {}
    today = datetime.now(UTC)
    items = []
    for key, v in sorted(chosen.items()):
        m, lv = met.get(v["trial_id"], {}), live.get(v["trial_id"], {"n": 0, "judged": 0, "hits": 0})
        age = None
        if v.get("finished_at") or v.get("started_at"):
            try:
                age = (today - datetime.fromisoformat((v.get("finished_at") or v["started_at"]).replace(" ", "T")).replace(tzinfo=UTC)).days
            except ValueError:
                age = None
        items.append({"target": key[0], "horizon": key[1], "run_id": v["run_id"], "algo": v["algo"], "sampler": v["sampler"], "n_features": v["n_features"],
                      "implicit": v["implicit"], "reason": v["reason"], "promoted_at": v["promoted_at"], "n_versions": len(versions[key]),
                      "f1_test": m.get("test_F1_dir"), "f1_holdout": m.get("holdout_F1_dir"), "acc_holdout": m.get("holdout_Acc_dir"),
                      "live_n": lv["n"], "live_judged": lv["judged"], "live_hit": (lv["hits"] / lv["judged"]) if lv["judged"] else None,
                      "drift": (badges.get(key) or {}).get("action"), "age_days": age, "artifact_exists": v["artifact_exists"], "finished_at": v.get("finished_at")})
    counts = {"pairs": len(items), "explicit": sum(1 for i in items if not i["implicit"]), "no_file": sum(1 for i in items if not i["artifact_exists"]),
              "stale": sum(1 for i in items if i["age_days"] is not None and i["age_days"] > STALE_MODEL_DAYS)}
    return sc.jsonable({"items": items, "counts": counts, "stale_days": STALE_MODEL_DAYS})


def limits(card_parts: dict) -> list[dict]:
    """Limites connues d'un modèle : constats de méthode tirés de sa fiche, du plus grave au plus bénin (jamais de conseil d'achat ou de vente)."""
    out: list[dict] = []
    g = card_parts
    for it in g.get("guide", []):
        if it["level"] == "warn" and it["key"] in ("acc_vs_majority", "one_sided", "holdout_drop", "auc", "calibration", "folds", "dsr", "too_good"):
            out.append({"level": "warn", "key": f"g_{it['key']}", "params": it["params"]})
    gr = g.get("guardrails") or {}
    if (gr.get("reads_recorded", 0) + gr.get("reads_inferred", 0)) > 1:
        out.append({"level": "warn", "key": "holdout_reads", "params": {"n": gr.get("reads_recorded", 0) + gr.get("reads_inferred", 0), "d": gr.get("duels", 0)}})
    if gr.get("verdict") == "within_noise":
        out.append({"level": "warn", "key": "within_noise", "params": {"n": gr.get("trials", 0), "p": gr.get("p_deflated")}})
    live = g.get("live") or {}
    if live.get("judged", 0) < MIN_LIVE_JUDGED:
        out.append({"level": "info", "key": "few_live", "params": {"n": live.get("judged", 0), "m": MIN_LIVE_JUDGED}})
    if g.get("drift") in ("retrain", "watch"):
        out.append({"level": "warn", "key": "drift_" + g["drift"], "params": {}})
    age = g.get("age_days")
    if age is not None and age > STALE_MODEL_DAYS:
        out.append({"level": "info", "key": "stale", "params": {"d": age}})
    stab = g.get("stability")
    if stab is not None and stab == stab and stab < 0.5:
        out.append({"level": "warn", "key": "unstable_selection", "params": {"j": stab}})
    if not g.get("artifact_exists", True):
        out.append({"level": "warn", "key": "no_file", "params": {}})
    out.sort(key=lambda i: 0 if i["level"] == "warn" else 1)
    return out


def model_card(conn: sqlite3.Connection, target: str, horizon: int, db_key: str = "") -> dict | None:
    """Fiche d'un couple : modèle en titre, données et configuration, métriques, suivi live, dérive, versions, historique de duels, limites connues."""
    from patrick.analysis import guardrails, sec_meta, sec_robust
    from patrick.analysis.context import Ctx
    from patrick.analysis.registry import get_frame
    from patrick.tracking import history
    ov = overview(conn)
    cur = next((i for i in ov["items"] if i["target"] == target and i["horizon"] == horizon), None)
    if cur is None:
        return None
    versions = _versions(conn).get((target, horizon), [])
    tids = [v["trial_id"] for v in versions]
    met, live = _metrics(conn, tids), _live(conn, tids)
    fr = get_frame(conn, cur["run_id"], None, db_key)
    ctx = Ctx(conn, fr, {}) if fr is not None else None
    overview_part = sec_meta.overview(ctx) if ctx else {}
    guide = (sec_robust.guide(ctx) or {}).get("items", []) if ctx else []
    gr_rows = guardrails.summary(conn)["rows"]
    gr = next((r for r in gr_rows if r["target"] == target and r["horizon"] == horizon), None)
    badge = history.drift_badges(conn, [target], [horizon]).get((target, horizon)) or {}
    stab = conn.execute("SELECT mean_jaccard FROM run_feature_stability WHERE run_id = ?", (cur["run_id"],)).fetchone()
    feats = [r[0] for r in conn.execute("SELECT feature FROM feature_stability WHERE run_id = ? ORDER BY selection_freq DESC, feature LIMIT 15", (cur["run_id"],))]
    run = conn.execute("SELECT snapshot_id, git_sha, config_hash, seed, started_at, finished_at FROM run WHERE run_id = ?", (cur["run_id"],)).fetchone()
    cfg = (fr.config if fr is not None else {}) or {}
    version_items = []
    for v in versions:
        m, lv = met.get(v["trial_id"], {}), live.get(v["trial_id"], {"judged": 0, "hits": 0})
        version_items.append({"run_id": v["run_id"], "started_at": v["started_at"], "algo": v["algo"], "sampler": v["sampler"], "n_features": v["n_features"],
                              "f1_test": m.get("test_F1_dir"), "f1_holdout": m.get("holdout_F1_dir"), "live_judged": lv["judged"],
                              "live_hit": (lv["hits"] / lv["judged"]) if lv["judged"] else None, "current": v["run_id"] == cur["run_id"],
                              "artifact_exists": v["artifact_exists"]})
    archive = []
    for a in champions.list_archive(conn, target, horizon):
        duel = None
        try:
            duel = json.loads(a["duel_json"]) if a["duel_json"] else None
        except ValueError:
            duel = None
        wf = {}
        try:
            wf = json.loads(a["wf_metrics_json"]) if a["wf_metrics_json"] else {}
        except ValueError:
            wf = {}
        archive.append({"archive_id": a["archive_id"], "run_id": a["run_id"], "role": a["role"], "decided_at": a["decided_at"], "algo": a["algo"],
                        "n_features": a["n_features"], "f1_dir": wf.get("F1_dir"), "duel": duel})
    parts = {"guide": guide, "guardrails": gr, "live": {"judged": cur["live_judged"]}, "drift": badge.get("action"), "age_days": cur["age_days"],
             "stability": stab[0] if stab else None, "artifact_exists": cur["artifact_exists"]}
    return sc.jsonable({
        "target": target, "horizon": horizon, "current": cur,
        "data": {"snapshot_id": run[0] if run else None, "git_sha": run[1] if run else None, "config_hash": run[2] if run else None, "seed": run[3] if run else None,
                 "trained_from": (overview_part.get("levels_range") or [None])[0], "trained_to": (overview_part.get("splits", {}).get("test") or {}).get("start"),
                 "scheme": (cfg.get("validation") or {}).get("scheme", "walkforward"), "horizon": horizon, "n_features": cur["n_features"],
                 "top_features": feats, "calibration": bool((cfg.get("models") or {}).get("calibration")) if cfg else None},
        "metrics": overview_part.get("headline", {}), "live": {"n": cur["live_n"], "judged": cur["live_judged"], "hit": cur["live_hit"]},
        "drift": {"action": badge.get("action"), "reason": badge.get("reason"), "psi": badge.get("psi"), "concept_drift": badge.get("concept_drift")},
        "guardrails": gr, "versions": version_items, "archive": archive, "limits": limits(parts), "guide": guide})


def promote_version(conn: sqlite3.Connection, target: str, horizon: int, run_id: str, reason: str = "manual") -> dict:
    """Désigne `run_id` comme modèle en titre. Refuse un run inconnu, non terminé, d'un autre couple, ou dont le modèle n'est plus sur ce poste.
    Inscrit la décision au journal de décision (`phase9_journal`) avec l'ancien titulaire."""
    from patrick.tracking import db as trackdb
    v = next((x for x in _versions(conn).get((target, horizon), []) if x["run_id"] == run_id), None)
    if v is None:
        raise ValueError("version_unknown")
    if not v["artifact_exists"]:
        raise ValueError("model_file_missing")
    before = champions.current(conn, target, horizon)
    metric = conn.execute("SELECT AVG(value) FROM fold_metric WHERE trial_id = ? AND split = 'holdout' AND metric = 'F1_dir'", (v["trial_id"],)).fetchone()
    champions.promote(conn, target, horizon, run_id, v["trial_id"], reason, metric[0] if metric else None)
    trackdb.save_phase9_journal_entry(conn, "champion_promote", "user", {"target": target, "horizon": horizon, "run_id": before["run_id"] if before else None},
                                      {"target": target, "horizon": horizon, "run_id": run_id}, reason)
    return {"target": target, "horizon": horizon, "run_id": run_id, "previous": before["run_id"] if before else None}
