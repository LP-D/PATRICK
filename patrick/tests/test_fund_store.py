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


# --- date de dernière modification (migration 0033) : sert au partage des fonds entre deux PC -------------------

_OLD = "2000-01-01 00:00:00.000"


def _stamp(conn, sid):
    return conn.execute("SELECT updated_at FROM fund_strategy WHERE strategy_id = ?", (sid,)).fetchone()[0]


def _aged(conn, sid):
    conn.execute("UPDATE fund_strategy SET updated_at = ? WHERE strategy_id = ?", (_OLD, sid))
    conn.commit()
    return sid


def test_a_new_strategy_carries_a_modification_stamp(conn):
    sid = store.create_strategy(conn, "A", "CTO", 1000, "2026-01-05")
    assert _stamp(conn, sid) > "2020-01-01"


@pytest.mark.parametrize("change", [
    lambda c, sid: store.update_strategy(c, sid, name="Renommée"),
    lambda c, sid: store.update_strategy(c, sid, archived=1),
    lambda c, sid: store.insert_order(c, _order(sid, position_id="pos_new")),
    lambda c, sid: store.update_order(c, store.list_orders(c, sid)[0]["order_id"], _order(sid, quantity=9.0)),
    lambda c, sid: store.delete_position(c, "pos_a"),
], ids=["rename", "archive", "new order", "corrected order", "deleted position"])
def test_every_change_of_a_strategy_refreshes_its_stamp(conn, change):
    sid = store.create_strategy(conn, "A", "CTO", 100_000, "2026-01-05")
    store.insert_order(conn, _order(sid))
    other = store.create_strategy(conn, "B", "CTO", 100_000, "2026-01-05")
    _aged(conn, sid)
    _aged(conn, other)

    change(conn, sid)

    assert _stamp(conn, sid) > _OLD
    assert _stamp(conn, other) == _OLD                    # les autres stratégies ne bougent pas


def test_deleting_a_strategy_leaves_a_dated_tombstone(conn):
    sid = store.create_strategy(conn, "A", "CTO", 1000, "2026-01-05")
    store.delete_strategy(conn, sid)
    row = conn.execute("SELECT strategy_id, deleted_at FROM fund_deleted").fetchall()
    assert [r[0] for r in row] == [sid] and row[0][1] > "2020-01-01"


# --- réglages du pilote automatique (migration 0036) --------------------------------------------------------------

def test_autopilot_settings_roundtrip_touch_the_strategy_and_can_be_cleared(conn):
    sid = store.create_strategy(conn, "A", "CTO", 1000, "2026-01-05")
    assert store.get_autopilot(conn, sid) is None
    _aged(conn, sid)

    store.set_autopilot(conn, sid, {"enabled": True, "settings": {"tier": "large"}})

    assert store.get_autopilot(conn, sid) == {"enabled": True, "settings": {"tier": "large"}}
    assert _stamp(conn, sid) > _OLD                                    # la politique voyage avec la stratégie : elle la date
    assert "autopilot_json" not in store.get_strategy(conn, sid)       # jamais exposée dans la stratégie elle-même
    store.set_autopilot(conn, sid, None)
    assert store.get_autopilot(conn, sid) is None


def test_autopilot_settings_of_an_unknown_strategy_are_refused(conn):
    with pytest.raises(store.FundError, match="introuvable"):
        store.set_autopilot(conn, "str_inconnue", {"enabled": True})
    assert store.get_autopilot(conn, "str_inconnue") is None
