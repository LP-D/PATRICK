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

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def default_db_path() -> str:
    """Lu depuis l'environnement à CHAQUE appel (pas une constante figée à
    l'import) : `patrick worker`, lancé en process séparé par
    `run_manager.ensure_worker_running`, doit partager la même base que le
    process web qui l'a fait naître (héritage d'environnement via
    `subprocess.Popen`) sans qu'il faille se passer le chemin en argument CLI
    — et les tests doivent pouvoir isoler chaque run sur un `tmp_path` en
    positionnant `PATRICK_DB_PATH` avant d'appeler `connect()`, ce qu'une
    valeur par défaut de paramètre (évaluée une seule fois à l'import du
    module) ne permettrait pas."""
    return os.environ.get("PATRICK_DB_PATH") or os.path.expanduser("~/.patrick/patrick.db")


DEFAULT_DB_PATH = default_db_path()  # valeur au chargement du module, pour affichage/CLI seulement

_TRACKED_LIBS = (
    "numpy", "pandas", "scikit-learn", "xgboost", "lightgbm", "catboost",
    "imbalanced-learn", "shap", "optuna", "pydantic", "arch", "pykalman", "hmmlearn",
)


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or default_db_path()
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


def add_data_quality_issues(conn: sqlite3.Connection, snapshot_id: str, issues: list[dict]) -> None:
    """Phase 6.5 (P6.5). Idempotent par snapshot : si ce `snapshot_id` a déjà
    des lignes (même contenu déjà ingéré via un `force=True` répété), on ne
    duplique pas -- le snapshot lui-même est déjà dédupliqué par hash de
    contenu (`data/store.py`), les motifs d'exclusion qui l'ont produit le
    sont donc aussi par construction."""
    if not issues:
        return
    with conn:
        existing = conn.execute(
            "SELECT 1 FROM data_quality_issue WHERE snapshot_id = ? LIMIT 1", (snapshot_id,)).fetchone()
        if existing:
            return
        conn.executemany(
            "INSERT INTO data_quality_issue (snapshot_id, series, reason, detail) VALUES (?, ?, ?, ?)",
            [(snapshot_id, i["series"], i["reason"], i["detail"]) for i in issues],
        )


def list_data_quality_issues(conn: sqlite3.Connection, snapshot_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT series, reason, detail FROM data_quality_issue WHERE snapshot_id = ? ORDER BY id",
        (snapshot_id,)).fetchall()
    return [dict(zip(("series", "reason", "detail"), row)) for row in rows]


def save_feature_stability(conn: sqlite3.Connection, run_id: str, mean_jaccard: float,
                            n_folds: int, selection_freq: dict[str, float]) -> None:
    """Phase 6.3 (P6.3). `mean_jaccard` peut être NaN (moins de 2 folds
    utilisables) -- stocké tel quel (SQLite REAL accepte NaN), le rapport
    l'affiche comme "non calculable", pas comme un chiffre trompeur."""
    with conn:
        conn.execute(
            "INSERT INTO run_feature_stability (run_id, mean_jaccard, n_folds) VALUES (?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET mean_jaccard = excluded.mean_jaccard, "
            "n_folds = excluded.n_folds",
            (run_id, mean_jaccard, n_folds),
        )
        conn.execute("DELETE FROM feature_stability WHERE run_id = ?", (run_id,))
        if selection_freq:
            conn.executemany(
                "INSERT INTO feature_stability (run_id, feature, selection_freq) VALUES (?, ?, ?)",
                [(run_id, feat, freq) for feat, freq in selection_freq.items()],
            )


