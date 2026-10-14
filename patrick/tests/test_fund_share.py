"""Partage des fonds entre deux PC : fusion par stratégie (la plus récente l'emporte), suppressions datées,
cotations en union. Chaque « PC » est une base à part ; le fichier échangé est celui de `export_funds`."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from patrick.fund import share, store
from patrick.tracking import db as trackdb

OLD, MID, NEW = "2026-03-01 10:00:00.000", "2026-03-02 10:00:00.000", "2026-03-03 10:00:00.000"


class PC:
    def __init__(self, tmp_path: Path, name: str):
        self.dir = tmp_path / name
        self.dir.mkdir()
        self.path = str(self.dir / "patrick.db")
        self.conn = trackdb.connect(self.path)

    def strategy(self, name="A", *, stamp=MID, orders=1, rule=False) -> str:
        sid = store.create_strategy(self.conn, name, "CTO", 100_000, "2026-01-05")
        for i in range(orders):
            store.insert_order(self.conn, _order(sid, position_id=f"pos_{i}", symbol=f"S{i}.PA", quantity=i + 1.0))
        if rule:
            self.conn.execute("INSERT INTO fund_rule (rule_id, strategy_id, name, config_json) VALUES (?, ?, 'r', '{}')",
                              (f"rule_{sid}", sid))
        self.stamp(sid, stamp)
        return sid

    def stamp(self, sid: str, value: str) -> None:
        self.conn.execute("UPDATE fund_strategy SET updated_at = ? WHERE strategy_id = ?", (value, sid))
        self.conn.commit()

    def price(self, symbol: str, days: dict[str, float], *, refreshed="2026-03-01 00:00:00", currency="EUR") -> None:
        for day, close in days.items():
            self.conn.execute("INSERT OR REPLACE INTO fund_price (symbol, day, open, high, low, close) "
                              "VALUES (?, ?, ?, ?, ?, ?)", (symbol, day, close, close, close, close))
        self.conn.execute("INSERT OR REPLACE INTO fund_price_meta (symbol, currency, refreshed_at) VALUES (?, ?, ?)",
                          (symbol, currency, refreshed))
        self.conn.commit()

    def file(self) -> Path:
        out = self.dir / "funds.db"
        out.unlink(missing_ok=True)
        share.export_funds(self.path, out)
        return out

    def merge(self, other: PC, **kw) -> dict:
        return share.merge_funds(self.path, other.file(), backup_dir=str(self.dir / "bk"), **kw)

    def names(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT strategy_id, name FROM fund_strategy"))

    def orders(self, sid: str) -> list[tuple]:
        return [(o["symbol"], o["quantity"]) for o in store.list_orders(self.conn, sid)]

    def backups(self) -> list[Path]:
        return sorted((self.dir / "bk").glob("*.json"))


def _order(strategy_id, **kw):
    base = {"strategy_id": strategy_id, "position_id": "pos_a", "ts": "2026-01-07", "action": "open",
            "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4.0, "price": 700.0,
            "price_source": "market", "currency": "EUR", "fx_rate": 1.0, "fees": 1.0,
            "fees_source": "estimated", "fee_seed": 7, "spec": {}, "note": None}
    base.update(kw)
    return base


@pytest.fixture
def pcs(tmp_path):
    return PC(tmp_path, "pc1"), PC(tmp_path, "pc2")


def test_a_strategy_travels_with_its_orders_rules_and_stamp(pcs):
    a, b = pcs
    sid = a.strategy("Mes fonds", stamp=NEW, orders=3, rule=True)
    b.strategy("Déjà là", orders=5)                       # `b` a déjà des ordres : les identifiants d'ordre divergent

    out = b.merge(a)

    assert out["imported"] == [sid] and out["orders"] == 3
    assert b.names()[sid] == "Mes fonds"
    assert b.orders(sid) == [("S0.PA", 1.0), ("S1.PA", 2.0), ("S2.PA", 3.0)]        # l'ordre d'origine est gardé
    assert b.conn.execute("SELECT updated_at FROM fund_strategy WHERE strategy_id = ?", (sid,)).fetchone()[0] == NEW
    assert b.conn.execute("SELECT COUNT(*) FROM fund_rule WHERE strategy_id = ?", (sid,)).fetchone()[0] == 1
    assert len(b.names()) == 2


def test_merging_twice_changes_nothing(pcs):
    a, b = pcs
    a.strategy("A", orders=2)
    b.merge(a)
    before = share.fingerprint(b.path)

    out = b.merge(a)

    assert out["imported"] == out["replaced"] == out["deleted"] == [] and out["orders"] == 0
    assert share.fingerprint(b.path) == before
    assert b.backups() == []


def test_two_pcs_with_their_own_strategies_end_with_both(pcs):
    a, b = pcs
    sa = a.strategy("De A")
    sb = b.strategy("De B")

    a.merge(b)
    b.merge(a)

    assert a.names() == b.names() == {sa: "De A", sb: "De B"}
    assert share.fingerprint(a.path) == share.fingerprint(b.path)


def test_the_most_recent_version_of_a_strategy_wins_and_the_loser_is_saved(pcs):
    a, b = pcs
    sid = a.strategy("Version ancienne", stamp=OLD, orders=1)
    b.merge(a)
    b.conn.execute("UPDATE fund_strategy SET name = 'Version récente' WHERE strategy_id = ?", (sid,))
    store.insert_order(b.conn, _order(sid, position_id="pos_x", symbol="NEW.PA"))      # touche la stratégie : date = maintenant

    out_a = a.merge(b)                                    # a est plus ancienne : remplacée
    assert out_a["replaced"] == [sid] and a.names()[sid] == "Version récente"
    assert ("NEW.PA", 4.0) in a.orders(sid) and len(a.orders(sid)) == 2
    saved = json.loads(a.backups()[0].read_text(encoding="utf-8"))
    assert saved["fund_strategy"][0]["name"] == "Version ancienne" and len(saved["fund_order"]) == 1

    out_b = b.merge(a)                                    # a et b sont maintenant identiques : rien à faire
    assert out_b["replaced"] == [] and b.backups() == []


def test_an_older_remote_version_never_replaces_the_local_one(pcs):
    a, b = pcs
    sid = a.strategy("Ancienne", stamp=OLD)
    b.merge(a)
    b.conn.execute("UPDATE fund_strategy SET name = 'Locale', updated_at = ? WHERE strategy_id = ?", (NEW, sid))
    b.conn.commit()

    out = b.merge(a)

    assert out["replaced"] == [] and b.names()[sid] == "Locale"


def test_a_tie_keeps_the_local_version(pcs):
    a, b = pcs
    sid = a.strategy("Chez A", stamp=MID)
    b.merge(a)
    b.conn.execute("UPDATE fund_strategy SET name = 'Chez B' WHERE strategy_id = ?", (sid,))
    b.conn.commit()

    assert b.merge(a)["replaced"] == [] and b.names()[sid] == "Chez B"


def test_a_deletion_travels_unless_the_strategy_was_modified_afterwards(pcs):
    a, b = pcs
    gone, kept = a.strategy("À supprimer", stamp=OLD), a.strategy("À garder", stamp=OLD)
    b.merge(a)
    store.delete_strategy(a.conn, gone)                   # a supprime les deux...
    store.delete_strategy(a.conn, kept)
    b.stamp(kept, "2999-01-01 00:00:00.000")              # ...mais b a modifié l'une après coup

    out = b.merge(a)

    assert out["deleted"] == [gone] and set(b.names()) == {kept}
    assert len(b.backups()) == 1 and "supprime" in b.backups()[0].name
    a.merge(b)                                            # la modification plus récente ressuscite la stratégie chez a
    assert kept in a.names() and a.conn.execute("SELECT COUNT(*) FROM fund_deleted WHERE strategy_id = ?",
                                                (kept,)).fetchone()[0] == 0
    assert gone not in a.names()


def test_a_strategy_deleted_here_is_not_resurrected_by_an_older_copy(pcs):
    a, b = pcs
    sid = a.strategy("Supprimée ici", stamp=OLD)
    b.merge(a)
    store.delete_strategy(b.conn, sid)

    out = b.merge(a)

    assert out["imported"] == [] and b.names() == {}


def test_a_deletion_is_remembered_so_it_reaches_a_third_pc(tmp_path):
    a, b, c = PC(tmp_path, "pc1"), PC(tmp_path, "pc2"), PC(tmp_path, "pc3")
    sid = a.strategy("Éphémère", stamp=OLD)
    b.merge(a)
    c.merge(a)
    store.delete_strategy(a.conn, sid)
    b.merge(a)                                            # b apprend la suppression et la retransmet

    out = c.merge(b)

    assert out["deleted"] == [sid] and c.names() == {}


def test_prices_are_a_union_and_a_more_recent_refresh_replaces_the_values(pcs):
    a, b = pcs
    a.price("AAA", {"2026-03-02": 10.0, "2026-03-03": 11.0}, refreshed="2026-03-10 00:00:00")
    a.price("BBB", {"2026-03-02": 20.0}, refreshed="2026-03-10 00:00:00")
    b.price("AAA", {"2026-03-01": 9.0, "2026-03-02": 99.0}, refreshed="2026-03-05 00:00:00")      # plus ancien que a
    b.price("BBB", {"2026-03-02": 77.0, "2026-03-04": 21.0}, refreshed="2026-03-20 00:00:00")      # plus récent que a
    b.price("CCC", {"2026-03-02": 5.0}, refreshed="2026-03-01 00:00:00")

    out = a.merge(b)

    def closes(symbol):
        return dict(a.conn.execute("SELECT day, close FROM fund_price WHERE symbol = ?", (symbol,)))
    assert closes("AAA") == {"2026-03-01": 9.0, "2026-03-02": 10.0, "2026-03-03": 11.0}      # a garde ses valeurs, gagne un jour
    assert closes("BBB") == {"2026-03-02": 77.0, "2026-03-04": 21.0}                          # b plus récent : ses valeurs, a n'en perd aucune
    assert closes("CCC") == {"2026-03-02": 5.0}
    assert out["prices_newer"] == 2                                                           # BBB et CCC
    assert a.conn.execute("SELECT refreshed_at FROM fund_price_meta WHERE symbol = 'BBB'").fetchone()[0] == "2026-03-20 00:00:00"
    assert a.conn.execute("SELECT refreshed_at FROM fund_price_meta WHERE symbol = 'AAA'").fetchone()[0] == "2026-03-10 00:00:00"


def test_the_merge_is_all_or_nothing(pcs, monkeypatch):
    a, b = pcs
    a.strategy("Première")
    a.strategy("Seconde")
    real = share._import_strategy
    calls = []

    def flaky(conn, sid):
        calls.append(sid)
        if len(calls) == 2:
            raise RuntimeError("disque plein")
        return real(conn, sid)
    monkeypatch.setattr(share, "_import_strategy", flaky)

    with pytest.raises(RuntimeError, match="disque plein"):
        b.merge(a)

    assert b.names() == {} and b.conn.execute("SELECT COUNT(*) FROM fund_order").fetchone()[0] == 0


def test_a_file_from_a_newer_or_older_version_is_refused_with_a_clear_message(pcs):
    a, b = pcs
    a.strategy("A")
    newer, older = a.file(), a.dir / "old.db"
    sqlite3.connect(newer).execute("INSERT INTO schema_version (version) VALUES (9999)").connection.commit()
    share.export_funds(a.path, older)
    conn = sqlite3.connect(older)
    conn.execute("DELETE FROM schema_version WHERE version >= 33")
    conn.commit()
    conn.close()

    with pytest.raises(share.FundShareError, match="mets PATRICK à jour sur ce PC"):
        share.merge_funds(b.path, newer, backup_dir=str(b.dir / "bk"))
    with pytest.raises(share.FundShareError, match="mets PATRICK à jour sur l'autre PC"):
        share.merge_funds(b.path, older, backup_dir=str(b.dir / "bk"))
    assert b.names() == {}


def test_the_fingerprint_follows_strategies_and_deletions_but_not_prices(pcs):
    a, _ = pcs
    sid = a.strategy("A", stamp=OLD)
    first = share.fingerprint(a.path)

    a.price("AAA", {"2026-03-02": 10.0})
    assert share.fingerprint(a.path) == first

    store.update_strategy(a.conn, sid, name="B")
    second = share.fingerprint(a.path)
    assert second != first

    store.delete_strategy(a.conn, sid)
    assert share.fingerprint(a.path) not in (first, second)


def test_the_exported_file_holds_only_the_funds(pcs):
    a, _ = pcs
    a.strategy("A")
    a.conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('acc', 'perso', 'PEA', 'real')")
    a.conn.commit()

    out = a.file()

    conn = sqlite3.connect(out)
    assert conn.execute("SELECT COUNT(*) FROM wealth_account").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fund_strategy").fetchone()[0] == 1
    conn.close()
