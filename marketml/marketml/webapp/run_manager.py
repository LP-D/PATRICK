"""État et exécution en arrière-plan des runs `marketml` déclenchés depuis
l'interface web. `run_pipeline` est synchrone, bloquant, et ne communique sa
progression que via `print()` (pas de callback/logger exposé côté moteur) —
on l'exécute dans un thread et on capture stdout pour en tirer logs +
progression, sans toucher à `marketml.pipeline.engine`.

Un seul run actif à la fois : `sys.stdout` est un objet global du process,
donc capturer stdout par thread n'est fiable que si les runs ne se chevauchent
pas (cf. plan). C'est une contrainte assumée pour cet outil local mono-
utilisateur, pas un oubli.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from marketml.config.schema import RunConfig
from marketml.data.store import DataStore
from marketml.pipeline.engine import run_pipeline

_FOLD_LINE_RE = re.compile(r"lignes cumulées")
_FOLD_LINE_NUM_RE = re.compile(r":\s*(\d+)\s*lignes")

_PHASE_MARKERS = [
    ("[FEATURES]", "features"),
    ("[SCAN]", "scan"),
    ("[BEST avant Optuna]", "scan"),
    ("[OPTUNA]", "tuning"),
    ("[EXPORT]", "export"),
]


@dataclass
class RunState:
    id: str
    config: RunConfig
    status: str = "running"  # running | done | error
    phase: str = "ingestion"
    log_lines: deque = field(default_factory=lambda: deque(maxlen=500))
    progress_done: int = 0
    progress_total: int = 1
    result: dict | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "status": self.status,
                "phase": self.phase,
                "progress": {"done": self.progress_done, "total": self.progress_total},
                "log_tail": list(self.log_lines)[-200:],
                "error": self.error,
                "elapsed_s": (self.finished_at or time.time()) - self.started_at,
            }


class _TeeCapture:
    """Redirige stdout : écrit vers la vraie console + alimente `state`."""

    def __init__(self, state: RunState):
        self._state = state
        self._buffer = ""

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
        with self._state.lock:
            self._state.log_lines.append(line)
            for marker, phase in _PHASE_MARKERS:
                if marker in line:
                    self._state.phase = phase
                    break
            if _FOLD_LINE_RE.search(line):
                m = _FOLD_LINE_NUM_RE.search(line)
                if m:
                    n = int(m.group(1))
                    self._state.progress_done = max(self._state.progress_done, n)


_RUNS: dict[str, RunState] = {}
_RUNS_LOCK = threading.Lock()


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


def active_run() -> RunState | None:
    with _RUNS_LOCK:
        for state in _RUNS.values():
            if state.status == "running":
                return state
    return None


def get_run(run_id: str) -> RunState | None:
    return _RUNS.get(run_id)


def start_run(config: RunConfig) -> RunState:
    if active_run() is not None:
        raise RuntimeError("Un run est déjà en cours — attends qu'il se termine.")

    run_id = uuid.uuid4().hex[:12]
    state = RunState(id=run_id, config=config, progress_total=_estimate_total(config))
    with _RUNS_LOCK:
        _RUNS[run_id] = state

    thread = threading.Thread(target=_run_worker, args=(state,), daemon=True)
    thread.start()
    return state


def _run_worker(state: RunState) -> None:
    capture = _TeeCapture(state)
    try:
        result = _run_with_stdout_captured(state.config, capture)
        with state.lock:
            state.result = _summarize_result(state.config, result)
            state.status = "done"
            state.phase = "done"
            state.progress_done = state.progress_total
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
        with state.lock:
            state.status = "error"
            state.error = f"{type(exc).__name__}: {exc}"
    finally:
        with state.lock:
            state.finished_at = time.time()


def _run_with_stdout_captured(config: RunConfig, capture: _TeeCapture) -> dict:
    old_stdout = sys.stdout
    sys.stdout = capture
    try:
        return run_pipeline(config, store=DataStore())
    finally:
        sys.stdout = old_stdout


def _to_native(obj):
    """Convertit récursivement numpy.int64/float64/bool_/NaN (issus des
    DataFrames pandas) en types Python natifs, JSON-sérialisables par FastAPI."""
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
    """Construit un résumé JSON-sérialisable + la liste des artefacts exportés
    (retrouvés par convention de nommage, cf. `pipeline/leaderboard.py` et
    `tracking/export.py` — `run_pipeline` ne renvoie pas ces chemins
    directement, sauf `model_path`)."""
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
    })
