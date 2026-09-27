"""Le serveur web lance le worker avec stdout/stderr sur DEVNULL
(`run_manager._spawn_worker`) : un worker qui meurt emportait sa trace avec
lui (2026-09-27 : job GSPC_61 resté 'running', worker disparu sans rien
laisser). Le worker écrit désormais son propre journal dans `logs/`, à côté
de la base -- démarrage, jobs, sortie du pipeline, traceback et arrêt.
Rapide : aucun vrai pipeline n'est exécuté (`run_pipeline` est remplacé).
"""
from __future__ import annotations

import os
import sys

import pytest

from patrick import worker as worker_module
from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    trackdb.connect(path).close()
    return path


def _logs(tmp_path) -> list[str]:
    log_dir = tmp_path / "logs"
    return sorted(os.listdir(log_dir)) if log_dir.exists() else []


def _read_single_log(tmp_path) -> str:
    names = _logs(tmp_path)
    assert len(names) == 1, names
    return (tmp_path / "logs" / names[0]).read_text(encoding="utf-8")


def _enqueue_minimal_job(db_path: str) -> str:
    config = RunConfig.model_validate({
        "name": "log_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
    })
    conn = trackdb.connect(db_path)
    try:
        return jobs_db.enqueue_job(conn, config.model_dump_json())
    finally:
        conn.close()


def test_worker_writes_its_log_next_to_the_db(tmp_path, db_path):
    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    names = _logs(tmp_path)
    assert len(names) == 1
    assert names[0].startswith("worker-") and names[0].endswith(f"-{os.getpid()}.log")
    text = _read_single_log(tmp_path)
    assert "[WORKER] started" in text
    assert "[WORKER] exit" in text


def test_worker_logs_the_traceback_when_its_loop_crashes(tmp_path, db_path, monkeypatch):
    def boom(conn, pid):
        raise RuntimeError("boom in claim")

    monkeypatch.setattr(worker_module.jobs_db, "claim_next_job", boom)
    with pytest.raises(RuntimeError, match="boom in claim"):
        worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    text = _read_single_log(tmp_path)
    assert "[WORKER] died" in text
    assert "RuntimeError: boom in claim" in text
    assert "[WORKER] exit" in text


def test_job_output_and_pipeline_traceback_reach_the_log(tmp_path, db_path, monkeypatch):
    def fake_pipeline(config, **kwargs):
        print("PIPELINE-LINE ingestion en cours")
        raise ValueError("pipeline cassé")

    monkeypatch.setattr(worker_module, "run_pipeline", fake_pipeline)
    job_id = _enqueue_minimal_job(db_path)

    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    text = _read_single_log(tmp_path)
    assert f"[WORKER] job {job_id} claimed" in text
    assert "PIPELINE-LINE ingestion en cours" in text
    assert "ValueError: pipeline cassé" in text
    assert f"[WORKER] job {job_id} finished: error" in text
    conn = trackdb.connect(db_path)
    try:
        assert jobs_db.get_job(conn, job_id)["status"] == "error"
    finally:
        conn.close()


def test_worker_restores_stdout_and_stderr(tmp_path, db_path):
    out, err = sys.stdout, sys.stderr
    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)
    assert sys.stdout is out
    assert sys.stderr is err


def test_worker_keeps_only_the_most_recent_logs(tmp_path, db_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for i in range(30):
        (log_dir / f"worker-20200101-0000{i:02d}-1.log").write_text("old", encoding="utf-8")

    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    names = _logs(tmp_path)
    assert len(names) == worker_module._WORKER_LOGS_KEPT
    assert any(n.endswith(f"-{os.getpid()}.log") for n in names)
    assert "worker-20200101-000000-1.log" not in names
