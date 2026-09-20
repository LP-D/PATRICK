"""Regression tests for the lot-1 webapp security/perf fixes (commit
3dab360, parent 288b418): reflected XSS on /runs, stored XSS via
data_table, open redirect on /set-lang, and the list_all_runs N+1. Same
style as test_predictions_page.py/test_history.py -- real Jinja templates
through a real FastAPI route or direct db.py calls, DB seeded via
PATRICK_DB_PATH/db.create_run, no pipeline run, no network."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp.app import app


def _seed_run(tmp_path, monkeypatch, run_id: str, target: str) -> None:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    config = {"name": run_id, "validation": {"scheme": "walkforward"}}
    db.create_run(conn, run_id, target, 5, f"snap_{run_id}", json.dumps(config), "cfghash", "sha", 42)
    db.finish_run(conn, run_id, status="done", n_trials=1)
    conn.close()


def test_runs_page_escapes_reflected_scheme_query_param(tmp_path, monkeypatch):
    """A1 -- /runs?scheme=<script>... used to land unescaped in the
    filter-summary footer (runs.html builds it via string concatenation),
    rendered via `{{ footer | safe }}` inside data_table.

    Uses `scheme` rather than `target`/`status`: `data_table`'s footer is
    only emitted when `rows` is non-empty (see `_components.html::
    data_table`), so the filtered set needs a matching row. `status` is
    DB-constrained (`CHECK status IN (...)`, can't hold a payload) and
    `list_all_runs` HTML-escapes `target`/`name` for display (see the
    other test below) but not `scheme` (read from `config_json`, free-
    form JSON, no DB constraint) -- so filtering by an exact `scheme`
    doesn't hit either problem."""
    payload = "<script>alert(1)</script>"
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    config = json.dumps({"validation": {"scheme": payload}})
    db.create_run(conn, "run1", "AAPL", 5, "snap1", config, "cfghash", "sha", 42)
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()
    client = TestClient(app)
    resp = client.get("/runs", params={"scheme": payload})
    assert resp.status_code == 200
    assert payload not in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text


def test_runs_page_escapes_stored_target_from_a_cli_launched_run(tmp_path, monkeypatch):
    """A2 -- a CLI-launched run's `target` is never sanitized the way the
    web form's slug_target sanitizes a submission; data_table renders every
    cell (including `target`) via `{{ cell | safe }}`."""
    payload = "<img src=x onerror=alert(1)>"
    _seed_run(tmp_path, monkeypatch, "run1", payload)
    client = TestClient(app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert payload not in resp.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in resp.text


def test_set_lang_rejects_scheme_relative_and_absolute_next(tmp_path, monkeypatch):
    """A3 -- /set-lang/{lang}?next= used to 303-redirect to `next` verbatim,
    no validation at all."""
    client = TestClient(app)
    for bad_next in ("//evil.example", "https://evil.example", "http://evil.example/x"):
        resp = client.get(f"/set-lang/fr?next={bad_next}", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/", (bad_next, resp.headers["location"])
    # A legitimate internal path must still be honored.
    resp = client.get("/set-lang/fr?next=/runs", follow_redirects=False)
    assert resp.headers["location"] == "/runs"


def test_list_all_runs_query_count_does_not_scale_with_run_count(tmp_path):
    """A4 -- list_all_runs used to run up to 3 extra queries PER run (best
    trial, its avg F1_dir, its dm_result) inside a Python loop. Same
    set_trace_callback technique as
    test_history.py::test_synthesis_overview_*_is_not_n_plus_1 --
    set_trace_callback reports the EXPANDED SQL (values inlined), so the
    per-run patterns are matched by their distinctive shape (a single-row
    `LIMIT 1` lookup, or a lack of a batched `IN (...)` clause) rather than
    a literal `?` placeholder."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    n_runs = 20
    for i in range(n_runs):
        run_id = f"run{i}"
        db.upsert_snapshot(conn, f"snap{i}", f"hash{i}", None, None, None)
        db.create_run(conn, run_id, f"SYM{i}", 5, f"snap{i}", "{}", "cfghash", "sha", 42)
        trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, trial_id)
        db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6})
        db.save_dm_result(conn, run_id, {"baseline": "majority", "dm_stat": 1.0, "p_value": 0.04})
        db.finish_run(conn, run_id, status="done", n_trials=1)

    queries: list[str] = []
    conn.set_trace_callback(lambda sql: queries.append(sql))
    db.list_all_runs(conn)
    conn.set_trace_callback(None)
    conn.close()

    per_run_best_trial = [q for q in queries if "FROM trial WHERE run_id = " in q and "LIMIT 1" in q]
    per_run_fold_metric = [q for q in queries if "FROM fold_metric WHERE trial_id = " in q and " IN (" not in q]
    per_run_dm = [q for q in queries if "FROM dm_result WHERE run_id = " in q and " IN (" not in q]
    assert not per_run_best_trial, f"{len(per_run_best_trial)} per-run best-trial lookups for {n_runs} runs"
    assert not per_run_fold_metric, f"{len(per_run_fold_metric)} per-run fold_metric lookups for {n_runs} runs"
    assert not per_run_dm, f"{len(per_run_dm)} per-run dm_result lookups for {n_runs} runs"
