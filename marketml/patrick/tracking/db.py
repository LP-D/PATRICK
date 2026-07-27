"""Persistance SQLite des runs (Phase 1) — une ligne par essai (`trial`), pas
seulement le vainqueur, pour permettre plus tard le calcul de validité
statistique (Sharpe déflaté, PBO — Phase 2) qui a besoin de savoir combien de
configurations ont réellement été testées.

Projet mono-utilisateur local : pas de Redis/Postgres/service — SQLite (WAL,
un fichier) + migrations SQL numérotées (pas d'Alembic, ce projet ne passe pas
par SQLAlchemy).
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from importlib import metadata as importlib_metadata
from pathlib import Path

DEFAULT_DB_PATH = os.path.expanduser("~/.patrick/patrick.db")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_TRACKED_LIBS = (
    "numpy", "pandas", "scikit-learn", "xgboost", "lightgbm", "catboost",
    "imbalanced-learn", "shap", "optuna", "pydantic", "arch", "pykalman", "hmmlearn",
)


def connect(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]

    scripts = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for script in scripts:
        version = int(script.name.split("_", 1)[0])
        if version <= current:
            continue
        sql = script.read_text()
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


def library_versions() -> str:
    """JSON {lib: version} des dépendances principales — cf. Phase 1.6
    (reproductibilité). `importlib.metadata` (stdlib) : pas de dépendance
    ajoutée juste pour ça."""
    versions = {"python": sys.version.split()[0]}
    for lib in _TRACKED_LIBS:
        try:
            versions[lib] = importlib_metadata.version(lib)
        except importlib_metadata.PackageNotFoundError:
            pass
    return json.dumps(versions, sort_keys=True)


def current_git_sha(cwd: str | None = None) -> str:
    """SHA git du HEAD courant — "unknown" (pas d'exception) si le run tourne
    hors d'un dépôt git ou sans binaire git disponible : la reproductibilité en
    pâtit mais ça ne doit jamais faire planter un run."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
            text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# CRUD — une fonction par table d'écriture, toutes idempotentes/explicites sur
# leurs paramètres plutôt que de prendre des dicts non typés.
# ---------------------------------------------------------------------------

def upsert_snapshot(conn: sqlite3.Connection, snapshot_id: str, data_hash: str,
                     n_tickers: int | None, n_fred_series: int | None,
                     fred_source: str | None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO snapshot (snapshot_id, created_at, data_hash, n_tickers, "
            "n_fred_series, fred_source) VALUES (?, datetime('now'), ?, ?, ?, ?) "
            "ON CONFLICT(snapshot_id) DO NOTHING",
            (snapshot_id, data_hash, n_tickers, n_fred_series, fred_source),
        )


def create_run(conn: sqlite3.Connection, run_id: str, target: str, horizon: int,
                snapshot_id: str, config_json: str, config_hash: str,
                git_sha: str, seed: int) -> None:
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, started_at, status, target, horizon, snapshot_id, "
            "config_json, config_hash, git_sha, seed, lib_versions) "
            "VALUES (?, datetime('now'), 'running', ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, target, horizon, snapshot_id, config_json, config_hash,
             git_sha, seed, library_versions()),
        )


def finish_run(conn: sqlite3.Connection, run_id: str, status: str,
                n_trials: int | None = None, error: str | None = None) -> None:
    with conn:
        conn.execute(
            "UPDATE run SET status = ?, finished_at = datetime('now'), n_trials = ?, "
            "error = ? WHERE run_id = ?",
            (status, n_trials, error, run_id),
        )


def create_trial(conn: sqlite3.Connection, run_id: str, regime: str, algo: str,
                  sampler: str, n_features: int, selector: str,
                  params_json: str = "{}") -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, "
            "params_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, regime, algo, sampler, n_features, selector, params_json),
        )
        return cur.lastrowid


def mark_best_trial(conn: sqlite3.Connection, trial_id: int, artifact_path: str | None = None) -> None:
    with conn:
        conn.execute("UPDATE trial SET is_best = 1, artifact_path = ? WHERE trial_id = ?",
                      (artifact_path, trial_id))


def add_fold_metrics(conn: sqlite3.Connection, trial_id: int, fold_index: int,
                      split: str, metrics: dict) -> None:
    rows = [(trial_id, fold_index, split, name, float(value))
            for name, value in metrics.items() if value is not None and value == value]  # exclut NaN
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fold_metric (trial_id, fold_index, split, metric, value) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def add_baseline_metrics(conn: sqlite3.Connection, run_id: str, baseline: str,
                          split: str, metrics: dict) -> None:
    rows = [(run_id, baseline, split, name, float(value))
            for name, value in metrics.items() if value is not None and value == value]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO baseline_metric (run_id, baseline, split, metric, value) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def add_predictions(conn: sqlite3.Connection, trial_id: int, fold_index: int, split: str,
                     ts: list[str], y_true, y_pred, y_proba=None) -> None:
    proba = y_proba if y_proba is not None else [None] * len(ts)
    rows = [(trial_id, str(t), fold_index, split, float(yt), float(yp),
              float(yp_proba) if yp_proba is not None else None)
            for t, yt, yp, yp_proba in zip(ts, y_true, y_pred, proba)]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prediction (trial_id, ts, fold_index, split, y_true, "
            "y_pred, y_proba) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
