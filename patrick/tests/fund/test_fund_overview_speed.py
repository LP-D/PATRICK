"""/fonds plus rapide (B20) : lecture des cotations bornée à la période utile, un symbole lu une fois par calcul d'ensemble."""
from __future__ import annotations

import fund_support as fs
import pytest

from patrick.fund import prices, service, store


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def test_history_start_is_the_earliest_of_opening_and_orders_minus_a_margin():
    orders = [{"ts": "2026-01-07"}, {"ts": "2026-03-02"}]
    assert prices.history_start(orders) == "2025-11-01"                       # 7 janvier - 60 jours = 8 novembre, ramené au 1er
    assert prices.history_start(orders, opened_on="2025-06-20") == "2025-04-01"
    assert prices.history_start([]) is None


def test_load_bars_since_keeps_only_the_window(conn):
    prices.ensure_bars(conn, "MC.PA")
    full, part = prices.load_bars(conn, "MC.PA"), prices.load_bars(conn, "MC.PA", "2026-01-01")
    assert part.index[0].isoformat()[:10] >= "2026-01-01" and part.equals(full.loc["2026-01-01":])


def test_overview_reads_each_symbol_once_and_gives_the_same_figures(conn, monkeypatch):
    for name in ("A", "B"):
        sid = store.create_strategy(conn, name, "CTO", 100_000, "2026-01-05")
        service.place_order(conn, {"strategy_id": sid, "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 3,
                                   "date": "2026-01-07"}, today=fs.TODAY)
    reads = []
    real = prices.load_bars
    monkeypatch.setattr(prices, "load_bars", lambda c, s, since=None: reads.append(s) or real(c, s, since))
    out = service.overview(conn, today=fs.TODAY)
    assert reads.count("MC.PA") == 1                                           # deux stratégies, une lecture
    reads.clear()
    for snap in out["strategies"]:                                             # mêmes chiffres qu'un calcul isolé, sans mémo
        alone = service.strategy_snapshot(conn, snap["strategy"], fs.TODAY)
        assert alone["kpis"]["nav"] == pytest.approx(snap["kpis"]["nav"], rel=1e-12)
    assert reads.count("MC.PA") == 2                                           # hors calcul d'ensemble : une lecture par appel
