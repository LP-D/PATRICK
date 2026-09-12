"""SQLite persistence for runs (Phase 1) — one row per trial (`trial`), not
just the winner, to later allow computing statistical validity (Deflated
Sharpe, PBO — Phase 2) which needs to know how many configurations were
actually tested.

Local single-user project: no Redis/Postgres/service — SQLite (WAL, one
file) + numbered SQL migrations (no Alembic, this project does not go
through SQLAlchemy).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from importlib import metadata as importlib_metadata
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_CREATE_TABLE_RE = re.compile(r"^\s*CREATE TABLE\s+(?:IF NOT EXISTS\s+)?[\"'`]?(\w+)[\"'`]?", re.IGNORECASE)
_CREATE_INDEX_RE = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?[\"'`]?(\w+)[\"'`]?", re.IGNORECASE)


def default_db_path() -> str:
    """Read from the environment on EVERY call (not a constant frozen at
    import time): `patrick worker`, launched as a separate process by
    `run_manager.ensure_worker_running`, must share the same database as the
    web process that spawned it (environment inheritance via
    `subprocess.Popen`) without needing to pass the path as a CLI argument
    — and tests must be able to isolate each run on a `tmp_path` by setting
    `PATRICK_DB_PATH` before calling `connect()`, which a parameter default
    (evaluated once at module import) would not allow."""
    return os.environ.get("PATRICK_DB_PATH") or os.path.expanduser("~/.patrick/patrick.db")


DEFAULT_DB_PATH = default_db_path()  # value at module load time, for display/CLI only

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


def _split_statements(sql: str) -> list[str]:
    """Split a migration script into individual statements. Migrations here
    are plain DDL/DML with no semicolons inside string literals (verified
    across all current scripts), so a split on ';' is enough once `--` line
    comments are stripped first -- otherwise a semicolon inside a French
    comment (this project's migration headers are prose, not just code)
    could be mistaken for a statement terminator."""
    stripped_lines = []
    for line in sql.splitlines():
        comment_at = line.find("--")
        stripped_lines.append(line[:comment_at] if comment_at != -1 else line)
    return [s.strip() for s in "\n".join(stripped_lines).split(";") if s.strip()]


def _ddl_target_already_exists(conn: sqlite3.Connection, statement: str) -> bool:
    """True if `statement` is a bare `CREATE TABLE`/`CREATE INDEX` (no
    `IF NOT EXISTS`) whose target already exists in the database -- the
    only two DDL forms in these migrations that raise `OperationalError` on
    a repeat run. Checked per statement at execution time rather than
    classifying a whole script upfront as "safe to skip entirely": a real
    incident (`0011_phase9_tracking.sql`, renumbered from 0010 after a
    collision with this project's own `0010_dm_result_kind.sql`) showed
    that decision is only as reliable as whatever inspects the script's
    content, and a per-statement check needs no such inspection to be
    correct -- it just asks SQLite whether the object is already there.
    Anything else (INSERT/DROP/RENAME/ALTER, or a statement that already
    spells out IF NOT EXISTS) runs unconditionally; a migration that isn't
    naturally safe to partially re-run this way (like 0010/0012's table
    rebuild) is excluded upstream via `_CUSTOM_IDEMPOTENCY_CHECKS` instead."""
    for pattern, obj_type in ((_CREATE_TABLE_RE, "table"), (_CREATE_INDEX_RE, "index")):
        m = pattern.match(statement)
        if m and "IF NOT EXISTS" not in statement[:m.end()].upper():
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
                (obj_type, m.group(1)),
            ).fetchone()
            return row is not None
    return False


def _run_migration_script(conn: sqlite3.Connection, sql: str) -> None:
    """Runs a migration script statement by statement (instead of a single
    `executescript()` call) so a `CREATE TABLE`/`CREATE INDEX` whose target
    already exists is skipped individually, without needing to decide
    upfront whether the whole script is "safe" to skip."""
    for statement in _split_statements(sql):
        if _ddl_target_already_exists(conn, statement):
            continue
        conn.execute(statement)


def _dm_result_already_has_kind(conn: sqlite3.Connection) -> bool:
    """True if `dm_result` already has its `kind` column. Guards migration
    0012 (`0012_dm_result_kind_repair.sql`, a byte-for-byte replay of
    `0010_dm_result_kind.sql`'s table rebuild) against re-running on a
    database where 0010 already applied normally -- unlike
    `_ddl_target_already_exists`'s per-statement check, "does dm_result_new
    exist" would not work here, since that table is transient (renamed away
    within the same script) and never lingers on disk either way."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(dm_result)")}
    return "kind" in cols


