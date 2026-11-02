"""Journal de prédictions fusionné entre deux PC (migration 0050, ADR 0015) : chaque PC garde SA chaîne d'empreintes, les lignes de l'autre sont recopiées telles
quelles et marquées `imported_from`, vérifiées une à une. Bases légères sous `tmp_path`, jamais la vraie."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from patrick import sync_merge
from patrick.analysis import journal_view
from patrick.tracking import db, journal


def _db(path: Path) -> sqlite3.Connection:
    conn = db.connect(str(path))
    journal.ensure_triggers(conn)
    return conn


def _signal(trial_id: int, day: str, target: str = "^GSPC", p_up: float = 0.6, run_id: str = "run") -> dict:
    return {"kind": "signal", "origin": "live", "trial_id": trial_id, "run_id": run_id, "target": target, "horizon": 5, "signal_date": day,
            "y_pred": 3.0, "p_up": p_up, "model_hash": "m" * 64, "config_hash": "cfg", "recorded_at": f"{day} 22:00:00.000000"}


def _fill(conn: sqlite3.Connection, trial_id: int, days: list[str], **kw) -> None:
    journal._append(conn, [_signal(trial_id, d, **kw) for d in days])
    conn.commit()


@pytest.fixture
def pcs(tmp_path):
    """Deux PC : mêmes numéros d'essai (1) pour des signaux différents, comme deux bases indépendantes."""
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    ca, cb = _db(a), _db(b)
    _fill(ca, 1, ["2026-01-05", "2026-01-06"], run_id="run_a")
    _fill(cb, 1, ["2026-01-07", "2026-01-08", "2026-01-09"], p_up=0.4, run_id="run_b")
    return a, b, ca, cb


def _merge(dst: Path, src: Path) -> dict:
    return sync_merge.merge_databases(str(dst), str(src))


def test_the_other_pcs_rows_are_copied_as_they_are_and_marked(pcs):
    a, b, ca, cb = pcs
    before = journal.verify(ca)

    report = _merge(a, b)

    assert report["added"]["prediction_journal"] == 3
    rows = ca.execute("SELECT trial_id, signal_date, prev_hash, entry_hash, imported_from, run_id FROM prediction_journal ORDER BY journal_id").fetchall()
    assert [(r[1], r[4]) for r in rows] == [("2026-01-05", None), ("2026-01-06", None), ("2026-01-07", "import"), ("2026-01-08", "import"), ("2026-01-09", "import")]
    theirs = cb.execute("SELECT trial_id, signal_date, prev_hash, entry_hash, run_id FROM prediction_journal ORDER BY journal_id").fetchall()
    assert [(r[0], r[1], r[2], r[3], r[5]) for r in rows[2:]] == theirs                      # empreintes et trial_id inchangés : ils sont dans la charge utile hachée
    after = journal.verify(ca)
    assert after["ok"] is True and after["n"] == before["n"] == 2 and after["n_imported"] == 3 and after["head"] == before["head"]


def test_merging_twice_adds_nothing_and_a_round_trip_creates_no_duplicates(pcs):
    a, b, ca, cb = pcs
    _merge(a, b)
    assert _merge(a, b)["added"]["prediction_journal"] == 0
    _merge(b, a)                                                    # A (qui contient maintenant les lignes de B) revient vers B
    total = cb.execute("SELECT COUNT(*) FROM prediction_journal").fetchone()[0]
    assert total == 5                                               # les 3 de B sont les siennes, les 2 de A importées
    assert cb.execute("SELECT COUNT(*) FROM prediction_journal WHERE imported_from IS NULL").fetchone()[0] == 3
    assert journal.verify(cb)["ok"] is True and journal.verify(ca)["ok"] is True


def test_new_local_entries_extend_the_local_chain_not_an_imported_one(pcs):
    a, b, ca, _ = pcs
    _merge(a, b)
    local_head = journal.verify(ca)["head"]

    _fill(ca, 1, ["2026-01-12"], run_id="run_a")                      # même trial_id (1) que les lignes importées de B, autre jour

    last = ca.execute("SELECT prev_hash, imported_from FROM prediction_journal WHERE signal_date = '2026-01-12'").fetchone()
    assert last == (local_head, None)
    assert journal.verify(ca)["ok"] is True and journal.verify(ca)["n"] == 3


