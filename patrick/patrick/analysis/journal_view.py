"""Lecture du journal de prédictions chaîné (`tracking/journal.py`) : état de la chaîne, réussite et calibration live par couple, écarts avec la table
`prediction`, liste des lignes, export CSV. La preuve est le journal, jamais la table `prediction` (qui se réécrit)."""
from __future__ import annotations

import csv
import io
import sqlite3

import numpy as np

from patrick.analysis import stats_core as sc
from patrick.tracking import journal

MIN_CALIBRATION = 30
LAST_N = 30
DIVERGENCE_LIMIT = 30


def _load(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT journal_id, recorded_at, kind, origin, run_id, trial_id, target, horizon, signal_date, y_pred, p_up, y_true, model_hash, entry_hash "
                        "FROM prediction_journal ORDER BY journal_id").fetchall()


def overview(conn: sqlite3.Connection) -> dict:
    rows = _load(conn)
    signals: dict[tuple, dict] = {}
    outcome: dict[tuple, float] = {}
    for jid, rec, kind, origin, run_id, trial_id, target, horizon, day, y_pred, p_up, y_true, mh, _eh in rows:
        key = (trial_id, day)
        if kind == "signal":
            signals.setdefault(key, {"target": target, "horizon": int(horizon), "run_id": run_id, "y_pred": y_pred, "p_up": p_up, "origin": origin, "model_hash": mh, "day": day, "at": rec})
        elif y_true is not None:
            outcome[key] = float(y_true)                      # la dernière issue journalisée fait foi
    pairs: dict[tuple, list] = {}
    for key, s in signals.items():
        pairs.setdefault((s["target"], s["horizon"]), []).append((s["day"], s, outcome.get(key)))
    items = []
    for (t, h), lst in sorted(pairs.items()):
        lst.sort(key=lambda x: x[0])
        judged = [(s, y) for _, s, y in lst if y is not None and s["y_pred"] is not None]
        hits = [int((s["y_pred"] >= 2) == (y >= 0.5)) for s, y in judged]
        pu = [(s["p_up"], 1.0 if y >= 0.5 else 0.0) for s, y in judged if s["p_up"] is not None]
        cal = None
        if len(pu) >= MIN_CALIBRATION:
            r = sc.reliability([a for a, _ in pu], [b for _, b in pu], 5, "quantile")
            cal = {"ece": r["ece"], "brier": r["brier"], "base_brier": r["uncertainty"], "mean_p": float(np.mean([a for a, _ in pu])), "base_rate": r["base_rate"], "n": r["n"]}
        items.append({"target": t, "horizon": h, "signals": len(lst), "judged": len(judged), "pending": len(lst) - len(judged), "hit_rate": float(np.mean(hits)) if hits else None,
                      "last_hit": float(np.mean(hits[-LAST_N:])) if len(hits) >= 5 else None, "calibration": cal,
                      "backfill": sum(1 for _, s, _y in lst if s["origin"] == "backfill"), "first": lst[0][0], "last": lst[-1][0],
                      "models": len({s["model_hash"] for _, s, _y in lst if s["model_hash"]})})
    # écarts entre le premier signal journalisé et la table `prediction` (qui peut se réécrire)
    divergences = []
    n_checked = 0
    for (trial_id, day), s in signals.items():
        row = conn.execute("SELECT y_pred, p_up FROM prediction WHERE trial_id = ? AND split = 'live' AND ts LIKE ? LIMIT 1", (trial_id, day + "%")).fetchone()
        if row is None:
            continue
        n_checked += 1
        same_pred = s["y_pred"] is None or row[0] is None or abs(float(row[0]) - float(s["y_pred"])) < 1e-9
        same_p = s["p_up"] is None or row[1] is None or abs(float(row[1]) - float(s["p_up"])) < 1e-6
        if not (same_pred and same_p) and len(divergences) < DIVERGENCE_LIMIT:
            divergences.append({"target": s["target"], "horizon": s["horizon"], "day": day, "journal": {"y_pred": s["y_pred"], "p_up": s["p_up"]}, "table": {"y_pred": row[0], "p_up": row[1]}})
    n_div = sum(1 for _ in divergences)
    stamps = [r[1] for r in rows]
    return sc.jsonable({
        "n_entries": len(rows), "n_signals": len(signals), "n_outcomes": len(outcome), "first_at": stamps[0] if stamps else None, "last_at": stamps[-1] if stamps else None,
        "n_backfill": sum(1 for s in signals.values() if s["origin"] == "backfill"), "n_models": len({s["model_hash"] for s in signals.values() if s["model_hash"]}),
        "pairs": items, "divergences": divergences, "n_divergences": n_div, "n_checked": n_checked})


def entries(conn: sqlite3.Connection, target: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    limit = max(1, min(1000, limit))
    where, params = ("WHERE target = ?", [target]) if target else ("", [])
    total = conn.execute(f"SELECT COUNT(*) FROM prediction_journal {where}", params).fetchone()[0]
    cols = ("journal_id", "recorded_at", "kind", "origin", "run_id", "target", "horizon", "signal_date", "y_pred", "p_up", "y_true", "model_hash", "prev_hash", "entry_hash")
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM prediction_journal {where} ORDER BY journal_id DESC LIMIT ? OFFSET ?", (*params, limit, max(0, offset))).fetchall()
    return sc.jsonable({"total": int(total), "items": [dict(zip(cols, r, strict=True)) for r in rows]})


def export_csv(conn: sqlite3.Connection) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    cols = ("journal_id", "recorded_at", "kind", "origin", "run_id", "trial_id", "target", "horizon", "signal_date", "y_pred", "p_up", "y_true", "model_hash", "config_hash",
            "prev_hash", "entry_hash")
    w.writerow(cols)
    for r in conn.execute(f"SELECT {', '.join(cols)} FROM prediction_journal ORDER BY journal_id"):
        w.writerow(["" if v is None else v for v in r])
    return out.getvalue()


def verify(conn: sqlite3.Connection) -> dict:
    return sc.jsonable(journal.verify(conn))
