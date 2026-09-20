"""Universe reduction (commit 3cc303f, ~550 tickers -> 67) left `run` rows
stuck 'running' on tickers no longer in `config.defaults.DEFAULT_TARGET_CHOICES`
-- orphans that can never complete since no feature/config wiring exists for
them any more. This tests `trackdb.cleanup_legacy_ticker_runs`, the targeted
(not age-gated) cleanup for exactly that case -- see its docstring for how it
differs from `trackdb.reap_orphaned_runs`.

`cleanup_legacy_ticker_runs` matches `status IN ('running', 'pending')`
(matching the production audit query this cleanup was written to codify),
but only 'running' is exercised here: the `run` table's schema
(`migrations/0001_initial.sql`) CHECKs `status IN ('queued', 'running',
'done', 'failed')` -- 'pending' cannot actually occur, confirmed against the
real production DB (30 running/pending rows total, all 'running', 0
'pending') -- so a fixture row with status='pending' would violate the CHECK
constraint and not represent any real state.

The "legacy"/"valid" targets used below are derived from
`DEFAULT_TARGET_CHOICES` itself (never hardcoded), so this test stays
correct if the universe list changes again.
"""
from __future__ import annotations

from patrick.config.defaults import DEFAULT_TARGET_CHOICES
from patrick.tracking import db as trackdb

_VALID_TARGETS = {symbol for symbol, _label, _source in DEFAULT_TARGET_CHOICES}
_VALID_TARGET = next(iter(_VALID_TARGETS))  # any real, still-in-scope ticker
_LEGACY_TARGET = "^NOT_IN_REDUCED_UNIVERSE"  # guaranteed outside the 67, see assert below

assert _LEGACY_TARGET not in _VALID_TARGETS


def _insert_run(conn, run_id: str, target: str, status: str, error: str | None = None) -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, started_at, status, target, horizon, snapshot_id, "
            "config_json, config_hash, git_sha, seed, lib_versions, error) VALUES "
            "(?, datetime('now'), ?, ?, 5, 'snap1', '{}', 'cfg', 'sha', 42, '{}', ?)",
            (run_id, status, target, error),
        )


def _status_and_error(conn, run_id: str):
    row = conn.execute("SELECT status, error, finished_at FROM run WHERE run_id = ?", (run_id,)).fetchone()
    return row


def test_cleanup_marks_running_legacy_target_runs_as_failed(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "legacy_running_1", _LEGACY_TARGET, "running")
    _insert_run(conn, "legacy_running_2", _LEGACY_TARGET, "running")

    changed = trackdb.cleanup_legacy_ticker_runs(conn)

    assert changed == 2
    for run_id in ("legacy_running_1", "legacy_running_2"):
        status, error, finished_at = _status_and_error(conn, run_id)
        assert status == "failed"
        assert error == "ticker hors univers reduit, run abandonne"
        assert finished_at is not None
    conn.close()


def test_cleanup_leaves_running_valid_target_untouched(tmp_path, monkeypatch):
    """A `running`/`pending` row on a STILL-VALID target is a different,
    unrelated orphan (`reap_orphaned_runs`'s concern) -- must not be
    touched by this target-gated cleanup."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "valid_running", _VALID_TARGET, "running")

    changed = trackdb.cleanup_legacy_ticker_runs(conn)

    assert changed == 0
    status, error, finished_at = _status_and_error(conn, "valid_running")
    assert status == "running"
    assert error is None
    assert finished_at is None
    conn.close()


def test_cleanup_leaves_finished_legacy_target_runs_untouched(tmp_path, monkeypatch):
    """`done`/`failed` rows on a legacy target are legitimate historical
    results from when that ticker was still in scope, not orphans -- must
    survive the cleanup unchanged, including their original error text."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "legacy_done", _LEGACY_TARGET, "done")
    _insert_run(conn, "legacy_failed_before", _LEGACY_TARGET, "failed", error="pre-existing failure reason")

    changed = trackdb.cleanup_legacy_ticker_runs(conn)

    assert changed == 0
    status, error, _ = _status_and_error(conn, "legacy_done")
    assert status == "done"
    assert error is None
    status, error, _ = _status_and_error(conn, "legacy_failed_before")
    assert status == "failed"
    assert error == "pre-existing failure reason"
    conn.close()


