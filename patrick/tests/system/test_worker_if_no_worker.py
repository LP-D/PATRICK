"""`patrick worker --if-no-worker` (AM8 du 25/11) : la tâche planifiée ne lance jamais un second worker ni un worker sans travail."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from patrick.cli import app as cli_app
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db


def test_without_a_queued_job_the_task_does_nothing(monkeypatch):
    monkeypatch.setattr("patrick.cli.worker_module.run_worker_loop", lambda **kw: (_ for _ in ()).throw(AssertionError("lancé")))
    trackdb.connect().close()
    result = CliRunner().invoke(cli_app, ["worker", "--if-no-worker"])
    assert result.exit_code == 0 and "Aucun job en file" in result.output


def test_a_live_worker_is_never_doubled(monkeypatch):
    monkeypatch.setattr("patrick.cli.worker_module.run_worker_loop", lambda **kw: (_ for _ in ()).throw(AssertionError("lancé")))
    monkeypatch.setattr(jobs_db, "worker_is_alive", lambda conn: True)
    result = CliRunner().invoke(cli_app, ["worker", "--if-no-worker"])
    assert result.exit_code == 0 and "worker vivant" in result.output


def test_a_queued_job_without_a_worker_starts_one(monkeypatch):
    started = {}
    monkeypatch.setattr("patrick.cli.worker_module.run_worker_loop", lambda **kw: started.update(kw))
    conn = trackdb.connect()
    jobs_db.enqueue_job(conn, json.dumps({"name": "x"})) if hasattr(jobs_db, "enqueue_job") else conn.execute(
        "INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'queued')")
    conn.commit()
    conn.close()
    result = CliRunner().invoke(cli_app, ["worker", "--if-no-worker"])
    assert result.exit_code == 0 and "idle_timeout" in started
