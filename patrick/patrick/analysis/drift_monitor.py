"""Moniteur de dérive par cible et horizon : état de chaque couple suivi (politique du 2026-09-26, `validation/drift_policy.py`) et détail d'un couple
(historique des PSI mesurés, courbe de Page-Hinkley sur les appels live indépendants, réussite glissante).

Distinct de l'audit anti-fuite (qui vérifie qu'un résultat d'entraînement ne triche pas) : ici on surveille un modèle DÉJÀ exporté, face aux données
et aux issues qui arrivent après lui. Deux signaux, jamais mélangés :
- dérive des données : part des variables dont le PSI (indice de stabilité de population, mesuré contre la distribution d'entraînement) dépasse 0,25 ;
- dérive de concept : test séquentiel de Page-Hinkley sur les appels live jugés, un appel indépendant tous les `horizon` séances (les rendements à h jours
  se chevauchent). Un PSI élevé seul ne justifie jamais un ré-entraînement : chaque ré-entraînement ajoute des essais au registre déflaté.

Lecture seule ; la mesure du PSI elle-même reste l'action explicite `POST /api/drift/{cible}/{horizon}`."""
from __future__ import annotations

import sqlite3

import numpy as np

from patrick.analysis import stats_core as sc
from patrick.validation import drift as drift_lib
from patrick.validation import drift_policy

ACTION_ORDER = {"retrain": 0, "watch": 1, "unmeasured": 2, "ok": 3}


def _pairs(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT DISTINCT run.target, run.horizon FROM prediction p "
        "JOIN trial ON trial.trial_id = p.trial_id AND trial.is_best = 1 JOIN run ON run.run_id = trial.run_id WHERE p.split = 'live' "
        "UNION SELECT DISTINCT symbol, horizon FROM drift_psi_history").fetchall()
    return sorted((r[0], int(r[1])) for r in rows if r[0] is not None and r[1] is not None)


def overview(conn: sqlite3.Connection) -> dict:
    from patrick.tracking import history
    pairs = _pairs(conn)
    targets = sorted({t for t, _ in pairs})
    horizons = sorted({h for _, h in pairs})
    badges = history.drift_badges(conn, targets, horizons) if pairs else {}
    items = []
    for t, h in pairs:
        b = badges.get((t, h)) or {}
        items.append({"target": t, "horizon": h, "action": b.get("action", "unmeasured"), "data_level": b.get("data_level"), "psi": b.get("psi"),
                      "worst_feature": b.get("worst_feature"), "share_significant": b.get("share_significant"), "n_features": b.get("n_features"),
                      "measured_at": b.get("measured_at"), "age_days": b.get("age_days"), "stale": b.get("stale"), "n_hits": b.get("n_hits", 0),
                      "n_independent": b.get("n_independent", 0), "concept_drift": b.get("concept_drift"), "concept_hit_rate": b.get("concept_hit_rate"),
                      "reason": b.get("reason")})
    items.sort(key=lambda r: (ACTION_ORDER.get(r["action"], 9), r["target"], r["horizon"]))
    counts: dict[str, int] = {}
    for r in items:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    return sc.jsonable({"items": items, "counts": counts, "n": len(items),
                        "thresholds": {"psi_warn": drift_lib.PSI_WARN_THRESHOLD, "psi_alert": drift_lib.PSI_ALERT_THRESHOLD,
                                       "watch_share": drift_policy.WATCH_SHARE, "drift_share": drift_policy.DRIFT_SHARE,
                                       "min_independent": drift_policy.MIN_INDEPENDENT_CALLS, "ph_delta": drift_lib.PAGE_HINKLEY_DELTA,
                                       "ph_lambda": drift_lib.PAGE_HINKLEY_LAMBDA, "stale_days": drift_policy.STALE_DAYS}})


def ph_curve(hits: list[int], delta: float, lam: float) -> dict:
    """Statistique de Page-Hinkley après chaque appel (même récurrence que `validation.drift.page_hinkley_test`), pour la tracer."""
    mean_err = cum = min_cum = 0.0
    values, detected = [], None
    for n, h in enumerate(hits, 1):
        err = 1 - h
        mean_err += (err - mean_err) / n
        cum += err - mean_err - delta
        min_cum = min(min_cum, cum)
        v = cum - min_cum
        values.append(v)
        if detected is None and v > lam:
            detected = n - 1
    return {"values": values, "detected_at": detected}


def pair_detail(conn: sqlite3.Connection, target: str, horizon: int) -> dict:
    psi_rows = conn.execute("SELECT computed_at, feature, psi FROM drift_psi_history WHERE symbol = ? AND horizon = ? ORDER BY computed_at",
                            (target, horizon)).fetchall()
    by_time: dict[str, list[tuple[str, float]]] = {}
    for at, feat, psi in psi_rows:
        by_time.setdefault(at, []).append((feat, float(psi)))
    history = []
    for at in sorted(by_time):
        v = np.array([p for _, p in by_time[at]])
        history.append({"at": at, "max": float(v.max()), "mean": float(v.mean()), "share": float((v > drift_policy.SIGNIFICANT_PSI).mean()), "n": len(v)})
    latest = sorted(by_time[max(by_time)], key=lambda x: -x[1]) if by_time else []
    live = conn.execute(
        "SELECT p.ts, p.y_pred, p.y_true, p.p_up FROM prediction p JOIN trial ON trial.trial_id = p.trial_id AND trial.is_best = 1 "
        "JOIN run ON run.run_id = trial.run_id WHERE p.split = 'live' AND p.y_true IS NOT NULL AND run.target = ? AND run.horizon = ? ORDER BY p.ts",
        (target, horizon)).fetchall()
    hits = [int((yp >= 2) == (float(yt) >= 0.5)) for _, yp, yt, _ in live]
    indep_idx = list(range(0, len(hits), max(1, horizon)))
    indep = [hits[i] for i in indep_idx]
    ph = ph_curve(indep, drift_lib.PAGE_HINKLEY_DELTA, drift_lib.PAGE_HINKLEY_LAMBDA)
    win = min(20, max(5, len(indep) // 3)) if indep else 0
    roll = sc.rolling_mean(np.array(indep, dtype=float), win) if win and len(indep) >= win else np.array([])
    return sc.jsonable({
        "target": target, "horizon": horizon, "psi_history": history,
        "latest": {"at": max(by_time) if by_time else None, "features": [{"feature": f, "psi": p, "level": drift_lib.data_drift_status(p)} for f, p in latest[:60]],
                   "n": len(latest)},
        "live": {"n_resolved": len(hits), "n_independent": len(indep), "hit_rate": float(np.mean(hits)) if hits else None,
                 "dates": [live[i][0][:10] for i in indep_idx], "hits": indep, "rolling": roll, "window": win, "ph": ph["values"], "detected_at": ph["detected_at"],
                 "detected_date": live[indep_idx[ph["detected_at"]]][0][:10] if ph["detected_at"] is not None else None},
        "params": {"delta": drift_lib.PAGE_HINKLEY_DELTA, "lambda": drift_lib.PAGE_HINKLEY_LAMBDA, "min_independent": drift_policy.MIN_INDEPENDENT_CALLS,
                   "psi_alert": drift_policy.SIGNIFICANT_PSI}})
