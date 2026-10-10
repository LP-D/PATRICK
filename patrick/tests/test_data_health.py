"""Page « Qualité des données » et son module (`tracking/data_health.py`) : cause des échecs, séries écartées, historique
comparé au seuil, résultats suspects, et le grisé des cibles trop récentes sur la page Lancer."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import data_health
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

TODAY = date(2026, 10, 9)


@pytest.mark.parametrize("message, kind", [
    ("XGBoostError: [22:25:13] gradient_index.h:99: Check failed: valid: Input data contains `inf` or a value too large",
     "float32_overflow"),
    ("orphaned: no matching process at worker startup", "orphaned"),
    ("Stopped by user.", "stopped"),
    ("IndexError: index 3 is out of bounds for axis 1 with size 3", "class_missing"),
    ("sqlite3.OperationalError: database is locked", "db_locked"),
    ("RuntimeError: [QUALITY] Insufficient history: data must go back at least 10 years", "insufficient_history"),
    ("something nobody planned for", "other"), (None, "other"),
])
def test_errors_are_classified_by_cause(message, kind):
    assert data_health.classify_error(message)[0] == kind


def _job(conn, job_id, name, target, error, status="error"):
    cfg = {"name": name, "objective": {"target_symbol": target}}
    with conn:
        conn.execute("INSERT INTO job (job_id, config_json, status, error, finished_at) VALUES (?, ?, ?, ?, datetime('now'))",
                     (job_id, json.dumps(cfg), status, error))


def test_failures_are_grouped_by_cause_with_their_targets(conn):
    _job(conn, "j1", "VIX_18", "^VIX", "XGBoostError: Input data contains `inf` or a value too large")
    _job(conn, "j2", "CL_F_3", "CL=F", "XGBoostError: Input data contains `inf` or a value too large")
    _job(conn, "j3", "GC_1", "GC=F", "Stopped by user.")
    summary = data_health.failure_summary(data_health.failures(conn))
    assert [(g["kind"], g["n"]) for g in summary] == [("float32_overflow", 2), ("stopped", 1)]
    assert summary[0]["targets"] == ["^VIX", "CL=F"]
    assert "Corrigé" in summary[0]["status"]


def test_quality_issues_are_grouped_by_reason_and_counted_per_snapshot(conn):
    for sid in ("s1", "s2"):
        trackdb.upsert_snapshot(conn, sid, "h" + sid, None, None, None)
        trackdb.add_data_quality_issues(conn, sid, [
            {"series": "ETH_USD", "reason": "couverture_insuffisante", "detail": "53.1% of business days populated"},
            {"series": "SHY", "reason": "prix_figes", "detail": "5 consecutive identical closes"}])
    groups = {g["reason"]: g for g in data_health.quality_issues(conn)}
    eth = groups["couverture_insuffisante"]["series"][0]
    assert (eth["series"], eth["n_snapshots"]) == ("ETH_USD", 2)
    assert "BTC-USD" in groups["couverture_insuffisante"]["meaning"]
    assert groups["prix_figes"]["effect"]


def test_alignment_decisions_are_stored_once_per_snapshot_even_when_the_snapshot_already_has_issues(conn):
    trackdb.upsert_snapshot(conn, "s1", "h1", None, None, None)
    trackdb.add_data_quality_issues(conn, "s1", [{"series": "X", "reason": "prix_figes", "detail": "d"}])
    rows = [{"series": "IDX_GSPC", "reason": "alignement_temporel", "detail": "retardée de 1 barre(s)"}]
    trackdb.add_alignment_issues(conn, "s1", rows)
    trackdb.add_alignment_issues(conn, "s1", rows)        # idempotent
    found = [i for i in trackdb.list_data_quality_issues(conn, "s1") if i["reason"] == "alignement_temporel"]
    assert len(found) == 1


def _store_with(tmp_path: Path, monkeypatch, entries: dict[str, str]) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    index = {f"raw_{sym}": {"snapshots": [{"snapshot_id": f"s__{sym}", "date_min": first, "date_max": "2026-10-08",
                                          "rows": 3000, "path": "x", "created_at": "2026-10-08T00:00:00+00:00"}]}
             for sym, first in entries.items()}
    (store_dir / "_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(store_dir))


def test_history_is_compared_to_the_threshold(tmp_path, monkeypatch):
    _store_with(tmp_path, monkeypatch, {"^GSPC": "1990-01-02", "BAMLH0A0HYM2": "2023-10-10"})
    groups = {"Indices": [("^GSPC", "SP500_Price")], "Macro (FRED)": [("BAMLH0A0HYM2", "HY_OAS"), ("NEVER_SEEN", "?")]}
    rows = {r["symbol"]: r for r in data_health.history_table(groups, 10, today=TODAY)}
    assert rows["^GSPC"]["status"] == "ok" and rows["^GSPC"]["source"] == "store"
    assert rows["BAMLH0A0HYM2"]["status"] == "short" and rows["BAMLH0A0HYM2"]["years"] == 3.0
    assert rows["NEVER_SEEN"]["status"] == "unknown"
    # le même historique passe un seuil de 3 ans
    assert {r["symbol"]: r["status"] for r in data_health.history_table(groups, 3, today=TODAY)}["BAMLH0A0HYM2"] == "ok"


def test_a_never_ingested_target_falls_back_on_its_verified_first_listing(tmp_path, monkeypatch):
    _store_with(tmp_path, monkeypatch, {})
    rows = {r["symbol"]: r for r in data_health.history_table({"Crypto": [("ETH-USD", "ETH"), ("XLK", "Tech")]}, 10, today=TODAY)}
    assert rows["ETH-USD"]["status"] == "short" and rows["ETH-USD"]["source"] == "declared"
    assert rows["XLK"]["status"] == "ok"


def test_suspect_runs_are_found_from_the_holdout_diagnostic(conn):
    trackdb.upsert_snapshot(conn, "s1", "h", None, None, None)
    trackdb.create_run(conn, "SP500_1_h1_x", target="SP500", horizon=1, snapshot_id="s1", config_json="{}",
                       config_hash="h", git_sha="g", seed=1)
    trackdb.create_run(conn, "GC_1_h1_y", target="GC=F", horizon=1, snapshot_id="s1", config_json="{}",
                       config_hash="h", git_sha="g", seed=1)
    for run_id, f1 in (("SP500_1_h1_x", 0.999), ("GC_1_h1_y", 0.55)):
        tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 5, "shap")
        with conn:
            conn.execute("INSERT INTO holdout_diagnostic (trial_id, metric, value) VALUES (?, 'F1_dir', ?)", (tid, f1))
    suspects = data_health.suspect_runs(conn)
    assert [s["run_id"] for s in suspects] == ["SP500_1_h1_x"]
    assert "FRED" in suspects[0]["cause"]


def test_the_page_renders_and_explains_a_failure(tmp_path, monkeypatch, conn):
    _store_with(tmp_path, monkeypatch, {"^GSPC": "1990-01-02"})
    resp = TestClient(app).get("/data-quality")
    assert resp.status_code == 200
    assert "Qualité des données" in resp.text and "Historique disponible par cible" in resp.text


def test_the_page_rejects_an_out_of_range_threshold(tmp_path, monkeypatch):
    _store_with(tmp_path, monkeypatch, {})
    assert TestClient(app).get("/data-quality?min_history_years=1").status_code == 400


def test_the_launch_page_greys_short_history_targets_without_any_network_call(tmp_path, monkeypatch):
    _store_with(tmp_path, monkeypatch, {"BAMLH0A0HYM2": "2023-10-10"})
    html = TestClient(app).get("/ml").text
    assert 'name="min_history_years"' in html
    assert 'value="BAMLH0A0HYM2" data-first="2023-10-10"' in html
    assert 'id="target-greyed-note"' in html


def test_the_data_quality_page_is_translated(tmp_path, monkeypatch):
    _store_with(tmp_path, monkeypatch, {})
    client = TestClient(app)
    client.cookies.set("patrick_lang", "en")
    assert "Why training runs failed" in client.get("/data-quality").text