def test_an_imported_signal_does_not_mask_a_local_one_with_the_same_trial_id_and_day(pcs):
    a, b, ca, _ = pcs
    _merge(a, b)                                                     # B a signalé 2026-01-07 pour SON essai 1

    _fill(ca, 1, ["2026-01-07"], run_id="run_a")                      # A signale le même jour pour SON essai 1 : ne doit pas être pris pour un doublon

    days = ca.execute("SELECT imported_from FROM prediction_journal WHERE signal_date = '2026-01-07' ORDER BY journal_id").fetchall()
    assert days == [("import",), (None,)]


def test_an_altered_imported_row_is_detected(pcs):
    a, b, ca, _ = pcs
    _merge(a, b)
    ca.execute("DROP TRIGGER prediction_journal_no_update")
    ca.execute("UPDATE prediction_journal SET p_up = 0.99 WHERE signal_date = '2026-01-08'")
    ca.commit()
    out = journal.verify(ca)
    assert out["ok"] is False and out["reason"] == "imported_hash_mismatch"
    assert ca.execute("SELECT signal_date FROM prediction_journal WHERE journal_id = ?", (out["first_bad"],)).fetchone() == ("2026-01-08",)


def test_a_removed_imported_row_breaks_the_link_of_the_next_one(pcs):
    a, b, ca, _ = pcs
    _merge(a, b)
    ca.execute("DROP TRIGGER prediction_journal_no_delete")
    ca.execute("DELETE FROM prediction_journal WHERE signal_date = '2026-01-08'")
    ca.commit()
    out = journal.verify(ca)
    assert out["ok"] is False and out["reason"] == "imported_prev_missing"
    assert ca.execute("SELECT signal_date FROM prediction_journal WHERE journal_id = ?", (out["first_bad"],)).fetchone() == ("2026-01-09",)


def test_the_local_chain_is_still_checked_on_its_own(pcs):
    a, b, ca, _ = pcs
    _merge(a, b)
    ca.execute("DROP TRIGGER prediction_journal_no_update")
    ca.execute("UPDATE prediction_journal SET y_pred = 0 WHERE signal_date = '2026-01-05'")
    ca.commit()
    assert journal.verify(ca)["reason"] == "hash_mismatch"


def test_two_pcs_started_from_the_same_copy_are_reported_as_a_fork_not_a_failure(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    ca = _db(a)
    _fill(ca, 1, ["2026-01-05", "2026-01-06"])
    ca.close()
    b.write_bytes(a.read_bytes())                                    # B démarre d'une copie de A
    ca, cb = _db(a), _db(b)
    _fill(ca, 1, ["2026-01-07"], run_id="run_a")
    _fill(cb, 1, ["2026-01-07"], p_up=0.3, run_id="run_b")           # chacun prolonge la même ligne de sa façon
    _merge(a, b)
    out = journal.verify(ca)
    assert out["ok"] is True and out["n_imported"] == 1 and out["forks"] == 0       # un seul fils importé : la fourche est entre local et importé
    assert ca.execute("SELECT COUNT(*) FROM prediction_journal WHERE signal_date = '2026-01-07'").fetchone()[0] == 2


def test_the_view_counts_imported_rows_and_only_compares_local_ones_with_the_prediction_table(pcs):
    a, b, ca, _ = pcs
    _merge(a, b)
    overview = journal_view.overview(ca)
    assert overview["n_entries"] == 5 and overview["n_imported"] == 3 and overview["n_signals"] == 5
    assert overview["n_checked"] == 0                                 # aucune ligne de la table `prediction` : rien n'est comparé, et rien d'importé non plus
    csv_text = journal_view.export_csv(ca)
    lines = csv_text.splitlines()
    assert lines[0].endswith("imported_from") and sum(1 for line in lines[1:] if line.endswith(",import")) == 3
    assert journal_view.entries(ca)["items"][0]["imported_from"] == "import"