# Per-version idempotency overrides for migrations whose real effect isn't
# expressible as "each individual CREATE TABLE/INDEX target already exists"
# (`_ddl_target_already_exists`, checked per statement in
# `_run_migration_script`) -- e.g. an ALTER-equivalent table rebuild, where
# skipping only some of its statements would leave the table half-migrated.
# Keyed by version so it stays opt-in per migration rather than a guess
# applied to every script.
_CUSTOM_IDEMPOTENCY_CHECKS = {12: _dm_result_already_has_kind}


def migrate(conn: sqlite3.Connection) -> None:
    """Two connections (e.g. the web process and the `patrick worker`
    subprocess it spawns, sharing one `PATRICK_DB_PATH` -- see
    `default_db_path`'s docstring) can call this around the same time on a
    brand new db. A plain `SELECT MAX(version)` before applying anything
    would let both read `current = 0` before either has committed, so both
    replay the same migrations -- several of which (0002, 0007, 0008, 0010,
    0012, 0013, 0017) contain non-idempotent ALTER/DROP/RENAME/INSERT
    statements, not just re-runnable `CREATE TABLE IF NOT EXISTS`. `BEGIN
    IMMEDIATE` acquires the write lock up front (instead of only once a
    write statement is reached), so a racing connection blocks here --
    `busy_timeout` (set by `connect()` before calling this) makes it wait
    rather than error -- and re-reads `current` already caught up once
    unblocked, rather than redoing what the first connection just applied.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]

        scripts = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for script in scripts:
            version = int(script.name.split("_", 1)[0])
            if version <= current:
                continue
            custom_check = _CUSTOM_IDEMPOTENCY_CHECKS.get(version)
            if custom_check is not None and custom_check(conn):
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                continue
            _run_migration_script(conn, script.read_text())
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def library_versions() -> str:
    """JSON {lib: version} of the main dependencies — see Phase 1.6
    (reproducibility). `importlib.metadata` (stdlib): no dependency added
    just for this."""
    versions = {"python": sys.version.split()[0]}
    for lib in _TRACKED_LIBS:
        try:
            versions[lib] = importlib_metadata.version(lib)
        except importlib_metadata.PackageNotFoundError:
            pass
    return json.dumps(versions, sort_keys=True)


def current_git_sha(cwd: str | None = None) -> str:
    """Git SHA of the current HEAD — "unknown" (no exception) if the run runs
    outside a git repo or with no git binary available: reproducibility
    suffers but this must never crash a run."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
            text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# CRUD — one function per write table, all idempotent/explicit about their
# parameters rather than taking untyped dicts.
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


def exclude_symbol(conn: sqlite3.Connection, symbol: str, reason: str) -> None:
    """M1: persist a symbol as confirmed unavailable at the data source
    (see migration 0013). `ON CONFLICT DO NOTHING`, not DO UPDATE: the
    first-confirmed reason/date is the historical record of when this was
    established, not something a later call should silently overwrite."""
    with conn:
        conn.execute(
            "INSERT INTO excluded_symbol (symbol, reason) VALUES (?, ?) "
            "ON CONFLICT(symbol) DO NOTHING",
            (symbol, reason),
        )


def get_cached_selection(conn: sqlite3.Connection, target: str, horizon: int, snapshot_id: str,
                          data_hash: str, selector_config_hash: str) -> list[int] | None:
    """S4: returns the cached feature-selection column indices for this
    exact key, or None on a miss. No TTL/expiration check (see migration
    0014's docstring): a snapshot is immutable once created, so a hit here
    is never stale -- the only invalidation is a change in one of the five
    key fields."""
    row = conn.execute(
        "SELECT selected_columns FROM shap_selection_cache WHERE "
        "target = ? AND horizon = ? AND snapshot_id = ? AND data_hash = ? AND selector_config_hash = ?",
        (target, horizon, snapshot_id, data_hash, selector_config_hash),
    ).fetchone()
    return json.loads(row[0]) if row else None


