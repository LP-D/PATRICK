"""Ordres limite et exécutions partielles des fonds (A12) : déclenchement sur la séance, prix d'exécution, tranches, validité, refus."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pandas as pd
import pytest

from patrick.fund import autopilot, limit_orders, service, store

PLACED = dt.date(2026, 1, 7)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def cto(conn, capital=100_000):
    return store.create_strategy(conn, "Macro CTO", "CTO", capital, "2026-01-05")


def _bars(lows: dict[str, float] | None = None, highs: dict[str, float] | None = None, opens: dict[str, float] | None = None,
          volume: float = 5_000_000.0) -> pd.DataFrame:
    """Barres de MC.PA du jeu factice, avec des plus bas / plus hauts / ouvertures imposés certains jours."""
    df, _ = fs.fake_download("MC.PA")
    df = df.copy()
    df["volume"] = volume
    for col, values in (("low", lows), ("high", highs), ("open", opens)):
        for day, v in (values or {}).items():
            df.loc[pd.Timestamp(day), col] = v
    return df


def _buy(sid, quantity=10, **kw):
    return {"strategy_id": sid, "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": quantity, **kw}


def _orders(conn, sid):
    return [o for o in store.list_orders(conn, sid) if (o.get("note") or "").startswith("limit:")]


def test_a_buy_limit_waits_then_fills_at_the_limit_on_the_first_touching_session(conn):
    sid = cto(conn)
    lo = limit_orders.create(conn, _buy(sid), 690.0, today=PLACED)
    assert lo["status"] == "open" and lo["direction"] == "buy" and lo["expires_on"] == "2026-02-06"
    # le jour du placement ne compte pas, même s'il touche ; le 12 touche, ouverture au-dessus de la limite -> exécuté À la limite
    bars = _bars(lows={"2026-01-07": 600.0, "2026-01-12": 689.0})
    moved = limit_orders.resolve(conn, sid, today=fs.TODAY, bars_loader=lambda s: bars)
    assert [m["status"] for m in moved] == ["filled"]
    (order,) = _orders(conn, sid)
    assert order["ts"] == "2026-01-12" and order["price"] == pytest.approx(690.0) and order["price_source"] == "manual"
    assert order["quantity"] == 10 and order["action"] == "open" and order["note"] == f"limit:{lo['limit_id']}"
    assert limit_orders.resolve(conn, sid, today=fs.TODAY, bars_loader=lambda s: bars) == []        # rien ne bouge deux fois


def test_an_open_below_the_limit_fills_at_the_open():
    bar = pd.Series({"open": 680.0, "high": 700.0, "low": 675.0, "close": 695.0})
    assert limit_orders.fill_on_bar("buy", 690.0, bar) == 680.0
    assert limit_orders.fill_on_bar("sell", 670.0, bar) == 680.0
    assert limit_orders.fill_on_bar("sell", 720.0, bar) is None


def test_partial_fills_follow_the_volume_cap_and_open_then_increase(conn):
    sid = cto(conn)
    lo = limit_orders.create(conn, _buy(sid, quantity=25), 800.0, today=PLACED, participation=0.1)
    bars = _bars(volume=100.0)                                       # 10 % de 100 = 10 titres par séance
    limit_orders.resolve(conn, sid, today=dt.date(2026, 1, 9), bars_loader=lambda s: bars)
    row = limit_orders.get(conn, lo["limit_id"])
    assert row["status"] == "partial" and row["filled_quantity"] == 20 and row["checked_through"] == "2026-01-09"
    limit_orders.resolve(conn, sid, today=fs.TODAY, bars_loader=lambda s: bars)
    row = limit_orders.get(conn, lo["limit_id"])
    assert row["status"] == "filled" and [f["quantity"] for f in row["fills"]] == [10, 10, 5]
    assert [o["action"] for o in _orders(conn, sid)] == ["open", "increase", "increase"]
    assert len({o["position_id"] for o in _orders(conn, sid)}) == 1


def test_a_sell_limit_closes_a_position_in_slices(conn):
    sid = cto(conn)
    opened = service.place_order(conn, {**_buy(sid, quantity=15), "date": "2026-01-06"}, today=fs.TODAY)
    pid = store.get_order(conn, opened["order_id"])["position_id"]
    lo = limit_orders.create(conn, {"strategy_id": sid, "action": "close", "position_id": pid, "quantity": 15}, 703.0,
                             today=PLACED, participation=0.1)
    assert lo["direction"] == "sell" and lo["symbol"] == "MC.PA"
    bars = _bars(volume=100.0, highs={"2026-01-08": 702.0})          # le 8 ne touche pas, puis chaque séance touche
    limit_orders.resolve(conn, sid, today=fs.TODAY, bars_loader=lambda s: bars)
    row = limit_orders.get(conn, lo["limit_id"])
    assert row["status"] == "filled" and row["fills"][0]["day"] == "2026-01-09"
    assert [o["action"] for o in _orders(conn, sid)] == ["reduce", "close"]


def test_expiry_cancel_and_rejection(conn):
    sid = cto(conn, capital=10_000)
    never = limit_orders.create(conn, _buy(sid), 100.0, today=PLACED, expires_on="2026-01-14")
    waiting = limit_orders.create(conn, _buy(sid), 100.0, today=PLACED)
    too_big = limit_orders.create(conn, _buy(sid, quantity=1000), 800.0, today=PLACED)
    limit_orders.resolve(conn, sid, today=fs.TODAY, bars_loader=lambda s: _bars())
    assert limit_orders.get(conn, never["limit_id"])["status"] == "expired"
    rejected = limit_orders.get(conn, too_big["limit_id"])
    assert rejected["status"] == "rejected" and rejected["message"].startswith("refusé le 2026-01-08")
    assert limit_orders.cancel(conn, waiting["limit_id"])["status"] == "cancelled"
    with pytest.raises(store.FundError):
        limit_orders.cancel(conn, waiting["limit_id"])
    with pytest.raises(store.FundError):
        limit_orders.create(conn, _buy(sid), -1, today=PLACED)


def test_the_nightly_cycle_resolves_pending_limits(conn, monkeypatch):
    sid = cto(conn)
    lo = limit_orders.create(conn, _buy(sid), 800.0, today=PLACED)
    autopilot.run_all(conn, today=fs.TODAY)
    assert limit_orders.get(conn, lo["limit_id"])["status"] == "filled"


def test_routes_create_list_cancel_and_panel(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.freeze_today(monkeypatch)
    client = TestClient(app)
    sid = fs.make_strategy(client)
    resp = client.post(f"/api/fund/strategies/{sid}/orders",
                       json={"instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 3, "limit_price": 650})
    assert resp.status_code == 200, resp.text
    lid = resp.json()["limit_order"]["limit_id"]
    listed = client.get(f"/api/fund/strategies/{sid}/limit-orders").json()["limit_orders"]
    assert [x["limit_id"] for x in listed] == [lid]
    panel = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "Ordres limite" in panel and f'data-limit-id="{lid}"' in panel
    assert client.post(f"/api/fund/limit-orders/{lid}/cancel").json()["limit_order"]["status"] == "cancelled"
    assert client.post(f"/api/fund/limit-orders/{lid}/cancel").status_code == 400
