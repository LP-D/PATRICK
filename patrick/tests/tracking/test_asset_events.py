"""D3 : événements datés d'un actif (changements de champion, publications de résultats) pour sa courbe de cours."""
from __future__ import annotations

from patrick.tracking import asset_events
from patrick.tracking import db as trackdb


def test_champion_changes_and_earnings_are_merged_by_date(conn):
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    trackdb.create_run(conn, "r1", target="AAPL", horizon=1, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "none", 3, "shap")
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) VALUES ('AAPL', 1, 'r1', ?, '2026-03-01 08:00:00', 'first')", (tid,))
    conn.execute("CREATE TABLE IF NOT EXISTS earn_calendar (symbol TEXT, ann_date TEXT, ann_local_time TEXT, timing TEXT, timing_source TEXT)")
    conn.executemany("INSERT INTO earn_calendar (symbol, ann_date, ann_local_time, timing, timing_source) VALUES (?, ?, '', 'AMC', 'yahoo')",
                     [("AAPL", "2026-01-29"), ("AAPL", "2026-04-30"), ("MSFT", "2026-01-28")])
    conn.commit()

    out = asset_events.events(conn, "AAPL")

    assert out == [{"date": "2026-01-29", "kind": "earnings", "label": "R"}, {"date": "2026-03-01", "kind": "champion", "label": "C1"},
                   {"date": "2026-04-30", "kind": "earnings", "label": "R"}]


def test_a_base_without_earnings_tables_gives_champion_changes_only(conn):
    assert asset_events.events(conn, "AAPL") == []


def test_several_champion_changes_on_one_day_share_one_label(conn):
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    for h in (1, 5, 10):
        trackdb.create_run(conn, f"r{h}", target="AAPL", horizon=h, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
        tid = trackdb.create_trial(conn, f"r{h}", "GLOBAL", "XGBoost", "none", 3, "shap")
        conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) VALUES ('AAPL', ?, ?, ?, '2026-03-01 08:00:00', 'first')",
                     (h, f"r{h}", tid))
    conn.commit()
    assert asset_events.events(conn, "AAPL") == [{"date": "2026-03-01", "kind": "champion", "label": "C1·5·10"}]
