"""Estimation des frais (spec §8) : reproductible, commissions déterministes."""
from __future__ import annotations

import pytest

from patrick.fund import fees


def test_estimate_is_reproducible_and_future_commission_is_fixed():
    ctx = fees.FeeContext(kind="future", notional_base=500_000.0, quantity=2.0, currency="USD",
                          commission_per_contract_base=2.0, tick_bps=0.5)
    a = fees.estimate_fees(ctx, fees.make_seed("s", "p", "2026-01-06", 1))
    b = fees.estimate_fees(ctx, fees.make_seed("s", "p", "2026-01-06", 1))
    assert a == b and a.commission == 4.0 and a.fx > 0
    c = fees.estimate_fees(ctx, fees.make_seed("s", "p", "2026-01-06", 2))
    assert c.spread != a.spread and c.commission == a.commission


def test_seed_depends_on_every_part():
    assert fees.make_seed("a", "b") == fees.make_seed("a", "b")
    assert fees.make_seed("a", "b") != fees.make_seed("a", "c")


def test_equity_commission_has_a_one_euro_floor_then_scales():
    small = fees.estimate_fees(fees.FeeContext(kind="equity", notional_base=1_000.0, quantity=1, currency="EUR"), 1)
    big = fees.estimate_fees(fees.FeeContext(kind="equity", notional_base=10_000.0, quantity=10, currency="EUR"), 1)
    assert small.commission == 1.0 and big.commission == pytest.approx(5.0)
    assert small.fx == 0.0


def test_etf_spread_is_three_halves_of_a_large_cap_for_the_same_draw():
    kw = {"notional_base": 10_000.0, "quantity": 10, "currency": "EUR", "adv_notional_base": 50_000_000.0}
    large = fees.estimate_fees(fees.FeeContext(kind="equity", **kw), 3)
    etf = fees.estimate_fees(fees.FeeContext(kind="etf", **kw), 3)
    assert etf.spread / large.spread == pytest.approx(3.0 / 2.0)
    thin = fees.estimate_fees(fees.FeeContext(kind="equity", **{**kw, "adv_notional_base": 1_000_000.0}), 3)
    assert thin.spread > large.spread * 4       # action peu liquide : médiane 8 bps et plus grande participation


def test_cfd_has_no_commission_and_foreign_currency_pays_the_conversion_fee():
    eur = fees.estimate_fees(fees.FeeContext(kind="cfd", notional_base=100_000.0, quantity=10, currency="EUR",
                                             fee_class="cfd_index"), 5)
    usd = fees.estimate_fees(fees.FeeContext(kind="cfd", notional_base=100_000.0, quantity=10, currency="USD",
                                             fee_class="cfd_index"), 5)
    assert eur.commission == 0.0 and eur.fx == 0.0
    assert usd.fx == pytest.approx(100.0) and usd.spread == eur.spread
    assert usd.total == pytest.approx(usd.spread + usd.fx, abs=0.01)


def test_larger_derivative_orders_pay_a_larger_spread_per_unit_of_notional():
    def spread_bps(notional):
        b = fees.estimate_fees(fees.FeeContext(kind="cfd", notional_base=notional, quantity=1, currency="EUR",
                                               fee_class="cfd_index"), 11)
        return b.spread / notional * 1e4
    assert spread_bps(5_000_000.0) > spread_bps(10_000.0)


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="inconnu"):
        fees.estimate_fees(fees.FeeContext(kind="swap", notional_base=1.0, quantity=1, currency="EUR"), 1)