def test_cleanup_mixed_scenario_only_touches_running_legacy_rows(tmp_path, monkeypatch):
    """All four categories at once, exactly mirroring the production shape
    this cleanup targets (18 running+legacy, 12 running+valid, 60
    done/failed+legacy): legacy+running rows get reaped, valid+running and
    legacy+done/failed are both left alone."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "r1", _LEGACY_TARGET, "running")
    _insert_run(conn, "r2", _LEGACY_TARGET, "running")
    _insert_run(conn, "r3", _VALID_TARGET, "running")
    _insert_run(conn, "r4", _LEGACY_TARGET, "done")
    _insert_run(conn, "r5", _LEGACY_TARGET, "failed", error="old failure")

    changed = trackdb.cleanup_legacy_ticker_runs(conn)

    assert changed == 2
    assert _status_and_error(conn, "r1")[0] == "failed"
    assert _status_and_error(conn, "r2")[0] == "failed"
    assert _status_and_error(conn, "r3")[0] == "running"
    assert _status_and_error(conn, "r4")[0] == "done"
    assert _status_and_error(conn, "r5")[0] == "failed"
    assert _status_and_error(conn, "r5")[1] == "old failure"

    # No running/pending row referencing a ticker outside DEFAULT_TARGET_CHOICES survives.
    remaining = conn.execute("SELECT target FROM run WHERE status IN ('running', 'pending')").fetchall()
    assert all(t[0] in _VALID_TARGETS for t in remaining)
    conn.close()


def test_list_legacy_ticker_runs_is_read_only_and_covers_every_status(tmp_path, monkeypatch):
    """Read-only preview (no mutation) of every `run` row referencing a
    ticker outside `DEFAULT_TARGET_CHOICES`, regardless of status --
    deliberately broader than `cleanup_legacy_ticker_runs` (running/pending
    only): this is the inspection step a hard-delete decision must be based
    on, so it must surface `done`/`failed` rows too, even though those are
    documented above (`test_cleanup_leaves_finished_legacy_target_runs_untouched`)
    as legitimate historical results that `cleanup_legacy_ticker_runs` itself
    must never touch."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "legacy_running", _LEGACY_TARGET, "running")
    _insert_run(conn, "legacy_done", _LEGACY_TARGET, "done")
    _insert_run(conn, "legacy_failed", _LEGACY_TARGET, "failed", error="old failure")
    _insert_run(conn, "valid_done", _VALID_TARGET, "done")

    preview = trackdb.list_legacy_ticker_runs(conn)

    assert {row["run_id"] for row in preview} == {"legacy_running", "legacy_done", "legacy_failed"}
    # Read-only: statuses/targets unchanged, nothing deleted or mutated.
    assert _status_and_error(conn, "legacy_running")[0] == "running"
    assert _status_and_error(conn, "legacy_done")[0] == "done"
    assert conn.execute("SELECT count(*) FROM run").fetchone()[0] == 4
    conn.close()


def _is_archived(conn, run_id: str) -> bool:
    row = conn.execute("SELECT is_archived FROM run WHERE run_id = ?", (run_id,)).fetchone()
    return bool(row[0])


def test_archive_legacy_ticker_runs_marks_all_statuses_without_deleting(tmp_path, monkeypatch):
    """Archive-in-place (migration 0018's `is_archived` flag), NOT the hard
    DELETE originally asked for: on the real production DB every legacy-
    ticker row is 'done'/'failed' -- exactly what
    `test_cleanup_leaves_finished_legacy_target_runs_untouched` above
    documents as legitimate historical results `cleanup_legacy_ticker_runs`
    must never rewrite. Archiving hides them from default listings without
    deleting or otherwise mutating status/error/any other column, and is
    idempotent (a second call archives nothing new)."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "legacy_running", _LEGACY_TARGET, "running")
    _insert_run(conn, "legacy_done", _LEGACY_TARGET, "done")
    _insert_run(conn, "legacy_failed", _LEGACY_TARGET, "failed", error="old failure")
    _insert_run(conn, "valid_done", _VALID_TARGET, "done")

    archived = trackdb.archive_legacy_ticker_runs(conn)

    assert archived == 3
    for run_id in ("legacy_running", "legacy_done", "legacy_failed"):
        assert _is_archived(conn, run_id) is True
    assert _is_archived(conn, "valid_done") is False
    # Nothing deleted, nothing else mutated.
    assert conn.execute("SELECT count(*) FROM run").fetchone()[0] == 4
    assert _status_and_error(conn, "legacy_done") == ("done", None, None)
    assert _status_and_error(conn, "legacy_failed")[1] == "old failure"

    # Idempotent: a second call finds nothing new to archive.
    assert trackdb.archive_legacy_ticker_runs(conn) == 0
    conn.close()


def test_list_all_runs_excludes_archived_by_default_but_can_include_them(tmp_path, monkeypatch):
    """The one genuinely unconditional 'all runs' listing (`/runs`, Phase
    7.1 full run-history explorer) must hide archived rows by default --
    `/predictions`/`/portfolio` need no equivalent change: both iterate the
    CURRENT universe (`config.defaults.DEFAULT_TARGET_GROUPS`) to build
    their queries (`webapp/app.py::_predictions_overview`), never `run`
    unconditionally, so a legacy-ticker run was already invisible there
    before this flag existed."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "legacy_done", _LEGACY_TARGET, "done")
    _insert_run(conn, "valid_done", _VALID_TARGET, "done")
    trackdb.archive_legacy_ticker_runs(conn)

    active_ids = {r["run_id"] for r in trackdb.list_all_runs(conn)}
    assert active_ids == {"valid_done"}

    all_ids = {r["run_id"] for r in trackdb.list_all_runs(conn, include_archived=True)}
    assert all_ids == {"legacy_done", "valid_done"}
    conn.close()


def test_list_done_runs_excludes_archived_by_default_but_can_include_them(tmp_path, monkeypatch):
    """Same default-hidden/explicit-opt-in behavior for the simulator's run
    selector (`list_done_runs`, feeds `/simulate`)."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)

    _insert_run(conn, "legacy_done", _LEGACY_TARGET, "done")
    _insert_run(conn, "valid_done", _VALID_TARGET, "done")
    trackdb.archive_legacy_ticker_runs(conn)

    active_ids = {r["run_id"] for r in trackdb.list_done_runs(conn)}
    assert active_ids == {"valid_done"}

    all_ids = {r["run_id"] for r in trackdb.list_done_runs(conn, include_archived=True)}
    assert all_ids == {"legacy_done", "valid_done"}
    conn.close()
