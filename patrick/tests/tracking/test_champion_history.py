"""D26 : frise des champions d'une cible, reconstruite à partir du champion en titre et de l'archive des champions détrônés."""
from __future__ import annotations

import datetime as dt
import json

from patrick.tracking import champion_history
from patrick.tracking import db as trackdb


def _run(conn, run_id, target="AAPL", horizon=1, algo="XGBoost", finished="2026-01-01 10:00:00"):
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "none", 3, "shap")
    conn.execute("UPDATE run SET finished_at = ? WHERE run_id = ?", (finished, run_id))
    conn.commit()
    return tid


def test_reigns_follow_each_other_and_the_current_champion_ends_the_list(conn):
    _run(conn, "r1", algo="LightGBM")
    _run(conn, "r2", algo="XGBoost")
    t3 = _run(conn, "r3", algo="CatBoost")
    conn.executemany("INSERT INTO model_archive (target, horizon, run_id, role, decided_at, algo, run_finished_at, duel_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("AAPL", 1, "r1", "replaced_champion", "2026-02-01 08:00:00", "LightGBM", "2026-01-01 10:00:00", json.dumps({"rule": "AUC_dir strictly greater"})),
        ("AAPL", 1, "r2", "replaced_champion", "2026-03-01 08:00:00", "XGBoost", "2026-01-20 10:00:00", None),
        ("AAPL", 1, "rx", "rejected_challenger", "2026-02-15 08:00:00", "MLP", None, None),          # jamais champion : ignoré
    ])
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) VALUES ('AAPL', 1, 'r3', ?, '2026-03-01 08:00:00', 'won_duel')", (t3,))
    conn.commit()

    out = champion_history.history(conn, "AAPL", now=dt.datetime(2026, 3, 11, tzinfo=dt.UTC))

    reigns = out[1]
    assert [(r["algo"], r["start"], r["end"], r["days"], r["current"]) for r in reigns] == [
        ("LightGBM", "2026-01-01", "2026-02-01", 30, False),
        ("XGBoost", "2026-02-01", "2026-03-01", 28, False),
        ("CatBoost", "2026-03-01", None, 9, True)]
    assert reigns[0]["lost_by"] == "AUC_dir strictly greater" and reigns[1]["lost_by"] is None


def test_an_asset_without_champion_has_no_history(conn):
    assert champion_history.history(conn, "MSFT") == {}
