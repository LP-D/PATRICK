"""Moteur de valorisation (spec §7, §9, §10) : cas chiffrés à la main, sans réseau."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.fund.engine import MarketData, simulate

DAYS = pd.bdate_range("2026-01-05", periods=10)  # lun 5 janv. -> ven 16 janv. 2026
STRAT = {"initial_capital": 100_000.0, "opened_on": "2026-01-05"}
END = "2026-01-16"


def bars(closes, *, opens=None, highs=None, lows=None, dividends=None):
    n = len(closes)
    return pd.DataFrame({
        "open": opens or closes, "high": highs or closes, "low": lows or closes, "close": closes,
        "volume": [1e6] * n, "dividend": dividends or [0.0] * n}, index=DAYS[:n])


def order(**kw):
    base = {"order_id": 1, "strategy_id": "s", "position_id": "p1", "ts": "2026-01-06", "action": "open",
            "instrument_kind": "equity", "symbol": "AAA", "side": "long", "quantity": 10.0, "price": 100.0,
            "currency": "EUR", "fx_rate": 1.0, "fees": 0.0, "spec": {}}
    base.update(kw)
    return base


def pos_of(res, pid="p1"):
    return next(p for p in res.positions if p["position_id"] == pid)


def test_equity_usd_splits_price_and_fx_effects():
    mkt = MarketData(bars={"AAA": bars([100.0] * 9 + [110.0])},
                     fx={"USD": pd.Series([0.9] * 9 + [0.95], index=DAYS)})
    res = simulate(STRAT, [order(currency="USD", fx_rate=0.9, fees=1.5)], mkt, END)
    p = pos_of(res)
    assert res.daily["nav"].iloc[-1] == pytest.approx(100_000 - 900 - 1.5 + 10 * 110 * 0.95)
    assert p["price_effect"] == pytest.approx(90.0)
    assert p["fx_effect"] == pytest.approx(55.0)
    assert p["pnl"] == pytest.approx(143.5)
    assert p["pnl_pct"] == pytest.approx(143.5 / 900)
    assert p["fx_open"] == pytest.approx(0.9) and p["fx_now"] == pytest.approx(0.95)
    assert not res.violations


def test_increase_then_reduce_uses_weighted_average_cost():
    mkt = MarketData(bars={"AAA": bars([100, 100, 120, 130] + [130.0] * 6)})
    orders = [order(order_id=1, ts="2026-01-06"),
              order(order_id=2, ts="2026-01-07", action="increase", price=120.0),
              order(order_id=3, ts="2026-01-08", action="reduce", quantity=5.0, price=130.0)]
    p = pos_of(simulate(STRAT, orders, mkt, END))
    assert p["quantity"] == 15 and p["avg_entry"] == pytest.approx(110.0)
    assert p["realized"] == pytest.approx(100.0)       # 5 x (130 - 110)
    assert p["latent"] == pytest.approx(300.0)         # 15 x 130 - 1650
    assert p["pnl"] == pytest.approx(400.0)


def test_dividend_goes_to_holders_of_the_previous_close_only():
    mkt = MarketData(bars={"AAA": bars([100.0] * 10, dividends=[0, 0, 0, 0.5, 0, 0, 0, 0, 0, 0])})
    early = order(order_id=1, ts="2026-01-06", position_id="early")
    late = order(order_id=2, ts="2026-01-08", position_id="late")   # achetée le jour de l'ex-date
    res = simulate(STRAT, [early, late], mkt, END)
    assert pos_of(res, "early")["dividends"] == pytest.approx(5.0)
    assert pos_of(res, "late")["dividends"] == 0.0
    assert res.daily["dividends_cum"].iloc[-1] == pytest.approx(5.0)


FUT_SPEC = {"multiplier": 50.0, "margin_per_unit": 20_000.0, "expiry": "2026-02-20",
            "fee_ctx": {"commission_per_contract_base": 2.0, "tick_bps": 0.5}}


def fut(**kw):
    return order(instrument_kind="future", symbol="FUT", side="short", quantity=2.0, price=5000.0,
                 spec=dict(FUT_SPEC), **kw)


def test_short_future_settles_variation_daily_and_blocks_margin():
    mkt = MarketData(bars={"FUT": bars([5000, 5000, 4990, 4980] + [4980.0] * 6)})
    res = simulate(STRAT, [fut(fees=4.0)], mkt, END)
    d = res.daily
    assert d["margin_used"].iloc[1] == pytest.approx(40_000)
    assert d["buying_power"].iloc[1] == pytest.approx(100_000 - 4 - 40_000)
    # 01-07 : -2 x 50 x (4990 - 5000) = +1000 ; 01-08 : -2 x 50 x (4980 - 4990) = +1000
    assert d["cash"].iloc[-1] == pytest.approx(100_000 - 4 + 2000)
    assert d["nav"].iloc[-1] == pytest.approx(100_000 - 4 + 2000)
    p = pos_of(res)
    assert p["pnl"] == pytest.approx(1996.0)
    assert p["pnl_pct"] == pytest.approx(1996.0 / 40_000)
    assert p["price_effect"] + p["fx_effect"] == pytest.approx(2000.0)
    assert p["realized"] + p["latent"] == pytest.approx(2000.0)


def test_stop_on_gap_fills_at_the_open():
    spec = dict(FUT_SPEC, stop=4900.0)
    o = order(instrument_kind="future", symbol="FUT", side="long", quantity=1.0, price=5000.0, spec=spec)
    closes = [5000, 5000, 4820] + [4820.0] * 7
    opens = [5000, 5000, 4850] + [4820.0] * 7
    lows = [5000, 5000, 4800] + [4820.0] * 7
    highs = [5000, 5000, 4900] + [4820.0] * 7
    mkt = MarketData(bars={"FUT": bars(closes, opens=opens, highs=highs, lows=lows)})
    res = simulate(STRAT, [o], mkt, END)
    p = pos_of(res)
    assert p["status"] == "stop" and p["closed_on"] == "2026-01-07"
    assert p["realized"] == pytest.approx(-150 * 50)       # fill 4850, pas 4900 ni 4820
    assert res.daily["margin_used"].iloc[-1] == 0.0
    assert p["fees"] > 0                                    # frais estimés de la clôture automatique


def test_target_hit_and_stop_priority_when_both_touch_the_same_day():
    spec = dict(FUT_SPEC, stop=4900.0, target=5100.0)
    o = order(instrument_kind="future", symbol="FUT", side="long", quantity=1.0, price=5000.0, spec=spec)
    flat = [5000.0] * 10
    mkt = MarketData(bars={"FUT": bars(flat, highs=[5000, 5000, 5200] + [5000.0] * 7,
                                        lows=[5000, 5000, 4800] + [5000.0] * 7)})
    assert pos_of(simulate(STRAT, [o], mkt, END))["status"] == "stop"
    mkt2 = MarketData(bars={"FUT": bars(flat, highs=[5000, 5000, 5200] + [5000.0] * 7)})
    p2 = pos_of(simulate(STRAT, [o], mkt2, END))
    assert p2["status"] == "target" and p2["realized"] == pytest.approx(100 * 50)


def test_future_expires_at_its_expiry_date():
    spec = dict(FUT_SPEC, expiry="2026-01-14")
    o = order(instrument_kind="future", symbol="FUT", side="long", quantity=1.0, price=5000.0, spec=spec)
    mkt = MarketData(bars={"FUT": bars([5000.0 + i for i in range(10)])})
    res = simulate(STRAT, [o], mkt, END)
    p = pos_of(res)
    assert p["status"] == "expired" and p["closed_on"] == "2026-01-14"
    assert res.daily["margin_used"].iloc[-1] == 0.0


def test_cfd_financing_covers_the_weekend():
    spec = {"leverage": 10.0, "fee_ctx": {"fee_class": "cfd_index"}}
    o = order(instrument_kind="cfd", symbol="IDX", quantity=100.0, price=50.0, ts="2026-01-09", spec=spec)
    mkt = MarketData(bars={"IDX": bars([50.0] * 10)})
    res = simulate(STRAT, [o], mkt, END)
    d = res.daily
    fri, mon = d.index.get_loc(pd.Timestamp("2026-01-09")), d.index.get_loc(pd.Timestamp("2026-01-12"))
    assert d["financing_cum"].iloc[fri] == pytest.approx(5000 * 0.045 * 3 / 365)    # vendredi -> lundi
    assert d["financing_cum"].iloc[mon] - d["financing_cum"].iloc[fri] == pytest.approx(5000 * 0.045 / 365)
    assert d["margin_used"].iloc[fri] == pytest.approx(500.0)
    assert d["nav"].iloc[fri] == pytest.approx(100_000 - 5000 * 0.045 * 3 / 365)


def test_short_cfd_receives_reference_minus_spread():
    spec = {"leverage": 10.0, "fee_ctx": {"fee_class": "cfd_index"}}
    o = order(instrument_kind="cfd", symbol="IDX", side="short", quantity=100.0, price=50.0, ts="2026-01-12", spec=spec)
    res = simulate(STRAT, [o], MarketData(bars={"IDX": bars([50.0] * 10)}, ref_rates={"EUR": 0.05}), END)
    assert res.daily["financing_cum"].iloc[-1] == pytest.approx(-5000 * (0.05 - 0.025) * (1 / 365) * 5)


def test_violations_are_reported_not_raised():
    mkt = MarketData(bars={"AAA": bars([100.0] * 10)})
    too_big = order(quantity=2000.0)                                       # 200 000 > capital
    res = simulate(STRAT, [too_big], mkt, END)
    assert any("insuffisant" in v["message"] for v in res.violations)
    oversell = [order(order_id=1), order(order_id=2, ts="2026-01-07", action="reduce", quantity=50.0)]
    assert any("détenus" in v["message"] for v in simulate(STRAT, oversell, mkt, END).violations)
    early = order(ts="2026-01-02")
    assert any("antérieur" in v["message"] for v in simulate(STRAT, [early], mkt, END).violations)
    closed = [order(order_id=1), order(order_id=2, ts="2026-01-07", action="close"),
              order(order_id=3, ts="2026-01-08", action="increase")]
    assert any("clôturée" in v["message"] for v in simulate(STRAT, closed, mkt, END).violations)


def test_accounting_identity_holds_across_instruments():
    """NAV - capital = somme des P&L des positions (réalisé + latent + dividendes - frais - financement)."""
    n = 10
    mkt = MarketData(
        bars={"AAA": bars([100, 101, 103, 102, 105, 107, 106, 108, 110, 111], dividends=[0, 0, 0, 0.4] + [0] * 6),
              "FUT": bars([5000, 5010, 4990, 5020, 5050, 5000, 4980, 5030, 5060, 5040]),
              "IDX": bars([50, 51, 49, 50, 52, 53, 51, 52, 54, 55])},
        fx={"USD": pd.Series([0.92, 0.91, 0.93, 0.92, 0.9, 0.91, 0.92, 0.94, 0.93, 0.95], index=DAYS[:n])})
    orders = [
        order(order_id=1, position_id="a", ts="2026-01-06", symbol="AAA", currency="USD", fx_rate=0.91,
              quantity=40.0, price=101.0, fees=2.0),
        order(order_id=2, position_id="a", ts="2026-01-09", action="reduce", symbol="AAA", currency="USD",
              fx_rate=0.9, quantity=15.0, price=105.0, fees=1.0),
        order(order_id=3, position_id="f", ts="2026-01-06", instrument_kind="future", symbol="FUT", side="short",
              currency="USD", fx_rate=0.91, quantity=1.0, price=5010.0, fees=3.0, spec=dict(FUT_SPEC)),
        order(order_id=4, position_id="f", ts="2026-01-13", action="increase", instrument_kind="future",
              symbol="FUT", side="short", currency="USD", fx_rate=0.92, quantity=1.0, price=4980.0, fees=3.0,
              spec=dict(FUT_SPEC)),
        order(order_id=5, position_id="f", ts="2026-01-15", action="close", instrument_kind="future",
              symbol="FUT", side="short", currency="USD", fx_rate=0.93, quantity=2.0, price=5060.0, fees=3.0,
              spec=dict(FUT_SPEC)),
        order(order_id=6, position_id="c", ts="2026-01-07", instrument_kind="cfd", symbol="IDX", currency="USD",
              fx_rate=0.93, quantity=200.0, price=49.0, fees=1.0, spec={"leverage": 5.0, "fee_ctx": {"fee_class": "cfd_index"}}),
        order(order_id=7, position_id="c", ts="2026-01-14", action="reduce", instrument_kind="cfd", symbol="IDX",
              currency="USD", fx_rate=0.91, quantity=50.0, price=52.0, fees=1.0, spec={"leverage": 5.0}),
    ]
    res = simulate(STRAT, orders, mkt, END)
    assert not res.violations
    total = sum(p["pnl"] for p in res.positions)
    assert res.daily["nav"].iloc[-1] - STRAT["initial_capital"] == pytest.approx(total, abs=1e-6)
    fees = sum(p["fees"] for p in res.positions)
    assert res.daily["fees_cum"].iloc[-1] == pytest.approx(fees)
    assert any(p["dividends"] > 0 for p in res.positions)
    assert any(p["financing"] > 0 for p in res.positions)


def test_an_open_future_has_nothing_realized_and_a_closed_one_realizes_everything():
    """Le règlement quotidien (converti au change du jour) ne doit pas laisser de « réalisé » fantôme sur une
    position ouverte : tout est latent tant que rien n'est sorti, tout est réalisé une fois fermée."""
    fx = pd.Series([0.9, 0.9, 0.92, 0.95] + [0.95] * 6, index=DAYS)
    mkt = MarketData(bars={"FUT": bars([5000, 5000, 4990, 4980] + [4980.0] * 6)}, fx={"USD": fx})
    opened = fut(currency="USD", fx_rate=0.9)
    p = pos_of(simulate(STRAT, [opened], mkt, END))
    settled = 1000 * 0.92 + 1000 * 0.95                       # variation du 7 puis du 8 janvier, au change du jour
    assert p["realized"] == 0.0 and p["latent"] == pytest.approx(settled)
    assert p["price_effect"] + p["fx_effect"] == pytest.approx(settled)
    close = order(order_id=2, ts="2026-01-09", action="close", instrument_kind="future", symbol="FUT", side="short",
                  quantity=2.0, price=4980.0, currency="USD", fx_rate=0.95, spec=dict(FUT_SPEC))
    done = pos_of(simulate(STRAT, [opened, close], mkt, END))
    assert done["status"] == "closed" and done["latent"] == 0.0
    assert done["realized"] == pytest.approx(settled) and done["pnl"] == pytest.approx(settled)
