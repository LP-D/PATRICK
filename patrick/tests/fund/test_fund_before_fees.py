"""Performance avant frais, catégories séparées et conditions des gammes (ADR 0030). Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pandas as pd
import pytest

from patrick.fund import asset_classes, kpis, real_funds, service, store

TODAY = dt.date(2026, 1, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _order(conn, sid, *, ts="2026-01-07", fees=1.0, symbol="MC.PA", price=700.0, qty=4.0, action="open", pid="pos_0000000001"):
    store.insert_order(conn, {"strategy_id": sid, "position_id": pid, "ts": ts, "action": action, "instrument_kind": "equity",
                              "symbol": symbol, "side": "long", "quantity": qty, "price": price, "price_source": "market", "currency": "EUR",
                              "fx_rate": 1.0, "fees": fees, "fees_source": "estimated", "fee_seed": 7, "spec": {}, "note": None})


# --------------------------------------------------------------------------- lecture avant / après frais

@pytest.mark.parametrize("gross, net, has_orders, verdict", [
    (0.0, 0.0, False, "none"), (-50.0, -80.0, True, "no_edge"), (0.0, -10.0, True, "no_edge"),
    (40.0, -5.0, True, "eaten"), (40.0, 0.0, True, "eaten"), (40.0, 25.0, True, "kept")])
def test_the_edge_verdict_separates_costs_from_a_signal_that_does_not_win(gross, net, has_orders, verdict):
    assert kpis.edge_verdict(gross, net, has_orders) == verdict


def test_the_value_before_costs_adds_back_fees_and_financing_day_by_day():
    daily = pd.DataFrame({"nav": [1000.0, 990.0, 1005.0], "fees_cum": [0.0, 12.0, 14.0], "financing_cum": [0.0, 1.0, -2.0]},
                         index=pd.bdate_range("2026-01-05", periods=3))

    assert kpis.gross_nav(daily).tolist() == [1000.0, 1003.0, 1017.0]
    points = kpis.series_points(daily.assign(cash=0.0))
    assert [p["gross"] for p in points] == [1000.0, 1003.0, 1017.0] and [p["nav"] for p in points] == [1000.0, 990.0, 1005.0]


def test_a_strategy_snapshot_reports_its_pnl_before_costs(conn):
    sid = store.create_strategy(conn, "A", "CTO", 10_000, "2026-01-05")
    _order(conn, sid, fees=400.0)                                 # MC.PA monte de 0,5 € par séance : gain avant frais, frais plus gros

    k = service.strategy_snapshot(conn, store.get_strategy(conn, sid), TODAY)["kpis"]

    assert k["costs"] == pytest.approx(k["fees"] + k["financing"])
    assert k["gross_pnl"] == pytest.approx(k["pnl"] + k["costs"]) and k["gross_pnl"] > 0 > k["pnl"]
    assert k["edge_verdict"] == "eaten" and k["gross_pnl_pct"] == pytest.approx(k["gross_pnl"] / 10_000)
    assert k["n_sessions"] > 0 and k["costs_share"] == pytest.approx(k["costs"] / k["gross_pnl"])


# --------------------------------------------------------------------------- catégories et sous-totaux

def test_the_overview_never_sums_categories_and_gives_each_envelope_its_subtotal(conn):
    quant = store.create_strategy(conn, "Systematic Future", "CTO", 10_000_000, "2026-01-05")
    cto = store.create_strategy(conn, "CTO Actions US", "CTO", 5_000, "2026-01-05", category="real", fee_flat=1.0)
    pea = store.create_strategy(conn, "PEA Actions France", "PEA", 5_000, "2026-01-05", category="real", fee_flat=1.0)
    lab = store.create_strategy(conn, "Combiné Référence", "CTO", 10_000_000, "2026-01-05", category="lab")
    _order(conn, pea, fees=1.0)

    data = service.overview(conn, TODAY)

    cats = {c["category"]: c for c in data["categories"]}
    assert list(cats) == ["quant", "real", "lab"]
    assert cats["real"]["fund"]["capital"] == 10_000 and cats["quant"]["fund"]["capital"] == 10_000_000
    groups = {g["wrapper"]: g for g in cats["real"]["groups"]}
    assert set(groups) == {"CTO", "PEA"} and groups["PEA"]["fund"]["capital"] == 5_000
    assert groups["PEA"]["fund"]["fees"] == 1.0 and groups["CTO"]["fund"]["fees"] == 0.0
    assert groups["PEA"]["fund"]["gross_pnl"] == pytest.approx(groups["PEA"]["fund"]["pnl"] + groups["PEA"]["fund"]["costs"])
    assert cats["real"]["fund"]["verdicts"]["kept"] + cats["real"]["fund"]["verdicts"]["eaten"] == 1
    assert [g["wrapper"] for g in cats["lab"]["groups"]] == [None] and quant and cto and lab


# --------------------------------------------------------------------------- conditions d'une gamme

def test_set_terms_moves_a_strategy_without_orders_and_freezes_fees_and_capital_once_traded(conn):
    sid = store.create_strategy(conn, "CTO Future", "CTO", 10_000_000, "2026-01-05")

    assert store.set_terms(conn, sid, category="real", fee_flat=1.0, initial_capital=5_000) is True
    s = store.get_strategy(conn, sid)
    assert (s["category"], s["fee_flat"], s["initial_capital"]) == ("real", 1.0, 5_000)
    assert store.set_terms(conn, sid, category="real", fee_flat=1.0, initial_capital=5_000) is False
    _order(conn, sid)
    assert store.set_terms(conn, sid, category="quant", fee_flat=1.0, initial_capital=5_000) is True     # la catégorie seule suit
    with pytest.raises(store.FundError, match="figés"):
        store.set_terms(conn, sid, category="quant", fee_flat=None, initial_capital=5_000)
    with pytest.raises(store.FundError, match="catégorie"):
        store.set_terms(conn, sid, category="autre", fee_flat=1.0, initial_capital=5_000)


def test_a_cto_strategy_made_before_the_retail_terms_takes_them_when_it_has_no_order(conn):
    old = store.create_strategy(conn, "CTO Actions France", "CTO", 10_000_000, "2026-01-05")          # créée en quant, 10 M€, le 22/11

    (row,) = asset_classes.setup(conn, today=TODAY, family="cto", tier="large", only=["Actions France"])

    s = store.get_strategy(conn, old)
    assert row["strategy_id"] == old and row["created"] is False and row["capital_changed"] is True
    assert (s["category"], s["fee_flat"], s["initial_capital"]) == ("real", 1.0, 5_000)
    assert store.get_autopilot(conn, old)["settings"]["min_position"] == 200.0


def test_a_cto_strategy_that_already_traded_in_the_quant_category_is_refused(conn):
    old = store.create_strategy(conn, "CTO Actions France", "CTO", 10_000_000, "2026-01-05")
    _order(conn, old)

    with pytest.raises(store.FundError, match="existe déjà"):
        asset_classes.setup(conn, today=TODAY, family="cto", tier="large", only=["Actions France"])


def test_the_every_signal_funds_are_renamed_so_systematic_only_means_the_quant_range(conn):
    legacy = store.create_strategy(conn, "Systematic CTO", "CTO", 5_000, "2026-01-05", category="real", fee_flat=1.0)

    rows = real_funds.setup(conn, today=TODAY)

    assert [r["name"] for r in rows] == ["PEA Tous signaux", "CTO Tous signaux"]
    assert rows[1]["strategy_id"] == legacy and store.get_strategy(conn, legacy)["name"] == "CTO Tous signaux"
    assert len(store.list_strategies(conn)) == 2
