"""`patrick` worker (Phase 3.1): a separate process that consumes the SQLite
job queue (`job`, see `tracking/jobs.py`) in a loop and runs `run_pipeline`.

Replaces execution in a thread internal to the web process (BackgroundTasks-
like, the old `webapp/run_manager.py`): killing the web process during a run
no longer loses the run, this worker (a separate process, sharing nothing
with the web process besides the SQLite database) finishes it. Automatically
relaunched by `run_manager.ensure_worker_running` on the next submission if
it's absent/dead; stops on its own after `idle_timeout` seconds with no job
to process (local single-user tool: no ghost process running forever for
nothing).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import numpy as np

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db

_FOLD_LINE_RE = re.compile(r"cumulative rows")
_FOLD_LINE_NUM_RE = re.compile(r":\s*(\d+)\s*cumulative")

_PHASE_MARKERS = [
    ("[FEATURES]", "features"),
    ("[SCAN]", "scan"),
    ("[BEST before Optuna]", "scan"),
    ("[OPTUNA]", "tuning"),
    ("[EXPORT]", "export"),
]

# Throttled DB writes: `run_pipeline` prints far more than one line per
# second (one per fold/trial), well beyond what's useful on the UI side, and
# every write is a SQLite transaction.
_FLUSH_THROTTLE_S = 1.0


def _estimate_total(config: RunConfig) -> int:
    total = (
        len(config.objective.horizons)
        * config.validation.n_wf_folds
        * len(config.objective.regimes)
        * len(config.selection.n_features_grid)
        * len(config.sampler.candidates)
        * len(config.models.algos)
    )
    return max(total, 1)


class _ProgressCapture:
    """Redirects stdout to the real console + persists progress/logs to the
    database. Also serves as a heartbeat during a run's execution: without
    this, a long run (several minutes between two `run_worker_loop`
    iterations) would let the heartbeat go stale and
    `ensure_worker_running` would believe this worker dead while it's
    working."""

    def __init__(self, conn, job_id: str, pid: int):
        self._conn = conn
        self._job_id = job_id
        self._pid = pid
        self._buffer = ""
        self._log_lines: list[str] = []
        self._phase = "ingestion"
        self._progress_done = 0
        self._last_flush = 0.0

    def write(self, text: str) -> int:
        sys.__stdout__.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._handle_line(line)
        return len(text)

    def flush(self) -> None:
        sys.__stdout__.flush()

    def _handle_line(self, line: str) -> None:
        self._log_lines.append(line)
        for marker, phase in _PHASE_MARKERS:
            if marker in line:
                self._phase = phase
                break
        if _FOLD_LINE_RE.search(line):
            m = _FOLD_LINE_NUM_RE.search(line)
            if m:
                self._progress_done = max(self._progress_done, int(m.group(1)))
        now = time.monotonic()
        if now - self._last_flush >= _FLUSH_THROTTLE_S:
            self._flush(now)

    def _flush(self, now: float) -> None:
        self._last_flush = now
        jobs_db.update_job_progress(
            self._conn, self._job_id, phase=self._phase,
            progress_done=self._progress_done, log_tail=self._log_lines[-200:],
        )
        jobs_db.write_heartbeat(self._conn, self._pid)

    def final_flush(self) -> None:
        self._flush(time.monotonic())


def _to_native(obj):
    """Recursively converts numpy.int64/float64/bool_/NaN (from pandas
    DataFrames) into native, JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, np.generic):
        val = obj.item()
        return None if isinstance(val, float) and np.isnan(val) else val
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj


