"""Pause, suppression, arrêt du PC : un run interrompu repart, il ne reste pas « en cours » pour toujours.

Constat du 2026-10-23 (run ZO=F, PC redémarré en plein réglage Optuna) : le job restait « running » sans processus, l'interface affichait
« en cours » ou « en pause » un calcul mort, le run ne pouvait pas être supprimé (« Cannot delete a running run »), et rien ne relançait
un worker tant qu'on ne soumettait pas un nouveau job -- qui, alors, marquait l'ancien en erreur au lieu de le reprendre.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import numpy as np
import optuna
import pytest
from fastapi.testclient import TestClient

from patrick import worker as worker_module
from patrick.pipeline import engine, pause
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.tuning.optuna_runner import tune_config
from patrick.webapp import run_manager
from patrick.webapp.app import app


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(run_manager, "_last_recovery", 0.0)
    monkeypatch.delenv("PATRICK_NO_AUTO_WORKER", raising=False)     # ces tests vérifient justement le lancement du worker (`_spawn_worker` simulé)
    trackdb.connect(path).close()
    return path


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _job(conn, job_id: str, pid: int | None, *, hours_ago: float = 0.2, status: str = "running", resume_count: int = 0,
         paused: bool = False) -> None:
    with conn:
        conn.execute(
            "INSERT INTO job (job_id, config_json, status, created_at, started_at, worker_pid, pause_requested, resume_count, phase) "
            "VALUES (?, ?, ?, datetime('now', ?), datetime('now', ?), ?, ?, ?, 'tuning')",
            (job_id, json.dumps({"name": job_id}), status, f"-{hours_ago + 0.1} hours", f"-{hours_ago} hours", pid, int(paused), resume_count),
        )


def _run(conn, run_id: str, job_id: str | None, *, status: str = "running", snapshot: str = "snapA") -> None:
    trackdb.upsert_snapshot(conn, snapshot, "h", None, None, None)
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, started_at, status, target, horizon, snapshot_id, config_json, config_hash, git_sha, seed, "
            "lib_versions, job_id) VALUES (?, datetime('now', '-0.2 hours'), ?, '^T', 1, ?, '{}', 'c', 's', 42, '{}', ?)",
            (run_id, status, snapshot, job_id),
        )


def _row(conn, sql: str, *args):
    return conn.execute(sql, args).fetchone()


# ---------------------------------------------------------------- un numéro de processus n'est pas un worker

def test_a_live_process_created_before_the_job_was_claimed_is_the_worker():
    claimed = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 5))
    assert jobs_db.worker_process_alive(os.getpid(), claimed)
    assert jobs_db.worker_process_alive(os.getpid())                      # sans heure : pid_alive seul


def test_a_process_created_after_the_job_was_claimed_is_not_the_worker():
    """Le numéro du worker mort a été réattribué à un autre programme (cas normal après un redémarrage de Windows)."""
    long_ago = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 7 * 86400))
    assert jobs_db.pid_alive(os.getpid()) and not jobs_db.worker_process_alive(os.getpid(), long_ago)


def test_a_machine_restarted_after_the_job_was_claimed_means_a_dead_worker(monkeypatch):
    claimed = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 3600))
    monkeypatch.setattr(jobs_db.psutil, "boot_time", lambda: time.time() - 60)       # redémarré il y a une minute
    assert not jobs_db.worker_process_alive(os.getpid(), claimed)


def test_a_dead_or_missing_pid_is_never_the_worker():
    assert not jobs_db.worker_process_alive(_dead_pid(), "2026-10-23 10:00:00")
    assert not jobs_db.worker_process_alive(None, "2026-10-23 10:00:00")


# ---------------------------------------------------------------- remise en file

def test_a_job_left_running_by_a_dead_worker_is_requeued_not_failed(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid(), paused=True)
    _run(conn, "zo_run", "zo")
    before = _row(conn, "SELECT created_at FROM job WHERE job_id = 'zo'")[0]

    out = jobs_db.recover_interrupted_jobs(conn)

    assert out == {"requeued": ["zo"], "failed": []}
    job = jobs_db.get_job(conn, "zo")
    assert job["status"] == "queued" and job["resume_count"] == 1 and job["worker_pid"] is None
    assert job["pause_requested"] == 0 and job["started_at"] is None and job["created_at"] == before
    assert job["error"] is None and "REPRISE" in job["log_tail"][0]
    run = _row(conn, "SELECT status, error FROM run WHERE run_id = 'zo_run'")
    assert run == ("failed", jobs_db.INTERRUPTED_RUN_ERROR)
    assert jobs_db.recover_interrupted_jobs(conn) == {"requeued": [], "failed": []}      # idempotent
    conn.close()


def test_the_requeued_job_keeps_its_place_before_the_jobs_created_after_it(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "old", _dead_pid(), hours_ago=2)
    _job(conn, "later", None, hours_ago=0.5, status="queued")
    jobs_db.recover_interrupted_jobs(conn)
    claimed = jobs_db.claim_next_job(conn, os.getpid())
    assert claimed["job_id"] == "old" and claimed["resume_count"] == 1
    conn.close()


def test_a_live_worker_is_never_interrupted_however_old_its_job(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "live", os.getpid(), hours_ago=0.01)
    monkeypatch.setattr(jobs_db, "worker_process_alive", lambda pid, started_at=None: True)
    assert jobs_db.recover_interrupted_jobs(conn) == {"requeued": [], "failed": []}
    assert jobs_db.get_job(conn, "live")["status"] == "running"
    conn.close()


def test_a_job_that_kills_its_worker_every_time_is_abandoned_after_the_automatic_resumptions(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "loop", _dead_pid(), resume_count=jobs_db.MAX_AUTO_RESUMES)
    _run(conn, "loop_run", "loop")
    assert jobs_db.recover_interrupted_jobs(conn) == {"requeued": [], "failed": ["loop"]}
    job = jobs_db.get_job(conn, "loop")
    assert job["status"] == "error" and "abandoned" in job["error"] and job["finished_at"]
    assert _row(conn, "SELECT status FROM run WHERE run_id = 'loop_run'")[0] == "failed"
    conn.close()


def test_the_worker_requeues_at_startup_then_runs_the_resumed_job(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    conn.close()
    seen = []

    def fake_run(conn, job, pid):
        seen.append((job["job_id"], job["resume_count"]))
        jobs_db.finish_job(conn, job["job_id"], "done")

    monkeypatch.setattr(worker_module, "_run_one_job", fake_run)
    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)
    assert seen == [("zo", 1)]
    conn = trackdb.connect(db_path)
    assert jobs_db.get_job(conn, "zo")["status"] == "done"
    conn.close()


def test_a_resumption_replays_the_snapshot_of_the_interrupted_run(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    _run(conn, "zo_run", "zo", snapshot="snapOLD")
    jobs_db.recover_interrupted_jobs(conn)
    assert worker_module._resume_snapshot(conn, "zo", 1) == "snapOLD"
    assert worker_module._resume_snapshot(conn, "zo", 0) is None                  # premier lancement : données du jour
    assert worker_module._resume_snapshot(conn, "other", 1) is None
    conn.close()


def test_a_resumption_whose_snapshot_left_the_store_restarts_on_todays_data(monkeypatch):
    calls = []

    def fake_pipeline(config, store=None, db_path=None, job_id=None, snapshot_id=None):
        calls.append(snapshot_id)
        if snapshot_id is not None:
            raise FileNotFoundError("Snapshot introuvable")
        return {"ok": True}

    monkeypatch.setattr(worker_module, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(worker_module, "DataStore", lambda: None)
    assert worker_module._run_pipeline_for_job(object(), "j", "snapX") == {"ok": True}
    assert calls == ["snapX", None]
    calls.clear()

    def always_missing(config, store=None, db_path=None, job_id=None, snapshot_id=None):
        calls.append(snapshot_id)
        raise FileNotFoundError("autre fichier manquant")

    monkeypatch.setattr(worker_module, "run_pipeline", always_missing)
    with pytest.raises(FileNotFoundError):                                          # lancement normal : l'erreur reste une erreur
        worker_module._run_pipeline_for_job(object(), "j", None)
    assert calls == [None]


def test_a_queued_job_with_an_invalid_config_fails_the_job_not_the_worker(db_path):
    conn = trackdb.connect(db_path)
    jobs_db.enqueue_job(conn, json.dumps({"name": "broken"}))
    conn.close()
    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)           # ne lève plus
    conn = trackdb.connect(db_path)
    status, error = _row(conn, "SELECT status, error FROM job")
    conn.close()
    assert status == "error" and "ValidationError" in error


# ---------------------------------------------------------------- runs orphelins et suppression

def test_the_runs_of_a_job_that_is_no_longer_running_are_closed_at_once(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "done_job", None, status="error")
    _run(conn, "r_of_error_job", "done_job")
    _run(conn, "r_without_job_recent", None)                                        # lancé en ligne de commande : délai conservé
    assert trackdb.reap_orphaned_runs(conn) == 1
    assert _row(conn, "SELECT status FROM run WHERE run_id = 'r_of_error_job'")[0] == "failed"
    assert _row(conn, "SELECT status FROM run WHERE run_id = 'r_without_job_recent'")[0] == "running"
    conn.close()


def test_a_pipeline_exception_closes_the_runs_of_its_job(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "boom", os.getpid())
    _run(conn, "boom_run", "boom")
    jobs_db.finish_job(conn, "boom", "error", error="ValueError: boom")
    assert _row(conn, "SELECT status, error FROM run WHERE run_id = 'boom_run'") == ("failed", "ValueError: boom")
    conn.close()


def test_a_zombie_run_of_a_dead_worker_can_be_deleted_from_the_history(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    _run(conn, "zo_run", "zo")
    conn.close()
    response = TestClient(app).post("/runs/zo_run/delete", follow_redirects=False)
    assert response.status_code == 303, response.text
    conn = trackdb.connect(db_path)
    assert _row(conn, "SELECT COUNT(*) FROM run WHERE run_id = 'zo_run'")[0] == 0
    conn.close()


def test_a_run_really_in_progress_still_cannot_be_deleted(db_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "worker_process_alive", lambda pid, started_at=None: True)
    conn = trackdb.connect(db_path)
    _job(conn, "live", os.getpid())
    _run(conn, "live_run", "live")
    conn.close()
    assert TestClient(app).post("/runs/live_run/delete", follow_redirects=False).status_code == 409


# ---------------------------------------------------------------- le serveur voit le worker disparu

def test_the_run_state_poll_requeues_the_dead_job_and_relaunches_a_worker(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    conn.close()
    spawned = []
    monkeypatch.setattr(run_manager, "_spawn_worker", spawned.append)

    state = TestClient(app).get("/api/run-state").json()

    assert state["active_run"] is None and [q["id"] for q in state["queue"]] == ["zo"]
    assert len(spawned) == 1


def test_recovery_is_throttled_and_does_not_double_the_worker(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    conn.close()
    spawned = []
    monkeypatch.setattr(run_manager, "_spawn_worker", spawned.append)
    run_manager.recover_interrupted_runs()
    run_manager.recover_interrupted_runs()                                           # < 5 s : sans effet
    run_manager.recover_interrupted_runs(force=True)                                 # worker déjà réservé (pouls) : pas de doublon
    assert len(spawned) == 1


def test_nothing_is_launched_when_there_is_nothing_to_resume(db_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(run_manager, "_spawn_worker", spawned.append)
    assert run_manager.recover_interrupted_runs(force=True) == {"requeued": [], "failed": []}
    assert spawned == []


def test_the_server_recovers_at_startup(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    conn.close()
    spawned = []
    monkeypatch.setattr(run_manager, "_spawn_worker", spawned.append)
    monkeypatch.setenv("PATRICK_BACKGROUND_DELAY_S", "3600")
    with TestClient(app):                                                            # exécute l'événement de démarrage
        pass
    conn = trackdb.connect(db_path)
    assert jobs_db.get_job(conn, "zo")["status"] == "queued" and len(spawned) == 1
    conn.close()


def test_pausing_a_job_whose_worker_is_gone_requeues_it_instead_of_showing_paused(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", _dead_pid())
    conn.close()
    monkeypatch.setattr(run_manager, "_spawn_worker", lambda timeout: None)
    response = TestClient(app).post("/api/jobs/zo/pause")
    assert response.status_code == 409
    conn = trackdb.connect(db_path)
    job = jobs_db.get_job(conn, "zo")
    conn.close()
    assert job["status"] == "queued" and job["pause_requested"] == 0


def test_stop_never_kills_a_process_that_only_reuses_the_workers_number(db_path, monkeypatch):
    conn = trackdb.connect(db_path)
    _job(conn, "zo", os.getpid())                                                    # le numéro existe : c'est le navigateur, pas le worker
    conn.close()
    monkeypatch.setattr(jobs_db, "worker_process_alive", lambda pid, started_at=None: False)
    killed = []
    monkeypatch.setattr(run_manager, "_terminate_worker", killed.append)
    monkeypatch.setattr(run_manager, "ensure_worker_running", lambda: None)
    assert TestClient(app).post("/api/jobs/zo/stop").status_code == 200
    assert killed == []
    conn = trackdb.connect(db_path)
    assert jobs_db.get_job(conn, "zo")["error"] == "Stopped by user."
    conn.close()


# ---------------------------------------------------------------- la pause prend effet même sans ligne affichée

def test_the_pause_gate_blocks_until_the_pause_is_lifted(db_path):
    conn = trackdb.connect(db_path)
    _job(conn, "j", os.getpid(), paused=True)
    done = threading.Event()

    def compute() -> None:                                  # la connexion du worker vit dans le fil qui calcule
        own = trackdb.connect(db_path)
        worker_module._pause_gate(own, "j")()
        done.set()
        own.close()

    thread = threading.Thread(target=compute, daemon=True)
    thread.start()
    time.sleep(0.8)
    assert not done.is_set(), "la pause n'a pas arrêté le calcul"
    jobs_db.set_job_paused(conn, "j", False)
    thread.join(timeout=5)
    assert done.is_set()
    conn.close()


def test_the_checkpoint_is_a_no_op_without_a_hook_and_calls_the_hook_otherwise():
    pause.set_hook(None)
    pause.checkpoint()
    calls = []
    pause.set_hook(lambda: calls.append(1))
    try:
        pause.checkpoint()
        pause.checkpoint()
    finally:
        pause.set_hook(None)
    assert calls == [1, 1]


def test_every_model_fit_and_every_optuna_fold_is_a_pause_point(monkeypatch):
    rng = np.random.default_rng(0)
    X, y = rng.normal(size=(240, 4)), rng.integers(0, 4, size=240)
    calls = []
    monkeypatch.setattr(pause, "checkpoint", lambda: calls.append(1))
    engine._fit_eval_full(X[:160], y[:160], X[160:], y[160:], "none", "XGBoost", 1, n_estimators=5)
    fit_calls = len(calls)
    assert fit_calls >= 1
    tune_config(X, y, "XGBoost", "none", n_trials=2, cv_splits=2, seed=1, horizon=1)
    assert len(calls) >= fit_calls + 2 * 2                                            # 2 essais x 2 plis


def test_an_optuna_trial_left_running_by_a_killed_process_does_not_eat_the_resumed_budget(tmp_path):
    rng = np.random.default_rng(0)
    X, y = rng.normal(size=(240, 4)), rng.integers(0, 4, size=240)
    storage = str(tmp_path / "optuna.db")
    study = optuna.create_study(direction="maximize", storage=f"sqlite:///{storage}", study_name="s", load_if_exists=True)
    study.ask()                                                                       # un essai commencé, jamais fini : processus tué
    tune_config(X, y, "XGBoost", "none", n_trials=3, cv_splits=2, seed=1, horizon=1, storage_path=storage, study_name="s")
    study = optuna.load_study(study_name="s", storage=f"sqlite:///{storage}")
    states = [t.state for t in study.trials]
    assert optuna.trial.TrialState.RUNNING not in states
    assert states.count(optuna.trial.TrialState.FAIL) == 1
    done = states.count(optuna.trial.TrialState.COMPLETE) + states.count(optuna.trial.TrialState.PRUNED)
    assert done == 3


# ---------------------------------------------------------------- bout en bout (lent) : un worker « tué » en plein réglage, puis la reprise

@pytest.mark.slow
def test_a_worker_killed_during_tuning_is_resumed_and_the_job_completes(db_path, tmp_path, monkeypatch):
    import pandas as pd

    from patrick.config.schema import RunConfig

    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=1500)
    raw = pd.DataFrame({"IDX_TEST": 15 + np.cumsum(rng.normal(0, 0.5, 1500))}, index=idx)
    raw["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, 1500))
    raw["NFCI"] = np.cumsum(rng.normal(0, 0.02, 1500))
    config = RunConfig.model_validate({
        "name": "kill_resume", "objective": {"target_symbol": "^TEST", "horizons": [3], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI"}, "start_date": "2015-01-01"},
        "features": {"families": ["technical", "macro"], "pool_prefilter": 40},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 100},
        "sampler": {"candidates": ["SMOTE"]}, "models": {"algos": ["XGBoost", "LightGBM"]},
        "tuning": {"enabled": True, "top_k": 1, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    })
    monkeypatch.setattr(engine, "ingest", lambda *a, **k: raw)
    conn = trackdb.connect(db_path)
    job_id = jobs_db.enqueue_job(conn, config.model_dump_json())
    conn.close()

    real_tune = engine._tune_one

    def killed(*args, **kwargs):
        raise SystemExit("simulated kill (PC switched off)")

    monkeypatch.setattr(engine, "_tune_one", killed)
    with pytest.raises(SystemExit):
        worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)
    conn = trackdb.connect(db_path)
    assert jobs_db.get_job(conn, job_id)["status"] == "running"                       # exactement l'état laissé par l'arrêt du PC
    assert _row(conn, "SELECT status FROM run")[0] == "running"
    conn.close()

    monkeypatch.setattr(engine, "_tune_one", real_tune)
    monkeypatch.setattr(jobs_db, "worker_process_alive", lambda pid, started_at=None: False)   # le processus d'avant n'existe plus
    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    conn = trackdb.connect(db_path)
    job = jobs_db.get_job(conn, job_id)
    runs = conn.execute("SELECT status, error FROM run ORDER BY started_at, rowid").fetchall()
    conn.close()
    assert job["status"] == "done" and job["resume_count"] == 1, job["error"]
    assert runs[0] == ("failed", jobs_db.INTERRUPTED_RUN_ERROR)                       # l'essai interrompu est refermé...
    assert runs[-1][0] == "done"                                                      # ... et la reprise a mené le run au bout
