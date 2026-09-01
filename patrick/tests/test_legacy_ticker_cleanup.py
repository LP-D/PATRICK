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

from patrick.tracking import db as trackdb
from patrick.config.defaults import DEFAULT_TARGET_CHOICES

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
