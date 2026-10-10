"""Le worker aiguille un job `"kind": "rl"` vers le moteur RL : mêmes mécanismes de file et d'avancement, autres marqueurs. `run_rl` est
remplacé ici par un faux qui imprime les marqueurs ; l'entraînement réel est couvert par `test_rl_run.py`."""
from __future__ import annotations

import json

import numpy as np
import pytest

from patrick import worker as worker_module
from patrick.rl import agents
from patrick.rl import run as rl_run
from patrick.rl.config import RLRunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


def _config(**rl) -> RLRunConfig:
    return RLRunConfig.model_validate({"name": "rl_job", "objective": {"target_symbol": "^GSPC"}, "rl": {"n_folds": 2, "n_seeds": 2, **rl}})


def _enqueue(config) -> str:
    conn = trackdb.connect(str(trackdb.default_db_path()))
    try:
        return jobs_db.enqueue_job(conn, config.model_dump_json())
    finally:
        conn.close()


def _run_and_read(job_id: str) -> dict:
    worker_module.run_worker_loop(poll_interval=0.1, idle_timeout=1.0)
    conn = trackdb.connect(str(trackdb.default_db_path()))
    try:
        return jobs_db.get_job(conn, job_id)
    finally:
        conn.close()


def test_an_rl_job_is_claimed_followed_by_its_markers_and_finished_with_its_result(monkeypatch):
    def fake_run(config, store=None, db_path=None, job_id=None, **kw):
        print("[RL-DATA] 1200 dates")
        print("[RL-TRAIN] pli 1/2 : entraînement")
        print("[RL-PROGRESS] 1/4")
        print("[RL-EVAL] pli 1/2")
        print("[RL-PROGRESS] 4/4")
        print("[RL-SAVE] écriture")
        return {"kind": "rl", "name": config.name, "strategy": {"sharpe": np.float64(0.7), "cagr": float("nan")}, "n_folds": np.int64(2)}

    monkeypatch.setattr(rl_run, "run_rl", fake_run)
    job = _run_and_read(_enqueue(_config()))
    assert job["status"] == "done", job
    assert job["progress_total"] == 4 and job["progress_done"] == 4
    assert job["phase"] == "rl_save"
    result = json.loads(job["result_json"])
    assert result["strategy"] == {"sharpe": 0.7, "cagr": None} and result["n_folds"] == 2
    assert "[RL-TRAIN] pli 1/2" in " ".join(json.loads(job["log_tail"]) if isinstance(job["log_tail"], str) else job["log_tail"])


def test_a_failing_rl_job_is_recorded_as_an_error_with_its_message_and_the_worker_goes_on(monkeypatch):
    def boom(config, **kw):
        raise agents.RLUnavailableError("Reinforcement learning indisponible : torch non installé.")

    monkeypatch.setattr(rl_run, "run_rl", boom)
    first = _enqueue(_config())
    second = _enqueue(_config(algo="A2C"))
    worker_module.run_worker_loop(poll_interval=0.1, idle_timeout=1.0)
    conn = trackdb.connect(str(trackdb.default_db_path()))
    try:
        jobs = [jobs_db.get_job(conn, j) for j in (first, second)]
    finally:
        conn.close()
    assert [j["status"] for j in jobs] == ["error", "error"]                      # le second job a bien été tenté malgré le premier échec
    assert "RLUnavailableError" in jobs[0]["error"] and "torch" in jobs[0]["error"]


def test_the_progress_capture_keeps_its_machine_learning_behaviour_by_default():
    capture = worker_module._ProgressCapture(conn=None, job_id="x", pid=1)
    assert capture._markers is worker_module._PHASE_MARKERS and capture._progress_re is None and capture._phase == "ingestion"
    rl = worker_module._ProgressCapture(conn=None, job_id="x", pid=1, phase_markers=worker_module._RL_PHASE_MARKERS,
                                        progress_pattern=worker_module._RL_PROGRESS_RE, first_phase="rl_data")
    assert rl._phase == "rl_data" and worker_module._RL_PROGRESS_RE.search("[RL-PROGRESS] 3/8").group(1) == "3"