def get_feature_stability(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT mean_jaccard, n_folds FROM run_feature_stability WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    freq_rows = conn.execute(
        "SELECT feature, selection_freq FROM feature_stability WHERE run_id = ? "
        "ORDER BY selection_freq DESC, feature", (run_id,)).fetchall()
    return {"mean_jaccard": row[0], "n_folds": row[1],
            "selection_freq": [{"feature": f, "selection_freq": freq} for f, freq in freq_rows]}


def create_run(conn: sqlite3.Connection, run_id: str, target: str, horizon: int,
                snapshot_id: str, config_json: str, config_hash: str,
                git_sha: str, seed: int, job_id: str | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, started_at, status, target, horizon, snapshot_id, "
            "config_json, config_hash, git_sha, seed, lib_versions, job_id) "
            "VALUES (?, datetime('now'), 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, target, horizon, snapshot_id, config_json, config_hash,
             git_sha, seed, library_versions(), job_id),
        )


def finish_run(conn: sqlite3.Connection, run_id: str, status: str,
                n_trials: int | None = None, error: str | None = None) -> None:
    with conn:
        conn.execute(
            "UPDATE run SET status = ?, finished_at = datetime('now'), n_trials = ?, "
            "error = ? WHERE run_id = ?",
            (status, n_trials, error, run_id),
        )


_RUN_COLUMNS = ["run_id", "target", "horizon", "snapshot_id", "config_json", "config_hash",
                "git_sha", "seed", "lib_versions", "status", "started_at", "finished_at",
                "n_trials", "error", "job_id"]


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(_RUN_COLUMNS)} FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()
    return dict(zip(_RUN_COLUMNS, row)) if row else None


def list_done_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Runs terminés (`status='done'`), les plus récents d'abord -- alimente le
    sélecteur de run du simulateur (Phase 4.7)."""
    rows = conn.execute(
        "SELECT run_id, target, horizon, started_at, finished_at, config_json "
        "FROM run WHERE status = 'done' ORDER BY started_at DESC LIMIT ?", (limit,),
    ).fetchall()
    out = []
    for run_id, target, horizon, started_at, finished_at, config_json in rows:
        name = None
        try:
            name = json.loads(config_json).get("name")
        except (TypeError, ValueError, AttributeError):
            pass
        out.append({"run_id": run_id, "target": target, "horizon": horizon, "name": name,
                     "started_at": started_at, "finished_at": finished_at})
    return out


def list_trials_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, is_best "
        "FROM trial WHERE run_id = ? ORDER BY is_best DESC, trial_id", (run_id,),
    ).fetchall()
    return [{"trial_id": r[0], "regime": r[1], "algo": r[2], "sampler": r[3],
             "n_features": r[4], "selector": r[5], "is_best": bool(r[6])} for r in rows]


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
    """`y_true` peut contenir `None` (Phase 4.6, `split='live'` : la prédiction
    est écrite AVANT que le résultat soit connu) -- stocké en NULL plutôt que
    de planter sur `float(None)`, complété plus tard par
    `update_prediction_outcome`."""
    proba = y_proba if y_proba is not None else [None] * len(ts)
    rows = [(trial_id, str(t), fold_index, split, float(yt) if yt is not None else None, float(yp),
              float(yp_proba) if yp_proba is not None else None)
            for t, yt, yp, yp_proba in zip(ts, y_true, y_pred, proba)]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prediction (trial_id, ts, fold_index, split, y_true, "
            "y_pred, y_proba) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def list_pending_live_predictions(conn: sqlite3.Connection, trial_id: int) -> list[dict]:
    """Prédictions `split='live'` dont le résultat n'est pas encore connu
    (Phase 4.6) -- candidates pour `update_prediction_outcome` une fois leur
    horizon écoulé."""
    rows = conn.execute(
        "SELECT ts FROM prediction WHERE trial_id = ? AND split = 'live' AND y_true IS NULL",
        (trial_id,),
    ).fetchall()
    return [{"ts": r[0]} for r in rows]


def update_prediction_outcome(conn: sqlite3.Connection, trial_id: int, ts: str, y_true: float) -> None:
    with conn:
        conn.execute(
            "UPDATE prediction SET y_true = ? WHERE trial_id = ? AND ts = ?",
            (float(y_true), trial_id, ts),
        )
