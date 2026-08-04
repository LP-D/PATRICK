"""Règle de nommage des runs (spec `docs/superpowers/specs/
2026-08-02-batch-run-launch-design.md` §2) : nom = slug(target) + numéro de
séquence, toujours -- jamais de saisie libre."""
from __future__ import annotations

import pytest

from patrick.tracking import db as trackdb
from patrick.webapp import forms, run_manager


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))


def _seed_run(conn, run_id: str, target: str) -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", 10, 5, "api")
    trackdb.create_run(conn, run_id, target, 1, "snap1", "{}", "confighash", "sha", 42)


def test_slug_target_strips_leading_caret():
    assert forms.slug_target("^VIX") == "VIX"


def test_slug_target_replaces_equals():
    assert forms.slug_target("EURUSD=X") == "EURUSD_X"


def test_slug_target_replaces_dot():
    assert forms.slug_target("000001.SS") == "000001_SS"


def test_slug_target_collapses_adjacent_separators():
    assert forms.slug_target("AB==CD") == "AB_CD"


def test_slug_target_leaves_plain_ticker_unchanged():
    assert forms.slug_target("AAPL") == "AAPL"


def test_next_run_name_starts_at_one_with_no_history():
    assert run_manager.next_run_name("^VIX") == "VIX_1"


def test_next_run_name_increments_with_history():
    conn = trackdb.connect()
    try:
        _seed_run(conn, "run1", "^VIX")
        _seed_run(conn, "run2", "^VIX")
    finally:
        conn.close()
    assert run_manager.next_run_name("^VIX") == "VIX_3"


def test_next_run_name_counts_per_target_independently():
    conn = trackdb.connect()
    try:
        _seed_run(conn, "run1", "^VIX")
    finally:
        conn.close()
    assert run_manager.next_run_name("^AORD") == "AORD_1"


def test_next_run_name_skips_names_claimed_by_queued_jobs():
    import json as _json
    from patrick.tracking import jobs as jobs_db
    conn = trackdb.connect()
    try:
        config_json = _json.dumps({"name": "VIX_1", "objective": {"target_symbol": "^VIX"}})
        jobs_db.enqueue_job(conn, config_json)
    finally:
        conn.close()
    assert run_manager.next_run_name("^VIX") == "VIX_2"
