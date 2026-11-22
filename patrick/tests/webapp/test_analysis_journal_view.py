"""Lecture du journal de prédictions (`patrick/analysis/journal_view.py`, `/journal`)."""
from __future__ import annotations

import numpy as np
import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import journal_view as jv
from patrick.analysis import registry
from patrick.tracking import db as trackdb
from patrick.webapp.app import app


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, live=0)
    yield conn, info
    registry.clear_cache()


def _emit(conn, info, n=40, hit_rate=0.7, seed=0):
    rng = np.random.default_rng(seed)
    days = [(np.datetime64("2027-01-04") + i).astype(str) for i in range(n)]
    ts = [d + " 00:00:00" for d in days]
    trackdb.add_predictions(conn, info["trial_id"], 0, "live", ts, [None] * n, [2.0] * n, [0.6] * n, p_up=[0.62] * n)      # tous prédisent « hausse »
    for t in ts:
        up = rng.random() < hit_rate
        trackdb.update_prediction_outcome(conn, info["trial_id"], t, 1.0 if up else 0.0, 3 if up else 0)


def test_overview_counts_hit_rate_and_calibration_from_the_journal(seeded):
    conn, info = seeded
    _emit(conn, info)
    d = jv.overview(conn)
    assert d["n_signals"] == 40 and d["n_outcomes"] == 40 and d["n_entries"] == 80 and d["n_backfill"] == 0 and d["n_models"] in (0, 1)
    p = d["pairs"][0]
    assert p["target"] == "TST" and p["signals"] == 40 and p["judged"] == 40 and p["pending"] == 0 and 0.4 < p["hit_rate"] < 0.95
    assert p["last_hit"] is not None and p["calibration"] and p["calibration"]["n"] == 40
    assert d["n_divergences"] == 0 and d["n_checked"] == 40


def test_overview_reports_a_rewritten_prediction_table(seeded):
    conn, info = seeded
    _emit(conn, info, n=10)
    conn.execute("UPDATE prediction SET y_pred = 0.0, p_up = 0.05 WHERE trial_id = ? AND split = 'live' AND ts LIKE '2027-01-06%'", (info["trial_id"],))
    conn.commit()
    d = jv.overview(conn)
    assert d["n_divergences"] == 1 and d["divergences"][0]["day"] == "2027-01-06"
    assert d["divergences"][0]["journal"]["y_pred"] == 2.0 and d["divergences"][0]["table"]["y_pred"] == 0.0


def test_entries_pagination_filter_and_export(seeded):
    conn, info = seeded
    _emit(conn, info, n=6)
    page = jv.entries(conn, None, limit=5, offset=0)
    assert page["total"] == 12 and len(page["items"]) == 5 and page["items"][0]["journal_id"] > page["items"][-1]["journal_id"]
    assert jv.entries(conn, "NOPE")["total"] == 0 and jv.entries(conn, "TST", 5000)["total"] == 12
    csv_text = jv.export_csv(conn)
    lines = csv_text.strip().split("\n")
    assert lines[0].startswith("journal_id,recorded_at,kind") and len(lines) == 13


def test_journal_pages_and_api(seeded):
    conn, info = seeded
    _emit(conn, info, n=8)
    conn.close()
    c = TestClient(app)
    assert c.get("/journal").status_code == 200 and 'href="/journal"' in c.get("/").text
    ov = c.get("/api/journal/overview")
    assert ov.status_code == 200 and ov.json()["n_signals"] == 8 and "NaN" not in ov.text
    assert c.get("/api/journal/entries?limit=3").json()["total"] == 16
    ver = c.get("/api/journal/verify").json()
    assert ver["ok"] is True and ver["n"] == 16
    assert c.get("/api/journal/export.csv").headers["content-type"].startswith("text/csv")
    seal = c.post("/api/journal/seal")
    assert seal.status_code == 200 and seal.json()["sealed"] == 0               # tout est déjà journalisé
