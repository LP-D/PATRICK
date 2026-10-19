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


def _job(conn, name: str, target: str = "^VIX", status: str = "done") -> None:
    import json as _json

    from patrick.tracking import jobs as jobs_db
    job_id = jobs_db.enqueue_job(conn, _json.dumps({"name": name, "objective": {"target_symbol": target}}, separators=(",", ":")))
    if status != "queued":
        with conn:
            conn.execute("UPDATE job SET status = ? WHERE job_id = ?", (status, job_id))


def test_a_number_is_never_handed_out_again_after_its_run_was_pruned():
    """Un challenger battu au duel des champions est élagué (ligne `run` supprimée), pas son job : compter les runs ramenait le numéro en arrière
    (IRX_2 et MUB_2 ont nommé quatre jobs chacun, dans le même dossier de sortie)."""
    conn = trackdb.connect()
    try:
        _seed_run(conn, "VIX_2_h1_abc", "^VIX")                  # il ne reste qu'UN run de la cible...
        _job(conn, "VIX_1")
        _job(conn, "VIX_2")                                      # ...mais les jobs 1, 2 et 3 ont existé
        _job(conn, "VIX_3")
    finally:
        conn.close()
    assert run_manager.next_run_name("^VIX") == "VIX_4"          # et non VIX_2, déjà porté


def test_the_number_follows_the_highest_one_ever_used_not_the_count():
    conn = trackdb.connect()
    try:
        _job(conn, "VIX_18")
        _job(conn, "VIX_25")
    finally:
        conn.close()
    assert run_manager.next_run_name("^VIX") == "VIX_26"


def test_other_targets_and_free_names_do_not_move_the_number():
    conn = trackdb.connect()
    try:
        _job(conn, "AORD_9", target="^AORD")
        _job(conn, "VIX_rl_7", target="^VIX")                    # un run de reinforcement learning n'a pas le même motif
        _job(conn, "mon_run", target="^VIX")
    finally:
        conn.close()
    assert run_manager.next_run_name("^VIX") == "VIX_1"
    assert run_manager.next_run_name("^AORD") == "AORD_10"
