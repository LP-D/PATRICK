"""Decision of 2026-09-26: the 504- and 756-day horizons are DESCRIPTIVE.

On real prices (docs/modelisation/horizons-longs.md), beating "always up"
significantly at 504/756 days would need ~98-100 % accuracy on the S&P 500
over its whole history (N_eff ~ 12-18 independent observations); inside a
15-month holdout there is less than one. They stay launchable for
exploration, but:
- they are out of the cross-target Benjamini-Hochberg family (a target only
  tested at those horizons is not "tested");
- no portfolio signal uses them (/portfolio, patrimoine signal replay);
- every page labels them "descriptif".
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.tracking import db as trackdb
from patrick.tracking import portfolio as trackportfolio
from patrick.tracking import stats as trackstats
from patrick.wealth import signal_replay
from patrick.webapp.app import app


def _run(conn, run_id, target, horizon, started_at=None):
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, None)
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap",
                        config_json=json.dumps({"validation": {"scheme": "walkforward"}}),
                        config_hash="c", git_sha="g", seed=42)
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 5, "shap")
    trackdb.mark_best_trial(conn, tid)
    trackdb.finish_run(conn, run_id, status="done")
    if started_at:
        with conn:
            conn.execute("UPDATE run SET started_at = ? WHERE run_id = ?", (started_at, run_id))
    return tid


def _dm(conn, run_id, p):
    trackdb.save_dm_result(conn, run_id, {"baseline": "BASELINE_persistence", "dm_stat": -3.0,
                                          "p_value": p, "n_obs": 250},
                           kind="class_specific", sample="holdout")


def test_the_descriptive_set():
    assert frozenset({504, 756}) == D.DESCRIPTIVE_HORIZONS
    assert 252 not in D.DESCRIPTIVE_HORIZONS


def test_bh_family_ignores_descriptive_horizons(conn):
    _run(conn, "a756", "^A", 756)
    _dm(conn, "a756", 0.0001)                  # only ever tested at 756 days: not in the family
    _run(conn, "b5", "^B", 5)
    _dm(conn, "b5", 0.5)
    _run(conn, "b504", "^B", 504)
    _dm(conn, "b504", 0.00001)                 # must not rescue ^B
    fdr = trackstats.fdr_across_targets(conn, alpha=0.10)
    assert set(fdr["results"]) == {"^B"} and fdr["n_tested"] == 1
    assert fdr["results"]["^B"]["p_value"] == pytest.approx(0.5)
    assert fdr["n_descriptive_runs"] == 2


def test_patrimoine_replay_never_uses_a_descriptive_model(conn):
    _run(conn, "old5", "^GSPC", 5, started_at="2026-01-01 00:00:00")
    _run(conn, "new756", "^GSPC", 756, started_at="2026-09-01 00:00:00")
    run_id, _trial, horizon = signal_replay._winning_trial(conn, "^GSPC")
    assert (run_id, horizon) == ("old5", 5)


def test_portfolio_drops_descriptive_horizons_even_when_asked(conn):
    out = trackportfolio.portfolio_overview(conn, horizons=[5, 504, 756])
    assert out["horizons"] == [5]


def test_pages_label_descriptive_horizons(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = trackdb.connect(str(tmp_path / "p.db"))
    _run(conn, "r756", "^GSPC", 756)
    conn.close()
    client = TestClient(app)
    assert "756j · descriptif" in client.get("/runs").text
    assert "756 (descriptif)" in client.get("/launch").text


def test_synthesis_says_how_many_runs_are_outside_the_family(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = trackdb.connect(str(tmp_path / "p.db"))
    _run(conn, "b5", "^B", 5)
    _dm(conn, "b5", 0.04)
    _run(conn, "b756", "^B", 756)
    _dm(conn, "b756", 0.001)
    conn.close()
    html = TestClient(app).get("/").text
    assert "1 run(s) à 504/756 j hors famille" in html