def _summarize_result(config: RunConfig, result: dict) -> dict:
    """Builds a JSON-serializable summary + the list of exported artifacts
    (found by naming convention, `run_pipeline` does not return these paths
    directly, except `model_path`)."""
    out_dir = config.output.dir
    name = config.name

    leaderboard_df = result["leaderboard"]
    tuned_df = result["tuned"]

    artifacts = {}

    def _add(key: str, path: str) -> None:
        if path and os.path.exists(path):
            artifacts[key] = path

    _add("leaderboard_csv", os.path.join(out_dir, f"{name}_leaderboard.csv"))
    _add("leaderboard_xlsx", os.path.join(out_dir, f"{name}_leaderboard.xlsx"))
    _add("tuned_csv", os.path.join(out_dir, f"{name}_tuned.csv"))
    model_path = result.get("model_path")
    if model_path:
        _add("best_model", model_path)
        _add("best_model_meta", model_path[: -len(".joblib")] + "_meta.json")

    top_rows = []
    if len(leaderboard_df):
        top_rows = (
            leaderboard_df.sort_values("F1_dir", ascending=False)
            .head(100)
            .to_dict(orient="records")
        )

    return _to_native({
        "n_evaluations": len(leaderboard_df),
        "n_tuned_evaluations": len(tuned_df),
        "top_rows": top_rows,
        "leaderboard_columns": list(leaderboard_df.columns) if len(leaderboard_df) else [],
        "best_before_tuning": result.get("best_before_tuning"),
        "final_best": result.get("final_best"),
        "elapsed_s": result.get("elapsed_s"),
        "artifacts": artifacts,
        "holdout": result.get("holdout"),
        "diebold_mariano": result.get("diebold_mariano"),
        "cumulative_trials": result.get("cumulative_trials"),
        "pbo": result.get("pbo"),
    })


def _run_one_job(conn, job: dict, pid: int) -> None:
    job_id = job["job_id"]
    config = RunConfig.model_validate(json.loads(job["config_json"]))
    jobs_db.update_job_progress(
        conn, job_id, phase="ingestion", progress_done=0,
        progress_total=_estimate_total(config), log_tail=[],
    )
    capture = _ProgressCapture(conn, job_id, pid)
    old_stdout = sys.stdout
    sys.stdout = capture
    try:
        result = run_pipeline(config, store=DataStore(), db_path=trackdb.default_db_path(), job_id=job_id)
    except Exception as exc:  # noqa: BLE001 - surfaced via job.error, never swallowed
        sys.stdout = old_stdout
        capture.final_flush()
        jobs_db.finish_job(conn, job_id, "error", error=f"{type(exc).__name__}: {exc}")
        return
    sys.stdout = old_stdout
    capture.final_flush()
    summary = _summarize_result(config, result)
    jobs_db.finish_job(conn, job_id, "done", result_json=json.dumps(summary))


def run_worker_loop(poll_interval: float = 1.0, idle_timeout: float = 600.0) -> None:
    """Main loop: claims the next queued job and runs it, in a loop, until
    `idle_timeout` seconds pass with no job available (the worker then
    stops on its own; `run_manager.ensure_worker_running` relaunches one on
    the next submission)."""
    pid = os.getpid()
    db_path = trackdb.default_db_path()
    conn = trackdb.connect(db_path)
    n_reaped = jobs_db.reap_stale_running_jobs(conn)
    if n_reaped:
        print(f"[WORKER] {n_reaped} 'running' job(s) abandoned by a previous worker -> error.")
    n_reaped_runs = trackdb.reap_orphaned_runs(conn)
    if n_reaped_runs:
        print(f"[WORKER] {n_reaped_runs} 'running' run(s) orphaned by a previous worker -> failed.")
    jobs_db.write_heartbeat(conn, pid)
    idle_since = time.monotonic()
    print(f"[WORKER] started (pid={pid}, db={db_path})")
    while True:
        job = jobs_db.claim_next_job(conn, pid)
        if job is None:
            jobs_db.write_heartbeat(conn, pid)
            if time.monotonic() - idle_since > idle_timeout:
                print(f"[WORKER] idle for {idle_timeout:.0f}s, stopping (pid={pid}).")
                return
            time.sleep(poll_interval)
            continue
        idle_since = time.monotonic()
        _run_one_job(conn, job, pid)
