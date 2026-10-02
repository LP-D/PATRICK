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

import faulthandler
import json
import os
import re
import sqlite3
import sys
import threading
import time
import traceback

import numpy as np

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.keep_awake import keep_awake
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

# The web server spawns the worker with stdout/stderr on DEVNULL
# (`run_manager._spawn_worker`): without its own log file, a worker that dies
# takes its traceback with it (2026-09-27: job GSPC_61 left 'running' by a
# worker that vanished without a trace). One file per worker process, in
# `logs/` next to the tracking DB; only the most recent ones are kept.
_WORKER_LOGS_KEPT = 20

# Heartbeat period of the dedicated thread, well under
# `jobs.HEARTBEAT_STALE_S` (30s). It used to be refreshed only when the
# pipeline printed a line: during a silent phase of more than 30s
# (holdout diagnostic), the web server took the live worker for dead and
# spawned a second one (2026-09-27, GSPC_62).
_HEARTBEAT_INTERVAL_S = 5.0


class _HeartbeatThread(threading.Thread):
    """Keeps the worker's heartbeat fresh whatever the pipeline is doing.
    Own SQLite connection: a connection is not shared across threads."""

    def __init__(self, db_path: str, pid: int):
        super().__init__(name="patrick-worker-heartbeat", daemon=True)
        self._db_path = db_path
        self._pid = pid
        self._stopped = threading.Event()

    def run(self) -> None:
        conn = trackdb.connect(self._db_path)
        try:
            while not self._stopped.wait(_HEARTBEAT_INTERVAL_S):
                try:
                    jobs_db.write_heartbeat(conn, self._pid)
                except sqlite3.Error as exc:
                    print(f"[WORKER] heartbeat not written: {exc}", file=sys.stderr)
        finally:
            conn.close()

    def stop(self) -> None:
        self._stopped.set()
        self.join(timeout=10)


class _Tee:
    """Duplicates a stream into the worker log file. The original stream may
    be DEVNULL (spawned worker) or a real console (`patrick worker` run by
    hand): its failures never prevent writing the log."""

    def __init__(self, stream, log):
        self._stream = stream
        self._log = log

    def write(self, text: str) -> int:
        if self._stream is not None:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
        self._log.write(text)
        self._log.flush()
        return len(text)

    def flush(self) -> None:
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass
        self._log.flush()

    def __getattr__(self, name):
        return getattr(self._stream if self._stream is not None else self._log, name)


def _open_worker_log(db_path: str, pid: int):
    log_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    olds = sorted(n for n in os.listdir(log_dir) if n.startswith("worker-") and n.endswith(".log"))
    for name in olds[: max(len(olds) - (_WORKER_LOGS_KEPT - 1), 0)]:
        try:
            os.remove(os.path.join(log_dir, name))
        except OSError:
            pass
    path = os.path.join(log_dir, f"worker-{time.strftime('%Y%m%d-%H%M%S')}-{pid}.log")
    return open(path, "a", encoding="utf-8", buffering=1)  # closed in run_worker_loop's finally


def _estimate_total(config: RunConfig) -> int:
    """Scan fits the progress bar and the ETA divide by. Exhaustive: every
    candidate on every fold. Staged screening: every candidate on fold 1,
    then only the finalists (per horizon and regime) on the other folds.
    Total-window screening: every candidate once on the whole out-of-sample
    window, then only the finalists on every fold."""
    candidates = len(config.selection.n_features_grid) * len(config.sampler.candidates) * len(config.models.algos)
    folds = config.validation.n_wf_folds
    finalists = min(config.selection.screening_finalists_per_group, candidates)
    if config.selection.screening_mode == "total_window":
        per_group = candidates + finalists * folds        # one fit per candidate, then the finalists on every fold
    elif config.selection.screening_mode == "staged" and folds > 1:
        per_group = candidates + finalists * (folds - 1)
    else:
        per_group = candidates * folds
    return max(len(config.objective.horizons) * len(config.objective.regimes) * per_group, 1)


