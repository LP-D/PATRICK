"""Persistance des stratégies et des ordres (migration 0029)."""
from __future__ import annotations

import pytest

from patrick.fund import store


def _order(strategy_id, **kw):
    base = {"strategy_id": strategy_id, "position_id": "pos_a", "ts": "2026-01-07", "action": "open",
            "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4.0, "price": 700.0,
            "price_source": "market", "currency": "EUR", "fx_rate": 1.0, "fees": 1.0,
            "fees_source": "estimated", "fee_seed": 7, "spec": {"leverage": 5}, "note": None}
    base.update(kw)
    return base


def test_migration_creates_the_fund_tables(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"fund_strategy", "fund_order", "fund_price", "fund_price_meta"} <= tables


def test_create_list_rename_archive_delete_strategy(conn):
    sid = store.create_strategy(conn, "  Macro CTO ", "CTO", "100 000,50", "2026-01-05")
    s = store.get_strategy(conn, sid)
    assert s["name"] == "Macro CTO" and s["wrapper"] == "CTO" and s["initial_capital"] == 100_000.5
    assert s["base_currency"] == "EUR" and s["archived"] == 0
    other = store.create_strategy(conn, "Actions PEA", "PEA", 50_000, "2026-02-02")
    assert [x["strategy_id"] for x in store.list_strategies(conn)] == [sid, other]
    store.update_strategy(conn, sid, name="Macro 2", archived=1)
    assert store.get_strategy(conn, sid)["name"] == "Macro 2"
    assert [x["strategy_id"] for x in store.list_strategies(conn)] == [other]
    assert len(store.list_strategies(conn, include_archived=True)) == 2
    store.delete_strategy(conn, sid)
    assert store.get_strategy(conn, sid) is None


@pytest.mark.parametrize("args, message", [
    (("", "CTO", 1000, "2026-01-05"), "nom"),
    (("x", "AV", 1000, "2026-01-05"), "enveloppe"),
    (("x", "CTO", 0, "2026-01-05"), "positif"),
    (("x", "CTO", "abc", "2026-01-05"), "capital invalide"),
    (("x", "CTO", float("inf"), "2026-01-05"), "positif"),
    (("x", "CTO", 1000, "pas une date"), "date invalide"),
    (("x", "CTO", 1000, "2999-01-01"), "futur"),
    (("x", "PEA", 150_000.01, "2026-01-05"), "plafond"),
])
def test_strategy_validation(conn, args, message):
    with pytest.raises(store.FundError, match=message):
        store.create_strategy(conn, *args)


def test_pea_accepts_exactly_the_deposit_cap(conn):
    assert store.create_strategy(conn, "PEA plein", "PEA", 150_000, "2026-01-05")


def test_update_strategy_rejects_unknown_fields_and_blank_name(conn):
    sid = store.create_strategy(conn, "A", "CTO", 1000, "2026-01-05")
    with pytest.raises(store.FundError, match="non modifiable"):
        store.update_strategy(conn, sid, wrapper="PEA")
    with pytest.raises(store.FundError, match="nom"):
        store.update_strategy(conn, sid, name="  ")


def test_orders_roundtrip_update_and_position_delete(conn):
    sid = store.create_strategy(conn, "A", "CTO", 100_000, "2026-01-05")
    first = store.insert_order(conn, _order(sid))
    second = store.insert_order(conn, _order(sid, ts="2026-01-09", action="reduce", quantity=1.0, spec={}))
    other = store.insert_order(conn, _order(sid, position_id="pos_b", symbol="TTE.PA"))
    orders = store.list_orders(conn, sid)
    assert [o["order_id"] for o in orders] == [first, other, second]      # triés par date puis par identifiant
    assert orders[0]["spec"] == {"leverage": 5} and orders[0]["fee_seed"] == 7
    store.update_order(conn, first, _order(sid, quantity=6.0, spec={"leverage": 3}))
    assert store.get_order(conn, first)["quantity"] == 6.0 and store.get_order(conn, first)["spec"] == {"leverage": 3}
    assert store.delete_position(conn, "pos_a") == 2
    assert [o["order_id"] for o in store.list_orders(conn, sid)] == [other]
    assert store.get_order(conn, 9999) is None


def test_deleting_a_strategy_removes_its_orders(conn):
    sid = store.create_strategy(conn, "A", "CTO", 100_000, "2026-01-05")
    store.insert_order(conn, _order(sid))
    store.delete_strategy(conn, sid)
    assert conn.execute("SELECT COUNT(*) FROM fund_order").fetchone()[0] == 0
