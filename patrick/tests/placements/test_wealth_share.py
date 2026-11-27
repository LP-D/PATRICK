"""Patrimoine partagé entre PC sans PC de référence : fusion ligne par ligne (`patrick.wealth.share`). Chaque « PC » est une
base à part ; le fichier échangé est celui de `export_wealth`. Les deux PC doivent toujours aboutir au même patrimoine."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from patrick.tracking import db as trackdb
from patrick.wealth import ledger, share

OLD, MID, NEW = "2026-03-01 10:00:00.000", "2026-03-02 10:00:00.000", "2026-03-03 10:00:00.000"


class PC:
    def __init__(self, tmp_path: Path, name: str, copy_of: PC | None = None):
        self.dir = tmp_path / name
        self.dir.mkdir()
        self.path = str(self.dir / "patrick.db")
        if copy_of is not None:                    # copie complète (la base est en WAL : pas de simple copie de fichier)
            copy_of.conn.commit()
            target = sqlite3.connect(self.path)
            copy_of.conn.backup(target)
            target.close()
        self.conn = trackdb.connect(self.path)

    def file(self) -> Path:
        out = self.dir / "wealth.db"
        out.unlink(missing_ok=True)
        share.export_wealth(self.path, out)
        return out

    def merge(self, other: PC) -> dict:
        return share.merge_wealth(self.path, other.file(), backup_dir=str(self.dir / "bk"))

    def deposit(self, account_id: str, ts: str, amount: float, note: str | None = None) -> int:
        return ledger.add_movement(self.conn, account_id, {"ts": ts, "kind": "deposit", "amount": amount, "note": note})

    def stamp(self, table: str, where: str, value: str) -> None:
        self.conn.execute(f"UPDATE {table} SET updated_at = ? WHERE {where}", (value,))
        self.conn.commit()

    def state(self) -> dict:
        """Ce qui doit être identique sur tous les PC (les `movement_id` sont propres à chaque base)."""
        accounts = self.conn.execute("SELECT account_id, name, kind, mode, archived, updated_at FROM wealth_account "
                                     "ORDER BY account_id").fetchall()
        movements = self.conn.execute("SELECT uid, account_id, ts, kind, amount, note, updated_at FROM wealth_movement "
                                      "ORDER BY uid").fetchall()
        return {"accounts": accounts, "movements": movements}

    def amounts(self) -> list[float]:
        return sorted(r[0] for r in self.conn.execute("SELECT amount FROM wealth_movement"))


def _quiet(res: dict) -> bool:
    return not any(v for k, v in res.items() if k != "backup")


@pytest.fixture
def pair(tmp_path):
    """Deux PC qui partent de la même copie du patrimoine (celle que l'ancien PC de référence publiait)."""
    a = PC(tmp_path, "a")
    acc = ledger.create_account(a.conn, "PEA perso", "PEA")
    a.deposit(acc, "2026-01-02", 1000.0)
    a.deposit(acc, "2026-01-03", 500.0)
    b = PC(tmp_path, "b", copy_of=a)
    return a, b, acc


def _sync(a: PC, b: PC) -> None:
    a.merge(b)
    b.merge(a)


def test_movements_added_on_each_pc_end_up_on_both(pair):
    a, b, acc = pair
    a.deposit(acc, "2026-02-01", 10.0)
    b.deposit(acc, "2026-02-02", 20.0)

    res = a.merge(b)
    assert res["movements_added"] == 1 and res["backup"] is None
    b.merge(a)

    assert a.state() == b.state()
    assert a.amounts() == [10.0, 20.0, 500.0, 1000.0]
    assert _quiet(a.merge(b)) and _quiet(b.merge(a))                  # deuxième échange : plus rien à faire


def test_a_deletion_reaches_the_other_pc_and_is_never_resurrected(pair):
    a, b, _acc = pair
    mid = a.conn.execute("SELECT movement_id FROM wealth_movement WHERE amount = 500").fetchone()[0]
    ledger.delete_movement(a.conn, mid)

    assert a.merge(b)["movements_added"] == 0                          # b l'a encore : ce n'est pas un ajout
    res = b.merge(a)

    assert res["movements_deleted"] == 1 and json.loads(Path(res["backup"]).read_text(encoding="utf-8"))
    assert a.amounts() == b.amounts() == [1000.0]
    _sync(a, b)
    assert a.amounts() == b.amounts() == [1000.0]


def test_a_movement_changed_after_its_deletion_elsewhere_survives(pair, tmp_path):
    a, b, _acc = pair
    other = ledger.create_account(b.conn, "CTO", "CTO")
    b.merge(a)
    a.merge(b)
    uid = a.conn.execute("SELECT uid FROM wealth_movement WHERE amount = 500").fetchone()[0]
    ledger.delete_movement(a.conn, a.conn.execute("SELECT movement_id FROM wealth_movement WHERE uid = ?", (uid,)).fetchone()[0])
    a.conn.execute("UPDATE wealth_deleted SET deleted_at = ? WHERE uid = ?", (MID, uid))
    a.conn.commit()
    mid_b = b.conn.execute("SELECT movement_id FROM wealth_movement WHERE uid = ?", (uid,)).fetchone()[0]
    ledger.transfer_movement(b.conn, mid_b, other)                      # modifié sur b APRÈS la suppression sur a
    b.stamp("wealth_movement", f"uid = '{uid}'", NEW)

    _sync(a, b)

    assert a.state() == b.state()
    assert a.conn.execute("SELECT account_id FROM wealth_movement WHERE uid = ?", (uid,)).fetchone() == (other,)
    assert a.conn.execute("SELECT COUNT(*) FROM wealth_deleted WHERE uid = ?", (uid,)).fetchone() == (0,)


def test_the_same_account_changed_on_both_pcs_keeps_the_latest_change(pair):
    a, b, acc = pair
    ledger.update_account(a.conn, acc, name="PEA (a)")
    a.stamp("wealth_account", f"account_id = '{acc}'", MID)
    ledger.update_account(b.conn, acc, name="PEA (b)")
    b.stamp("wealth_account", f"account_id = '{acc}'", NEW)

    res = a.merge(b)
    b.merge(a)

    assert res["accounts_updated"] == 1
    assert a.state() == b.state() and ledger.get_account(a.conn, acc)["name"] == "PEA (b)"
    backup = json.loads(Path(res["backup"]).read_text(encoding="utf-8"))
    assert backup[0]["account"]["name"] == "PEA (a)"                    # la version écartée est gardée


def test_equal_stamps_still_converge(pair):
    a, b, acc = pair
    for pc, name in ((a, "x"), (b, "y")):
        ledger.update_account(pc.conn, acc, name=name)
        pc.stamp("wealth_account", f"account_id = '{acc}'", MID)

    _sync(a, b)

    assert a.state() == b.state()


def test_the_same_statement_imported_on_both_pcs_is_counted_once(pair):
    a, b, acc = pair
    for pc in (a, b):                                                   # deux imports du même relevé avant tout échange
        pc.deposit(acc, "2026-02-10", 200.0, note="Versement LCL")
        pc.deposit(acc, "2026-02-10", 200.0, note="Versement LCL")      # deux versements identiques le même jour
        pc.deposit(acc, "2026-02-11", 50.0)

    res = a.merge(b)
    b.merge(a)

    assert res["duplicates"] == 3 and res["movements_added"] == 0
    assert res["movements_updated"] == 0 and res["backup"] is None     # seule la date de saisie diffère : rien à signaler
    assert a.state() == b.state()
    assert a.amounts() == [50.0, 200.0, 200.0, 500.0, 1000.0]
    assert _quiet(a.merge(b)) and _quiet(b.merge(a))


def test_a_deleted_account_disappears_with_its_movements(pair):
    a, b, acc = pair
    ledger.delete_account(a.conn, acc)

    res = b.merge(a)

    assert res["accounts_deleted"] == 1
    assert b.state() == a.state() == {"accounts": [], "movements": []}
    _sync(a, b)
    assert b.state() == {"accounts": [], "movements": []}


def test_a_deleted_account_comes_back_when_the_other_pc_added_to_it_afterwards(pair):
    a, b, acc = pair
    ledger.delete_account(a.conn, acc)
    a.conn.execute("UPDATE wealth_deleted SET deleted_at = ? WHERE uid = ?", (MID, acc))
    a.conn.commit()
    b.deposit(acc, "2026-02-20", 75.0)
    b.stamp("wealth_movement", "amount = 75", NEW)

    a.merge(b)
    b.merge(a)

    assert a.state() == b.state()
    assert a.amounts() == [75.0, 500.0, 1000.0]                         # le compte revient avec tous ses mouvements


def test_identical_copies_get_identical_ids_for_movements_entered_without_the_ledger(tmp_path):
    a = PC(tmp_path, "a")
    a.conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode, created_at) "
                   "VALUES ('acc_x', 'x', 'PEA', 'real', '2026-01-01 08:00:00')")
    a.conn.execute("INSERT INTO wealth_movement (account_id, ts, kind, amount, created_at) "
                   "VALUES ('acc_x', '2026-01-02', 'deposit', 10, '2026-01-02 09:30:00')")
    b = PC(tmp_path, "b", copy_of=a)

    share.ensure_identities(a.path)
    share.ensure_identities(b.path)

    uid = a.conn.execute("SELECT uid FROM wealth_movement").fetchone()[0]
    assert uid == b.conn.execute("SELECT uid FROM wealth_movement").fetchone()[0] == "mv_acc_x_1_20260102T093000"
    assert a.merge(b) == {**dict.fromkeys(("accounts_added", "accounts_updated", "accounts_deleted", "movements_added",
                                           "movements_updated", "movements_deleted", "duplicates"), 0), "backup": None}


def test_adoption_replaces_the_local_wealth_and_keeps_a_backup(pair):
    a, b, acc = pair
    ledger.create_account(b.conn, "local seulement", "CTO")
    a.deposit(acc, "2026-02-01", 10.0)

    res = share.adopt_wealth(b.path, a.file(), backup_dir=str(b.dir / "bk"))

    assert (res["accounts"], res["movements"]) == (1, 3)
    assert b.state() == a.state()
    saved = json.loads(Path(res["backup"]).read_text(encoding="utf-8"))[0]
    assert sorted(r["name"] for r in saved["wealth_account"]) == ["PEA perso", "local seulement"]


def test_a_file_from_a_newer_patrick_is_refused(pair):
    a, b, _acc = pair
    f = a.file()
    conn = sqlite3.connect(f)
    conn.execute("INSERT INTO schema_version (version) VALUES (9999)")
    conn.commit()
    conn.close()

    with pytest.raises(share.WealthShareError, match="mets PATRICK à jour sur ce PC"):
        share.merge_wealth(b.path, f, backup_dir=str(b.dir / "bk"))