def save_cached_selection(conn: sqlite3.Connection, target: str, horizon: int, snapshot_id: str,
                           data_hash: str, selector_config_hash: str, columns: list[int]) -> None:
    with conn:
        conn.execute(
            "INSERT INTO shap_selection_cache "
            "(target, horizon, snapshot_id, data_hash, selector_config_hash, selected_columns) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (target, horizon, snapshot_id, data_hash, selector_config_hash, json.dumps(columns)),
        )


def get_cached_vol_model(conn: sqlite3.Connection, snapshot_id: str, ticker: str, model: str,
                          fit_end_idx: int, test_end_idx: int, data_hash: str) -> list[float | None] | None:
    """Cache for parametric volatility-model computations (EGARCH/Kalman/HMM/
    AR/MA/ARMA/ARIMA -- see migration 0015). `fit_end_idx`/`test_end_idx` use
    -1 as the "not provided" sentinel (see migration 0015's docstring), never
    NULL -- SQLite does not dedupe NULLs against each other in a composite
    PRIMARY KEY. No TTL: same reasoning as `get_cached_selection`, a snapshot
    never changes once created."""
    row = conn.execute(
        "SELECT result_json FROM vol_model_cache WHERE snapshot_id = ? AND ticker = ? AND model = ? "
        "AND fit_end_idx = ? AND test_end_idx = ? AND data_hash = ?",
        (snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash),
    ).fetchone()
    return json.loads(row[0]) if row else None


def save_cached_vol_model(conn: sqlite3.Connection, snapshot_id: str, ticker: str, model: str,
                           fit_end_idx: int, test_end_idx: int, data_hash: str,
                           values: list[float | None]) -> None:
    with conn:
        conn.execute(
            "INSERT INTO vol_model_cache "
            "(snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash, json.dumps(values)),
        )


def list_excluded_symbols(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT symbol, reason, excluded_at FROM excluded_symbol ORDER BY excluded_at"
    ).fetchall()
    return [dict(zip(("symbol", "reason", "excluded_at"), row)) for row in rows]


def add_data_quality_issues(conn: sqlite3.Connection, snapshot_id: str, issues: list[dict]) -> None:
    """Phase 6.5 (P6.5). Idempotent per snapshot: if this `snapshot_id`
    already has rows (same content already ingested via a repeated
    `force=True`), nothing is duplicated -- the snapshot itself is already
    deduplicated by content hash (`data/store.py`), so the exclusion reasons
    that produced it are too, by construction."""
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


def save_phase9_snapshot(conn: sqlite3.Connection, snapshot_name: str, state: dict) -> int:
    """Persist one snapshot of the Phase 9 workspace for later review."""
    payload = json.dumps(state, sort_keys=True, default=str)
    with conn:
        cursor = conn.execute(
            "INSERT INTO phase9_snapshot (snapshot_name, payload_json, created_at) VALUES (?, ?, datetime('now'))",
            (snapshot_name, payload),
        )
    return int(cursor.lastrowid)


def list_phase9_snapshots(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT snapshot_name, payload_json, created_at FROM phase9_snapshot ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "snapshot_name": snapshot_name,
            "payload": json.loads(payload_json) if payload_json else {},
            "created_at": created_at,
        }
        for snapshot_name, payload_json, created_at in rows
    ]


def save_phase9_journal_entry(conn: sqlite3.Connection, action: str, actor: str, before: object | None, after: object | None, reason: str) -> dict:
    """Persist a decision or operator action for the Phase 9 tracking layer."""
    payload_before = json.dumps(before, sort_keys=True, default=str)
    payload_after = json.dumps(after, sort_keys=True, default=str)
    with conn:
        cursor = conn.execute(
            "INSERT INTO phase9_journal (action, actor, before_json, after_json, reason, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (action, actor, payload_before, payload_after, reason),
        )
    row = conn.execute(
        "SELECT id, action, actor, before_json, after_json, reason, created_at FROM phase9_journal WHERE id = ?",
        (int(cursor.lastrowid),),
    ).fetchone()
    return {
        "id": row[0],
        "action": row[1],
        "actor": row[2],
        "before": json.loads(row[3]) if row[3] else None,
        "after": json.loads(row[4]) if row[4] else None,
        "reason": row[5],
        "created_at": row[6],
    }


