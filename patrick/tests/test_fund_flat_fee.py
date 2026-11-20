"""Fonds, frais forfaitaires par ordre (ADR 0026) : 1 € tout compris pour un fonds réel, frais estimés pour un fonds quant. Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest

from patrick.fund import fees, service, store

TODAY = dt.date(2026, 1, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _ctx(kind: str, **kw) -> fees.FeeContext:
    return fees.FeeContext(kind=kind, notional_base=50_000.0, quantity=3, currency="USD", **kw)


@pytest.mark.parametrize("kind, extra", [
    ("equity", {"adv_notional_base": 1_000_000.0}), ("etf", {}), ("cfd", {"fee_class": "cfd_index"}),
    ("future", {"commission_per_contract_base": 2.5, "tick_bps": 1.0})])
def test_a_flat_fee_replaces_commission_spread_and_currency_cost(kind, extra):
    out = fees.estimate_fees(_ctx(kind, flat_fee=1.0, **extra), seed=7)

    assert (out.commission, out.spread, out.fx, out.total) == (1.0, 0.0, 0.0, 1.0)


def test_without_a_flat_fee_the_estimate_is_unchanged():
    ctx = _ctx("equity", adv_notional_base=1_000_000.0)

    assert fees.estimate_fees(ctx, 7) == fees.estimate_fees(fees.FeeContext(**{**ctx.__dict__, "flat_fee": None}), 7)
    assert fees.estimate_fees(ctx, 7).total > 1.0 and fees.estimate_fees(ctx, 7).fx > 0


def test_a_real_fund_charges_one_euro_per_order_whatever_the_size_and_the_currency(conn):
    sid = store.create_strategy(conn, "Réel", "CTO", 5_000, "2026-01-05", category="real", fee_flat=1.0)

    small = service.place_order(conn, {"strategy_id": sid, "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 1,
                                       "date": "2026-01-07"}, TODAY)
    dollars = service.place_order(conn, {"strategy_id": sid, "instrument_kind": "equity", "symbol": "AAPL", "side": "long", "quantity": 10,
                                         "date": "2026-01-07"}, TODAY)

    assert small["order"]["fees"] == 1.0 and dollars["order"]["fees"] == 1.0
    assert small["preview"]["fees"]["total"] == 1.0 and dollars["preview"]["fees"]["total"] == 1.0
    closed = service.place_order(conn, {"strategy_id": sid, "action": "close", "position_id": small["preview"]["position_id"],
                                        "date": "2026-01-09"}, TODAY)
    assert closed["order"]["fees"] == 1.0                        # un ordre de sortie coûte aussi 1 €


def test_a_quant_fund_keeps_its_estimated_fees(conn):
    sid = store.create_strategy(conn, "Quant", "CTO", 100_000, "2026-01-05")

    placed = service.place_order(conn, {"strategy_id": sid, "instrument_kind": "equity", "symbol": "AAPL", "side": "long", "quantity": 10,
                                        "date": "2026-01-07"}, TODAY)

    assert placed["order"]["fees"] > 1.0                          # commission, spread et frais de change


def test_the_amount_sizing_leaves_room_for_the_flat_fee(conn):
    sid = store.create_strategy(conn, "Réel", "PEA", 5_000, "2026-01-05", category="real", fee_flat=1.0)

    quote = service.quote(conn, {"strategy_id": sid, "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "amount": 1_500,
                                 "date": "2026-01-07"}, TODAY)

    order = quote["order"]
    assert quote["ok"] and order["fees"] == 1.0
    assert order["quantity"] * order["price"] * order["fx_rate"] + order["fees"] <= 1_500 + 1e-6


@pytest.mark.parametrize("value, expected", [(None, None), ("", None), (0, 0.0), (1, 1.0), ("1,5", 1.5), (100, 100.0)])
def test_check_flat_fee_accepts_a_small_amount_or_nothing(value, expected):
    assert store.check_flat_fee(value) == expected


@pytest.mark.parametrize("value", [-1, 101, "abc", float("nan"), float("inf")])
def test_check_flat_fee_refuses_nonsense(value):
    with pytest.raises(store.FundError, match="frais forfaitaires"):
        store.check_flat_fee(value)


def test_the_category_and_the_fee_are_stored_with_the_strategy_and_validated(conn):
    real = store.create_strategy(conn, "Réel", "PEA", 5_000, "2026-01-05", category="real", fee_flat=1.0)
    quant = store.create_strategy(conn, "Quant", "CTO", 100_000, "2026-01-05")

    assert (store.get_strategy(conn, real)["category"], store.get_strategy(conn, real)["fee_flat"]) == ("real", 1.0)
    assert (store.get_strategy(conn, quant)["category"], store.get_strategy(conn, quant)["fee_flat"]) == ("quant", None)
    with pytest.raises(store.FundError, match="catégorie inconnue"):
        store.create_strategy(conn, "X", "CTO", 1_000, "2026-01-05", category="exotic")
    with pytest.raises(store.FundError, match="frais forfaitaires"):
        store.create_strategy(conn, "X", "CTO", 1_000, "2026-01-05", fee_flat=-3)
