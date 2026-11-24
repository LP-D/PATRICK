"""`patrick audit fx-gap` : exactitude directionnelle holdout / réel des cibles de change, par règle d'alignement."""
from __future__ import annotations

import json

from patrick.audit.fx_gap import fx_gap
from patrick.tracking import db as trackdb


def _run(conn, run_id, target, rule, holdout, live, horizon=1):
    """`holdout` / `live` : listes de (y_pred, y_true) ; holdout en 4 classes, réel en binaire."""
    trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
    cfg = json.dumps({"objective": {"session_rule": rule}})
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap", config_json=cfg, config_hash="c",
                       git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 3, "shap")
    trackdb.mark_best_trial(conn, tid, artifact_path=None)
    trackdb.finish_run(conn, run_id, "done")
    for i, (p, t) in enumerate(holdout):
        conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred) VALUES (?, ?, 'holdout', ?, ?)", (tid, f"2025-01-{i % 28 + 1:02d}", t, p))
    for i, (p, t) in enumerate(live):
        conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred) VALUES (?, ?, 'live', ?, ?)", (tid, f"2026-02-{i % 28 + 1:02d}", t, p))
    conn.commit()


def test_the_gap_is_measured_per_alignment_rule(conn):
    # règle 1 : 8/10 au holdout, 5/10 en réel ; règle 2 : 6/10 et 6/10 ; une action et un run trop jeune sont ignorés
    _run(conn, "fx1", "EURUSD=X", 1, [(3, 3)] * 8 + [(3, 0)] * 2, [(3, 1.0)] * 5 + [(3, 0.0)] * 5)
    _run(conn, "fx2", "GBPUSD=X", 2, [(0, 1)] * 6 + [(0, 3)] * 4, [(0, 0.0)] * 6 + [(0, 1.0)] * 4)
    _run(conn, "young", "JPY=X", 2, [(3, 3)] * 10, [(3, 1.0)] * 3)
    _run(conn, "eq", "AAPL", 1, [(3, 3)] * 10, [(3, 1.0)] * 10)

    out = fx_gap(conn, horizon=1, min_live=10)

    r1, r2 = out["rules"][1], out["rules"][2]
    assert (r1["runs"], round(r1["holdout_acc"], 3), round(r1["live_acc"], 3), round(r1["gap_points"], 1)) == (1, 0.8, 0.5, 30.0)
    assert (r2["runs"], r2["too_young"], round(r2["gap_points"], 1)) == (1, 1, 0.0)


def test_no_fx_run_gives_no_rule(conn):
    assert fx_gap(conn)["rules"] == {}