def list_phase9_journal_entries(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, action, actor, before_json, after_json, reason, created_at FROM phase9_journal ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row[0],
            "action": row[1],
            "actor": row[2],
            "before": json.loads(row[3]) if row[3] else None,
            "after": json.loads(row[4]) if row[4] else None,
            "reason": row[5],
            "created_at": row[6],
        }
        for row in rows
    ]


def save_feature_stability(conn: sqlite3.Connection, run_id: str, mean_jaccard: float,
                            n_folds: int, selection_freq: dict[str, float]) -> None:
    """Phase 6.3 (P6.3). `mean_jaccard` can be NaN (fewer than 2 usable
    folds) -- converted to SQL NULL before storage (nullable column, see
    migration 0006; sqlite3/the Python driver does not guarantee a Python
    NaN survives `REAL` binding), the report displays it as "not
    computable", never as a misleading number."""
    mean_jaccard_sql = mean_jaccard if mean_jaccard == mean_jaccard else None  # NaN != NaN
    with conn:
        conn.execute(
            "INSERT INTO run_feature_stability (run_id, mean_jaccard, n_folds) VALUES (?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET mean_jaccard = excluded.mean_jaccard, "
            "n_folds = excluded.n_folds",
            (run_id, mean_jaccard_sql, n_folds),
        )
        conn.execute("DELETE FROM feature_stability WHERE run_id = ?", (run_id,))
        if selection_freq:
            conn.executemany(
                "INSERT INTO feature_stability (run_id, feature, selection_freq) VALUES (?, ?, ?)",
                [(run_id, feat, freq) for feat, freq in selection_freq.items()],
            )


def get_feature_stability(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """`mean_jaccard` comes back as NaN (not `None`) when not computable --
    SQL NULL only at persistence time (see `save_feature_stability`), NaN on
    the Python side so existing numeric comparisons (`mj == mj`) remain
    valid without handling `None` separately everywhere."""
    row = conn.execute(
        "SELECT mean_jaccard, n_folds FROM run_feature_stability WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    mean_jaccard = row[0] if row[0] is not None else float("nan")
    freq_rows = conn.execute(
        "SELECT feature, selection_freq FROM feature_stability WHERE run_id = ? "
        "ORDER BY selection_freq DESC, feature", (run_id,)).fetchall()
    return {"mean_jaccard": mean_jaccard, "n_folds": row[1],
            "selection_freq": [{"feature": f, "selection_freq": freq} for f, freq in freq_rows]}


def save_dm_result(conn: sqlite3.Connection, run_id: str, dm_result: dict,
                    kind: str = "class_specific") -> None:
    """Phase 6.4 (P6.4). Persists THIS run's Diebold-Mariano result (Phase
    2.5) so it is queryable across the whole history (see migration 0009)
    -- `dm_result` comes from `validation.diebold_mariano.diebold_mariano()`
    with an extra `baseline` field (added by
    `pipeline/engine.py::_evaluate_diebold_mariano`).

    `kind` (Phase X5, migration 0010): `"class_specific"` (baseline specific
    to the target's asset class, see `validation.baseline_by_asset_class`)
    or `"common"` (class-agnostic persistence, fixed reference across
    classes) -- two distinct rows per run, PRIMARY KEY (run_id, kind)."""
    with conn:
        conn.execute(
            "INSERT INTO dm_result (run_id, kind, baseline, dm_stat, p_value) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, kind) DO UPDATE SET baseline = excluded.baseline, "
            "dm_stat = excluded.dm_stat, p_value = excluded.p_value, "
            "computed_at = datetime('now')",
            (run_id, kind, dm_result["baseline"], dm_result.get("dm_stat"), dm_result["p_value"]),
        )


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


def record_phase_timing(conn: sqlite3.Connection, run_id: str, phase: str,
                         started_at: float, finished_at: float) -> None:
    """Phase-timing instrumentation (migration 0016). `started_at`/
    `finished_at` are `time.time()` epoch floats -- the same clock
    `pipeline/engine.py` already uses for its own `t0`/duration prints --
    converted here to the UTC 'YYYY-MM-DD HH:MM:SS' string format
    `datetime('now')` produces elsewhere in this schema, so this table's
    timestamps stay directly comparable to `run.started_at`/`finished_at`.

    One row per phase OCCURRENCE, not one row per (run_id, phase): see the
    migration's header for why (ingestion/pool_construction happen once
    per pipeline invocation and get recorded once per horizon's run_id;
    tuning can occur more than once per run_id, once per top-config)."""
    started_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(started_at))
    finished_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(finished_at))
    with conn:
        conn.execute(
            "INSERT INTO run_phase_timing (run_id, phase, started_at, finished_at) VALUES (?, ?, ?, ?)",
            (run_id, phase, started_str, finished_str),
        )