class _ProgressCapture:
    """Redirects stdout to the worker's output + persists progress/logs to
    the database. It also refreshes the heartbeat, but only when the
    pipeline prints: silent phases are covered by `_HeartbeatThread`."""

    def __init__(self, conn, job_id: str, pid: int):
        self._conn = conn
        self._job_id = job_id
        self._pid = pid
        # The stream in place before the capture (the worker log's tee), not
        # `sys.__stdout__`, so that the pipeline output also reaches the log.
        self._out = sys.stdout
        self._buffer = ""
        self._log_lines: list[str] = []
        self._phase = "ingestion"
        self._progress_done = 0
        self._last_flush = 0.0

    def write(self, text: str) -> int:
        self._out.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._handle_line(line)
        return len(text)

    def flush(self) -> None:
        self._out.flush()

    def _handle_line(self, line: str) -> None:
        while jobs_db.pause_requested(self._conn, self._job_id):
            time.sleep(0.5)
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
        try:
            jobs_db.update_job_progress(
                self._conn, self._job_id, phase=self._phase,
                progress_done=self._progress_done, log_tail=self._log_lines[-200:],
            )
            jobs_db.write_heartbeat(self._conn, self._pid)
        except sqlite3.Error as exc:
            # Progress display only: a busy database must not abort a
            # multi-hour run (2026-09-27: a "database is locked" here killed
            # two workers mid-run). The next flush retries.
            self._out.write(f"[WORKER] progress not saved ({exc}), will retry\n")

    def final_flush(self) -> None:
        self._flush(time.monotonic())


def _to_native(obj):
    """Recursively converts numpy.int64/float64/bool_/NaN/±inf (from pandas
    DataFrames) into native, STRICT-JSON-serializable Python types: ±inf
    (e.g. a Diebold-Mariano statistic on a constant nonzero loss
    differential) would otherwise be written as `Infinity`, which the
    browser's `JSON.parse` rejects."""
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
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
    # Fix report [per-horizon export]: `run_pipeline` now exports one model
    # per horizon with a valid result (`result["model_paths"]`), not just
    # `model_path` (kept above, unchanged, for backward compatibility --
    # still the global winner's own file). Exposed here under per-horizon
    # keys so a multi-horizon run's OTHER horizons are downloadable too,
    # through the same generic `/runs/{run_id}/download/{artifact}` route
    # (no new route needed, `download_artifact` already looks artifacts up
    # by key).
    for horizon, h_model_path in (result.get("model_paths") or {}).items():
        if h_model_path == model_path:
            continue  # already exposed as "best_model" above, avoid a duplicate download link
        _add(f"best_model_h{horizon}", h_model_path)
        _add(f"best_model_meta_h{horizon}", h_model_path[: -len(".joblib")] + "_meta.json")

    top_rows = []
    if len(leaderboard_df):
        top_rows = (
            leaderboard_df.sort_values("F1_dir", ascending=False, kind="mergesort")
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
        "champions": {str(h): d for h, d in (result.get("champions") or {}).items()},
        "kpi_summary": result.get("kpi_summary"),
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
        with keep_awake():
            result = run_pipeline(config, store=DataStore(), db_path=trackdb.default_db_path(), job_id=job_id)
    except Exception as exc:  # noqa: BLE001 -- job boundary: any pipeline failure is recorded on the job, the worker keeps running
        sys.stdout = old_stdout
        traceback.print_exc()  # full traceback in the worker log; the job only keeps the message
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
    the next submission).

    Everything the worker prints -- and its traceback if it dies -- also goes
    to its own log file (`logs/` next to the DB, see `_open_worker_log`). An
    abrupt end of that file, without the final `[WORKER] exit` line, means
    the process was killed from outside."""
    pid = os.getpid()
    db_path = trackdb.default_db_path()
    log = _open_worker_log(db_path, pid)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    faulthandler_was_enabled = faulthandler.is_enabled()
    sys.stdout, sys.stderr = _Tee(old_stdout, log), _Tee(old_stderr, log)
    faulthandler.enable(file=log, all_threads=True)  # native crashes (C extensions) too
    heartbeat = _HeartbeatThread(db_path, pid)
    heartbeat.start()
    try:
        _worker_loop(pid, db_path, poll_interval, idle_timeout)
    except BaseException:
        log.write(f"[WORKER] died (pid={pid}):\n{traceback.format_exc()}")
        raise
    finally:
        heartbeat.stop()
        log.write(f"[WORKER] exit (pid={pid}) {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        sys.stdout, sys.stderr = old_stdout, old_stderr
        faulthandler.disable()
        if faulthandler_was_enabled:
            try:
                faulthandler.enable(file=sys.__stderr__)
            except (AttributeError, OSError, ValueError):
                pass
        log.close()


def _worker_loop(pid: int, db_path: str, poll_interval: float, idle_timeout: float) -> None:
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
        print(f"[WORKER] job {job['job_id']} claimed")
        _run_one_job(conn, job, pid)
        finished = jobs_db.get_job(conn, job["job_id"]) or {}
        print(f"[WORKER] job {job['job_id']} finished: {finished.get('status')}")
