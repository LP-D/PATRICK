"""Journal de prédictions chaîné (`patrick/tracking/journal.py`, migration 0040) : chaîne de hachage, premier écrit gagne, refus de modification,
détection d'altération, scellement de l'existant, crochets de `tracking/db.py` sans risque pour l'écriture des prédictions."""
from __future__ import annotations

import sqlite3

import pytest
from analysis_support import seed_run

from patrick.analysis import registry
from patrick.tracking import db as trackdb
from patrick.tracking import journal


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, live=0)
    model = tmp_path / "model.joblib"
    model.write_bytes(b"model-bytes")
    conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (str(model), info["trial_id"]))
    conn.commit()
    yield conn, info, model
    registry.clear_cache()


def _rows(conn):
    return conn.execute("SELECT journal_id, kind, origin, signal_date, y_pred, p_up, y_true, model_hash, prev_hash, entry_hash FROM prediction_journal ORDER BY journal_id").fetchall()


def test_live_signal_is_journaled_with_model_hash_and_chain(seeded):
    conn, info, model = seeded
    trackdb.add_predictions(conn, info["trial_id"], 0, "live", ["2027-01-04 00:00:00", "2027-01-05 00:00:00"], [None, None], [2.0, 1.0], [0.6, 0.4], p_up=[0.7, 0.3])
    rows = _rows(conn)
    assert [r[1] for r in rows] == ["signal", "signal"] and [r[3] for r in rows] == ["2027-01-04", "2027-01-05"]
    assert rows[0][8] == journal.GENESIS and rows[1][8] == rows[0][9]                      # chaîne : la 2e relie la 1re
    import hashlib
    assert rows[0][7] == hashlib.sha256(b"model-bytes").hexdigest() == journal.model_hash(str(model))
    assert journal.verify(conn) == {"ok": True, "n": 2, "first_bad": None, "reason": None, "head": rows[1][9]}


def test_first_write_wins_and_outcomes_append_once(seeded):
    conn, info, _ = seeded
    tid = info["trial_id"]
    trackdb.add_predictions(conn, tid, 0, "live", ["2027-01-04 00:00:00"], [None], [3.0], [0.9], p_up=[0.95])
    trackdb.add_predictions(conn, tid, 0, "live", ["2027-01-04 00:00:00"], [None], [0.0], [0.9], p_up=[0.05])      # tentative de réécrire le signal
    sig = [r for r in _rows(conn) if r[1] == "signal"]
    assert len(sig) == 1 and sig[0][4] == 3.0 and sig[0][5] == pytest.approx(0.95)                               # le premier signal reste
    trackdb.update_prediction_outcome(conn, tid, "2027-01-04 00:00:00", 1.0, 3)
    trackdb.update_prediction_outcome(conn, tid, "2027-01-04 00:00:00", 1.0, 3)                                  # même issue : rien de plus
    assert [r[1] for r in _rows(conn)] == ["signal", "outcome"]
    trackdb.update_prediction_outcome(conn, tid, "2027-01-04 00:00:00", 0.0, 0)                                  # jugement corrigé : une ligne de plus, l'ancienne reste
    out = [r for r in _rows(conn) if r[1] == "outcome"]
    assert [o[6] for o in out] == [1.0, 0.0] and journal.verify(conn)["ok"] is True


def test_update_and_delete_are_refused_by_triggers(seeded):
    conn, info, _ = seeded
    trackdb.add_predictions(conn, info["trial_id"], 0, "live", ["2027-01-04 00:00:00"], [None], [2.0], [0.6], p_up=[0.6])
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE prediction_journal SET y_pred = 0")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM prediction_journal")
    assert journal.verify(conn)["ok"] is True


def test_tampering_is_detected_even_without_triggers(seeded):
    conn, info, _ = seeded
    ts = [f"2027-01-{d:02d} 00:00:00" for d in range(4, 9)]
    trackdb.add_predictions(conn, info["trial_id"], 0, "live", ts, [None] * 5, [2.0] * 5, [0.6] * 5, p_up=[0.6] * 5)
    ids = [r[0] for r in _rows(conn)]
    conn.execute("DROP TRIGGER prediction_journal_no_update")
    conn.execute("UPDATE prediction_journal SET y_pred = 3.0 WHERE journal_id = ?", (ids[2],))
    conn.commit()
    res = journal.verify(conn)
    assert res["ok"] is False and res["first_bad"] == ids[2] and res["reason"] == "hash_mismatch"
    conn.execute("DROP TRIGGER prediction_journal_no_delete")
    conn.execute("UPDATE prediction_journal SET y_pred = 2.0 WHERE journal_id = ?", (ids[2],))      # on remet la valeur : la chaîne redevient valide
    conn.commit()
    assert journal.verify(conn)["ok"] is True
    conn.execute("DELETE FROM prediction_journal WHERE journal_id = ?", (ids[1],))
    conn.commit()
    res = journal.verify(conn)
    assert res["ok"] is False and res["first_bad"] == ids[2] and res["reason"] == "prev_mismatch"


def test_seal_existing_adds_backfill_rows_once(seeded):
    conn, info, _ = seeded
    tid = info["trial_id"]
    # lignes live écrites AVANT le journal (insertion directe, sans crochet)
    conn.execute("INSERT INTO prediction (trial_id, ts, fold_index, split, y_true, y_pred, y_proba, path_id, p_up) VALUES (?, '2026-12-01 00:00:00', 0, 'live', 1.0, 2.0, 0.6, -1, 0.6)", (tid,))
    conn.execute("INSERT INTO prediction (trial_id, ts, fold_index, split, y_true, y_pred, y_proba, path_id, p_up) VALUES (?, '2026-12-02 00:00:00', 0, 'live', NULL, 1.0, 0.6, -1, 0.4)", (tid,))
    conn.commit()
    res = journal.seal_existing(conn)
    assert res["sealed"] == 2 and res["outcomes"] == 1
    kinds = [(r[1], r[2]) for r in _rows(conn)]
    assert kinds.count(("signal", "backfill")) == 2 and kinds.count(("outcome", "backfill")) == 1
    assert journal.seal_existing(conn)["sealed"] == 0                                            # idempotent
    assert journal.verify(conn)["ok"] is True


def test_journal_failure_never_blocks_prediction_writes(seeded):
    conn, info, _ = seeded
    conn.execute("DROP TABLE prediction_journal")
    conn.commit()
    trackdb.add_predictions(conn, info["trial_id"], 0, "live", ["2027-02-01 00:00:00"], [None], [2.0], [0.6], p_up=[0.6])
    trackdb.update_prediction_outcome(conn, info["trial_id"], "2027-02-01 00:00:00", 1.0, 3)
    assert conn.execute("SELECT y_true FROM prediction WHERE split = 'live' AND ts LIKE '2027-02-01%'").fetchone()[0] == 1.0


def test_non_live_predictions_are_not_journaled(seeded):
    conn, _, _ = seeded
    assert conn.execute("SELECT COUNT(*) FROM prediction_journal").fetchone()[0] == 0       # le run synthétique (test, holdout) n'a rien journalisé


def test_model_hash_handles_missing_files(tmp_path):
    assert journal.model_hash(None) is None and journal.model_hash(str(tmp_path / "absent.joblib")) is None