def reap_orphaned_runs(conn: sqlite3.Connection, max_age_s: float = 3600.0) -> int:
    """Runs left 'running' beyond `max_age_s` -> their worker died before
    calling `finish_run` (kill -9, crash, a container-level swap -- see
    AUDIT_ENVIRONNEMENT.md for a real example), or -- a distinct, more
    common gap this also closes -- `worker.py::_run_one_job` catches a
    normal pipeline exception and marks `job.status='error'`, but never
    touches the `run` row itself, so a plain caught exception mid-run also
    left it stuck on 'running' forever until now.

    Age-gated exactly like `jobs.reap_stale_running_jobs`, not "any running
    row at worker startup is orphaned": `run_manager.ensure_worker_running`
    documents that two workers can briefly, legitimately overlap (no
    distributed lock), so a run genuinely in progress under a live worker
    -- itself possibly just started -- must not be reaped out from under it.
    Called once at `run_worker_loop` startup, never during an ongoing
    execution."""
    with conn:
        cur = conn.execute(
            "UPDATE run SET status = 'failed', finished_at = datetime('now'), "
            "error = 'orphaned: no matching process at worker startup' "
            "WHERE status = 'running' AND "
            "(julianday('now') - julianday(started_at)) * 86400 > ?",
            (max_age_s,),
        )
    return cur.rowcount


def cleanup_legacy_ticker_runs(conn: sqlite3.Connection) -> int:
    """Runs left 'running'/'pending' whose `target` is no longer part of the
    current reduced universe (`config.defaults.DEFAULT_TARGET_CHOICES`, since
    commit 3cc303f which cut ~550 tickers down to 67 -- commodity futures +
    FRED macro series + 4 kept assets) can never complete: no feature/config
    wiring exists any more for a ticker outside that set, so a worker will
    never pick them back up nor drive them to 'done'/'failed' on its own --
    they are orphaned the moment the universe changed under them, not after
    some timeout.

    Distinct from `reap_orphaned_runs` above: that one is age-gated and
    target-agnostic (any run stuck 'running' too long, regardless of
    ticker); this one is target-gated and age-agnostic (a 'running'/'pending'
    row on a legacy ticker is invalid immediately, no need to wait one out).
    The two catch different orphans and neither should touch the other's:
    this function leaves alone
    - 'running'/'pending' rows on a still-valid target (a different,
      unrelated orphan -- `reap_orphaned_runs`'s concern, not this one's);
    - already-finished ('done'/'failed') rows on a legacy target -- those
      are legitimate historical results from when that ticker was still in
      scope, not orphans, and must never be rewritten.

    Same manual remediation this codifies as a repeatable, tested function:
    the ad hoc `GSPC_1_detail_h*` cleanup done directly against the DB
    before this existed."""
    from patrick.config.defaults import DEFAULT_TARGET_CHOICES

    valid_targets = {symbol for symbol, _label, _source in DEFAULT_TARGET_CHOICES}

    rows = conn.execute(
        "SELECT run_id, target FROM run WHERE status IN ('running', 'pending')"
    ).fetchall()

    count = 0
    for run_id, target in rows:
        if target not in valid_targets:
            finish_run(conn, run_id, status="failed",
                       error="ticker hors univers reduit, run abandonne")
            count += 1
    return count


_RUN_COLUMNS = ["run_id", "target", "horizon", "snapshot_id", "config_json", "config_hash",
                "git_sha", "seed", "lib_versions", "status", "started_at", "finished_at",
                "n_trials", "error", "job_id"]


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(_RUN_COLUMNS)} FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()
    return dict(zip(_RUN_COLUMNS, row)) if row else None


