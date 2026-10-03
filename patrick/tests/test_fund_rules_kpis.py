"""Règles d'enveloppe (statiques et chronologiques) et KPI d'une stratégie."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from patrick.fund import engine, kpis, rules

DAYS = pd.bdate_range("2026-01-05", periods=10)
TODAY = dt.date(2026, 1, 16)
CTO = {"strategy_id": "s", "wrapper": "CTO", "opened_on": "2026-01-05", "initial_capital": 100_000.0}
PEA = {**CTO, "wrapper": "PEA"}


def bars(closes):
    n = len(closes)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                         "volume": [1e6] * n, "dividend": [0.0] * n}, index=DAYS[:n])


def order(**kw):
    base = {"order_id": 1, "strategy_id": "s", "position_id": "p1", "ts": "2026-01-06", "action": "open",
            "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 10.0, "price": 100.0,
            "currency": "EUR", "fx_rate": 1.0, "fees": 0.0, "spec": {}}
    base.update(kw)
    return base


def test_static_checks_for_a_clean_cto_order():
    chk = rules.static_checks(CTO, order(), TODAY)
    assert chk.blocking == [] and chk.warnings == []


@pytest.mark.parametrize("strategy, overrides, expected", [
    (CTO, {"ts": "2026-02-01"}, "futur"),
    (CTO, {"ts": "2026-01-02"}, "antérieure à l'ouverture"),
    (CTO, {"quantity": 0}, "quantité"),
    (CTO, {"price": None}, "prix indisponible"),
    (CTO, {"side": "short"}, "découvert"),
    (CTO, {"instrument_kind": "etf", "side": "short"}, "découvert"),
    (PEA, {"instrument_kind": "future", "side": "long"}, "ni future ni CFD"),
    (PEA, {"instrument_kind": "cfd"}, "ni future ni CFD"),
    (PEA, {"currency": "USD"}, "euro"),
    (PEA, {"side": "short"}, "longues seulement"),
    (CTO, {"instrument_kind": "cfd", "symbol": "^GSPC", "spec": {"leverage": 25}}, "plafond 20:1"),
    (CTO, {"instrument_kind": "cfd", "symbol": "AAPL", "spec": {"leverage": 6}}, "plafond 5:1"),
    (CTO, {"instrument_kind": "cfd", "symbol": "AAPL", "spec": {"leverage": 0.5}}, "levier minimal"),
])
def test_static_blocking_rules(strategy, overrides, expected):
    chk = rules.static_checks(strategy, order(**overrides), TODAY)
    assert any(expected in m for m in chk.blocking), chk.blocking


def test_modify_needs_neither_price_nor_quantity_but_still_caps_leverage():
    ok = order(action="modify", quantity=0.0, price=None, instrument_kind="cfd", symbol="^GSPC",
               spec={"stop": 4000.0})
    assert rules.static_checks(CTO, ok, TODAY).blocking == []
    too_much = order(action="modify", quantity=0.0, price=None, instrument_kind="cfd", symbol="^GSPC",
                     spec={"leverage": 50})
    assert any("plafond" in m for m in rules.static_checks(CTO, too_much, TODAY).blocking)


def test_pea_warns_on_a_probably_ineligible_venue_but_does_not_block():
    chk = rules.static_checks(PEA, order(symbol="AAPL"), TODAY)
    assert chk.blocking == [] and any("non éligible" in m for m in chk.warnings)
    assert rules.static_checks(PEA, order(symbol="MC.PA"), TODAY).warnings == []


def test_validate_replays_the_whole_timeline_and_keeps_only_new_violations():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    small_cap = {**CTO, "initial_capital": 10_000.0}
    later = order(order_id=1, ts="2026-01-12", quantity=95.0)                # 9 500 EUR : tient dans le capital
    chk, _ = rules.validate(small_cap, [later], order(order_id=None, position_id="p2", ts="2026-01-07",
                                                       quantity=20.0), market, TODAY)
    assert any("insuffisant" in m for m in chk.blocking)                      # l'ordre antidaté casse celui du 12
    ok, result = rules.validate(small_cap, [later], order(order_id=None, position_id="p2", ts="2026-01-13",
                                                           quantity=1.0), market, TODAY)
    assert ok.blocking == [] and result.positions


def test_validate_ignores_violations_that_already_exist():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    oversold = [order(order_id=1, quantity=5.0),
                order(order_id=2, ts="2026-01-07", action="reduce", quantity=50.0)]   # anomalie déjà présente
    candidate = order(order_id=None, position_id="p2", ts="2026-01-13", quantity=1.0)
    assert rules.validate(CTO, oversold, candidate, market, TODAY)[0].blocking == []
    overdrawn = [order(order_id=1, quantity=5000.0)]          # capital dépassé : tout nouvel ordre est refusé
    assert any("insuffisant" in m for m in rules.validate(CTO, overdrawn, candidate, market, TODAY)[0].blocking)


def test_validate_replaces_the_corrected_order_instead_of_duplicating_it():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    existing = order(order_id=7, quantity=5.0)
    chk, result = rules.validate(CTO, [existing], order(order_id=7, quantity=8.0), market, TODAY)
    assert chk.blocking == [] and result.positions[0]["quantity"] == 8.0 and len(result.positions) == 1


def test_validate_warns_when_net_value_falls_below_half_the_required_margin():
    spec = {"multiplier": 50.0, "margin_per_unit": 20_000.0, "expiry": "2026-06-19",
            "fee_ctx": {"commission_per_contract_base": 2.0, "tick_bps": 0.5}}
    market = engine.MarketData(bars={"FUT": bars([5000.0] * 3 + [4000.0] * 7)})
    cand = order(order_id=None, instrument_kind="future", symbol="FUT", side="long", quantity=4.0, price=5000.0,
                 spec=spec)
    small = {**CTO, "initial_capital": 90_000.0}
    chk, _ = rules.validate(small, [], cand, market, TODAY)
    assert any("50 %" in m for m in chk.warnings)


def _result(closes, quantity=10.0):
    market = engine.MarketData(bars={"MC.PA": bars(closes)})
    return engine.simulate(CTO, [order(quantity=quantity)], market, "2026-01-16")


def test_kpis_of_a_simple_long_position():
    res = _result([100, 100, 102, 101, 105, 104, 108, 107, 110, 112])
    k = kpis.compute(CTO, res)
    assert k["nav"] == pytest.approx(100_000 + 10 * 12) and k["pnl"] == pytest.approx(120.0)
    assert k["pnl_pct"] == pytest.approx(0.0012) and k["twr"] == pytest.approx(0.0012)
    assert k["latent"] == pytest.approx(120.0) and k["realized"] == 0.0 and k["n_open_positions"] == 1
    assert k["gross_exposure_pct"] == pytest.approx(1120 / 100_120) and k["leverage"] == k["gross_exposure_pct"]
    assert k["max_drawdown"] <= 0 and k["volatility"] > 0 and k["margin_used"] == 0.0
    assert k["buying_power"] == pytest.approx(100_000 - 1000)


def test_kpis_of_a_strategy_without_orders_are_neutral_and_json_safe():
    market = engine.MarketData()
    k = kpis.compute(CTO, engine.simulate(CTO, [], market, "2026-01-16"))
    assert k["nav"] == 100_000 and k["pnl"] == 0 and k["n_open_positions"] == 0
    assert k["sharpe"] is None and k["volatility"] in (None, 0.0)
    assert k["cash"] == 100_000 and k["gross_exposure_pct"] == 0


def test_series_points_are_rounded_and_dated():
    res = _result([100.0] * 10)
    pts = kpis.series_points(res.daily)
    assert pts[0] == {"t": "2026-01-05", "nav": 100000.0, "cash": 100000.0} and len(pts) == 10
    assert kpis.series_points(pd.DataFrame()) == []


def test_an_order_dated_before_the_previous_order_of_its_position_is_refused():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    existing = [order(order_id=1, ts="2026-01-06", quantity=10.0),
                order(order_id=2, ts="2026-01-12", action="increase", quantity=5.0)]
    backdated = order(order_id=None, ts="2026-01-08", action="reduce", quantity=8.0)
    chk, _ = rules.validate(CTO, existing, backdated, market, TODAY)
    assert any("antérieure à l'ordre précédent" in m for m in chk.blocking)
    later = order(order_id=None, ts="2026-01-13", action="reduce", quantity=8.0)
    assert rules.validate(CTO, existing, later, market, TODAY)[0].blocking == []
