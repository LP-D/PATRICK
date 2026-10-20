"""Garde-fous (`patrick/analysis/guardrails.py`, `/garde-fous`) : p déflatée, verdicts, lectures du holdout enregistrées et déduites."""
from __future__ import annotations

import math

import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import guardrails, registry
from patrick.tracking import db as trackdb
from patrick.webapp.app import app


def test_deflated_matches_closed_form_and_grows_with_trials():
    d1 = guardrails.deflated(0.60, 280, 1, 1)
    assert d1["n_eff"] == 280 and d1["p"] == pytest.approx(d1["p_deflated"])          # un seul essai : pas de déflation
    d100 = guardrails.deflated(0.60, 280, 1, 100)
    assert d100["p_deflated"] == pytest.approx(1 - (1 - d1["p"]) ** 100)
    assert d100["p_deflated"] > d1["p"] and d100["null_best"] > 0.5 and d100["margin"] == pytest.approx(0.60 - d100["null_best"])
    big = guardrails.deflated(0.60, 280, 1, 100_000)
    assert big["p_deflated"] == 1.0 and big["null_best"] > d100["null_best"]


def test_deflated_divides_the_count_by_the_horizon():
    short = guardrails.deflated(0.58, 300, 1, 50)
    long_ = guardrails.deflated(0.58, 300, 10, 50)
    assert long_["n_eff"] == 30 and long_["p_deflated"] > short["p_deflated"]
    assert guardrails.deflated(None, 300, 1, 50)["p"] is None and guardrails.deflated(0.6, 300, 1, 0)["p"] is None
    assert math.isfinite(guardrails.deflated(0.55, 1, 1, 10)["null_best"])


def test_summary_counts_runs_trials_and_inferred_reads(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, skill=0.7, extra_trials=4)
    trackdb.register_trials(conn, "TST", 2, "optuna", 300, run_id=info["run_id"])
    d = guardrails.summary(conn)
    row = next(r for r in d["rows"] if r["target"] == "TST" and r["horizon"] == 2)
    assert row["runs"] == 1 and row["configs"] == 1
    assert row["trials"] == 300 + 5                                    # 1 essai gagnant + 4 autres (scan) + 300 Optuna
    assert row["reads_recorded"] == 0 and row["reads_inferred"] == 1    # un run terminé avec holdout = une lecture déduite
    assert row["best_acc"] is not None and row["p_deflated"] >= row["p"]
    assert d["registry"]["by_source"]["optuna"]["trials"] == 300 and d["reads"]["recorded"] == 0 and d["reads"]["inferred"] == 1
    assert d["fdr"]["alpha"] == 0.10


def test_recorded_reads_and_selecting_purpose_are_separated(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    trackdb.record_holdout_access(conn, "TST", 2, "final_eval", run_id=info["run_id"], holdout_start="2025-01-01", holdout_end="2025-06-01", n_rows=120)
    trackdb.record_holdout_access(conn, "TST", 2, "champion_duel_challenger", run_id=info["run_id"], holdout_start="2025-01-01", holdout_end="2025-06-01", n_rows=120)
    d = guardrails.summary(conn)
    row = next(r for r in d["rows"] if r["target"] == "TST")
    assert row["reads_recorded"] == 2 and row["reads_selecting"] == 1
    assert d["reads"]["recorded"] == 2 and d["reads"]["selecting"] == 1 and d["reads"]["first_at"]
    assert d["reads"]["pairs_read_more_than_once"] == 1 and len(d["log"]) == 2
    assert {x["purpose"] for x in d["log"]} == {"final_eval", "champion_duel_challenger"}


def test_too_good_score_is_flagged_suspect_not_beyond_noise(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    trackdb.add_fold_metrics(conn, info["trial_id"], 0, "holdout", {"Acc_dir": 0.9})
    d = guardrails.summary(conn)
    assert next(r for r in d["rows"] if r["target"] == "TST")["verdict"] == "suspect"


def test_guardrails_page_and_api(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, _ = seed_run(tmp_path, monkeypatch)
    conn.close()
    c = TestClient(app)
    page = c.get("/garde-fous")
    assert page.status_code == 200 and "guardrails.js" in page.text and 'id="ag-root"' in page.text
    api = c.get("/api/garde-fous/summary")
    assert api.status_code == 200 and "NaN" not in api.text
    body = api.json()
    assert body["registry"]["total"] >= 3 and any(r["target"] == "TST" for r in body["rows"])
    assert 'href="/garde-fous"' in c.get("/").text                        # entrée de la barre latérale