def list_all_runs(conn: sqlite3.Connection) -> list[dict]:
    """All runs, most recent first — for exploratory surfaces (Phase 5).
    Includes `scheme`/`best_f1_dir`/`dm_p_value` (same queries as
    `tracking.history.list_runs`, duplicated here rather than imported:
    `db.py` is the low-level layer, `history.py` depends on it, not the
    other way around) -- `runs.html` displays them directly (`r.scheme`,
    `r.best_f1_dir`, `r.dm_p_value`)."""
    rows = conn.execute(
        "SELECT run_id, target, horizon, status, started_at, finished_at, config_json, n_trials "
        "FROM run ORDER BY started_at DESC",
    ).fetchall()
    out = []
    for run_id, target, horizon, status, started_at, finished_at, config_json, n_trials in rows:
        name, scheme = None, "walkforward"
        try:
            cfg = json.loads(config_json) if config_json else {}
            name = cfg.get("name")
            scheme = cfg.get("validation", {}).get("scheme", "walkforward")
        except (TypeError, ValueError, AttributeError):
            pass
        best_row = conn.execute(
            "SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1 LIMIT 1", (run_id,)
        ).fetchone()
        best_f1_dir = None
        if best_row:
            metric_row = conn.execute(
                "SELECT AVG(value) FROM fold_metric WHERE trial_id = ? "
                "AND split IN ('test', 'test_path') AND metric = 'F1_dir'",
                (best_row[0],),
            ).fetchone()
            best_f1_dir = metric_row[0] if metric_row and metric_row[0] is not None else None
        dm_row = conn.execute("SELECT p_value FROM dm_result WHERE run_id = ?", (run_id,)).fetchone()
        out.append({
            "run_id": run_id, "target": target, "horizon": horizon,
            "status": status, "started_at": started_at, "finished_at": finished_at,
            "n_trials": n_trials, "name": name, "config_json": config_json,
            "scheme": scheme, "best_f1_dir": best_f1_dir,
            "dm_p_value": dm_row[0] if dm_row else None,
        })
    return out


def list_done_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Finished runs (`status='done'`), most recent first -- feeds the
    simulator's run selector (Phase 4.7)."""
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
            for name, value in metrics.items() if value is not None and value == value]  # excludes NaN
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
                     ts: list[str], y_true, y_pred, y_proba=None, path_id: int = -1) -> None:
    """`y_true` can contain `None` (Phase 4.6, `split='live'`: the prediction
    is written BEFORE the outcome is known) -- stored as NULL rather than
    crashing on `float(None)`, backfilled later by
    `update_prediction_outcome`.

    `path_id` (Phase 6.1, P6.1): `-1` (default) = not applicable
    (walk-forward, unchanged behavior); under CPCV, a distinct backtest path
    (`validation/cpcv.py::path_assignment`) -- the same date can then appear
    in several `prediction` rows (one per path that covers it),
    (trial_id, ts, path_id) distinguishes them."""
    proba = y_proba if y_proba is not None else [None] * len(ts)
    rows = [(trial_id, str(t), fold_index, split, float(yt) if yt is not None else None, float(yp),
              float(yp_proba) if yp_proba is not None else None, path_id)
            for t, yt, yp, yp_proba in zip(ts, y_true, y_pred, proba)]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prediction (trial_id, ts, fold_index, split, y_true, "
            "y_pred, y_proba, path_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def list_pending_live_predictions(conn: sqlite3.Connection, trial_id: int) -> list[dict]:
    """`split='live'` predictions whose outcome is not yet known (Phase 4.6)
    -- candidates for `update_prediction_outcome` once their horizon has
    elapsed."""
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


def latest_prediction_for_trial(conn: sqlite3.Connection, trial_id: int) -> dict | None:
    """Phase 7 (SHAP waterfall) -- the most recent `prediction` row recorded
    for a trial, whatever its `split` (holdout/test/test_path/live). Used to
    pick a real, already-persisted prediction to explain rather than
    triggering a fresh live inference (`predict.py`'s job, not this one) --
    `ts` strings are lexicographically sortable ISO-like dates, so `ORDER BY
    ts DESC` is correct here."""
    row = conn.execute(
        "SELECT ts, split, fold_index, y_true, y_pred, y_proba FROM prediction "
        "WHERE trial_id = ? ORDER BY ts DESC LIMIT 1",
        (trial_id,),
    ).fetchone()
    if row is None:
        return None
    ts, split, fold_index, y_true, y_pred, y_proba = row
    return {"ts": ts, "split": split, "fold_index": fold_index, "y_true": y_true,
            "y_pred": int(y_pred), "y_proba": y_proba}
