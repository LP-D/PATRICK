"""Cas d'usage du fonds : aperçu et passage d'ordres, correction, instantanés. Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest

from patrick.fund import service, store

TODAY = dt.date(2026, 1, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def cto(conn, capital=100_000):
    return store.create_strategy(conn, "Macro CTO", "CTO", capital, "2026-01-05")


def equity(sid, symbol="MC.PA", **kw):
    return {"strategy_id": sid, "instrument_kind": "equity", "symbol": symbol, "side": "long",
            "date": "2026-01-07", **kw}


def es_future(sid, **kw):
    return {"strategy_id": sid, "instrument_kind": "future", "side": "short", "quantity": 2, "date": "2026-01-07",
            "spec": {"root": "ES", "year": 2026, "month": 12}, **kw}


def test_equity_quote_then_place_records_the_quoted_fees(conn):
    sid = cto(conn)
    req = equity(sid, "AAPL", amount=5000, fees_mode="estimated")
    q = service.quote(conn, req, TODAY)
    assert q["ok"], q["blocking"]
    pv = q["preview"]
    fx, price = fs.fx_on("2026-01-07"), fs.price_on("AAPL", "2026-01-07")
    assert pv["quantity"] == int(5000 // (price * fx)) and pv["currency"] == "USD"
    assert pv["fx_rate"] == pytest.approx(fx) and pv["fees"]["source"] == "estimated" and pv["fees"]["fx"] > 0
    assert pv["cash_after"] == pytest.approx(100_000 - pv["quantity"] * price * fx - pv["fees"]["total"])
    placed = service.place_order(conn, {**req, "fee_seed": pv["fees"]["seed"], "position_id": pv["position_id"]}, TODAY)
    assert placed["preview"]["fees"]["total"] == pv["fees"]["total"]
    assert store.list_orders(conn, sid)[0]["fees"] == pv["fees"]["total"]
    assert store.list_orders(conn, sid)[0]["position_id"] == pv["position_id"]


def test_manual_fees_and_manual_price(conn):
    sid = cto(conn)
    pv = service.place_order(conn, equity(sid, quantity=3, price=650.0, fees_mode="manual", fees=7.5), TODAY)["preview"]
    assert pv["price"] == 650.0 and pv["price_source"] == "manual"
    assert pv["fees"]["total"] == 7.5 and pv["fees"]["source"] == "manual"
    bad = service.quote(conn, equity(sid, quantity=3, fees_mode="manual", fees=-1), TODAY)
    assert not bad["ok"] and "frais manuels" in bad["blocking"][0]


def test_a_date_between_sessions_executes_on_the_next_trading_day(conn):
    sid = cto(conn)
    pv = service.quote(conn, equity(sid, quantity=1, date="2026-01-10"), TODAY)["preview"]      # un samedi
    assert pv["exec_day"] == "2026-01-12" and pv["price"] == pytest.approx(fs.price_on("MC.PA", "2026-01-12"))
    assert pv["provisional"] is False
    today_quote = service.quote(conn, equity(sid, quantity=1, date="2026-01-16"), dt.date(2026, 10, 2))["preview"]
    assert today_quote["exec_day"] == "2026-01-16" and today_quote["provisional"] is False
    last = service.quote(conn, equity(sid, quantity=1, date="2026-10-02"), dt.date(2026, 10, 2))["preview"]
    assert last["provisional"] is True                                  # dernier cours d'aujourd'hui


def test_sizes_that_cannot_be_traded_are_refused_with_a_reason(conn):
    sid = cto(conn)
    tiny = service.quote(conn, equity(sid, amount=100), TODAY)                         # < 1 action à 700 €
    assert not tiny["ok"] and "montant insuffisant" in tiny["blocking"][0]
    assert "quantité ou montant" in service.quote(conn, equity(sid), TODAY)["blocking"][0]
    assert "quantité entière" in service.quote(conn, es_future(sid, quantity=1.5), TODAY)["blocking"][0]
    assert "quantité entière" in service.quote(conn, equity(sid, quantity=0.4), TODAY)["blocking"][0]
    assert "invalide" in service.quote(conn, equity(sid, quantity="abc"), TODAY)["blocking"][0]


def test_future_date_unknown_symbol_and_unknown_strategy_are_refused(conn):
    sid = cto(conn)
    q = service.quote(conn, equity(sid, quantity=1, date="2026-02-20"), TODAY)
    assert not q["ok"] and "futur" in q["blocking"][0]
    q = service.quote(conn, equity(sid, "ZZZZ", quantity=1), TODAY)
    assert not q["ok"] and "aucune cotation" in q["blocking"][0]
    q = service.quote(conn, equity(sid, quantity=1, date="2025-06-03"), TODAY)
    assert not q["ok"] and "antérieure à l'ouverture" in q["blocking"][0]
    q = service.quote(conn, equity(sid, quantity=1, date="2025-05-01"), TODAY)
    assert not q["ok"] and "pas de cotation avant le 2025-06-02" in q["blocking"][0]
    q = service.quote(conn, equity("nope", quantity=1), TODAY)
    assert not q["ok"] and "introuvable" in q["blocking"][0]
    with pytest.raises(store.FundError, match="introuvable"):
        service.place_order(conn, equity("nope", quantity=1), TODAY)
    with pytest.raises(service.FundRuleError) as exc:
        service.place_order(conn, equity(sid, "ZZZZ", quantity=1), TODAY)
    assert "aucune cotation" in exc.value.blocking[0]


def test_pea_blocks_short_usd_and_derivatives_but_warns_on_eligibility(conn):
    sid = store.create_strategy(conn, "PEA", "PEA", 50_000, "2026-01-05")
    q_usd = service.quote(conn, equity(sid, "AAPL", quantity=2), TODAY)
    assert not q_usd["ok"] and any("euro" in m for m in q_usd["blocking"])
    assert any("probablement non éligible" in m for m in q_usd["warnings"])
    q_short = service.quote(conn, equity(sid, quantity=2, side="short"), TODAY)
    assert any("longues seulement" in m for m in q_short["blocking"])
    assert any("ni future ni CFD" in m for m in service.quote(conn, es_future(sid), TODAY)["blocking"])
    ok = service.quote(conn, equity(sid, quantity=2), TODAY)
    assert ok["ok"] and not ok["warnings"]


def test_cto_blocks_equity_short_and_excess_cfd_leverage_and_reports_the_cap(conn):
    sid = cto(conn)
    short = service.quote(conn, equity(sid, quantity=1, side="short"), TODAY)
    assert any("découvert" in m for m in short["blocking"])
    cfd = {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long", "quantity": 1,
           "date": "2026-01-07", "spec": {"leverage": 30}}
    q = service.quote(conn, cfd, TODAY)
    assert any("plafond 20:1" in m for m in q["blocking"]) and q["preview"]["leverage_cap"] == 20.0
    assert q["preview"]["underlying_class"] == "index_major"
    cfd["spec"]["leverage"] = 20
    ok = service.quote(conn, cfd, TODAY)
    assert ok["ok"] and ok["preview"]["margin_required"] == pytest.approx(
        ok["preview"]["notional_base"] / 20)


def test_cfd_without_a_leverage_defaults_to_the_lower_of_the_cap_and_five(conn):
    sid = cto(conn)
    q = service.quote(conn, {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "short",
                             "quantity": 1, "date": "2026-01-07"}, TODAY)
    assert q["ok"] and q["order"]["spec"]["leverage"] == 5.0


def test_future_preview_reports_margin_notional_and_fixed_commission(conn):
    sid = cto(conn)
    q = service.quote(conn, es_future(sid), TODAY)
    assert q["ok"], q["blocking"]
    pv = q["preview"]
    assert pv["symbol"] == "ESZ26.CME" and pv["margin_required"] == pytest.approx(2 * 22000 * pv["fx_rate"])
    assert pv["notional_local"] == pytest.approx(2 * 50 * fs.price_on("ESZ26.CME", "2026-01-07"))
    assert pv["fees"]["commission"] == pytest.approx(2 * 2.0 * pv["fx_rate"])
    assert q["order"]["spec"]["expiry"] == "2026-12-18" and q["order"]["spec"]["multiplier"] == 50.0
    big = service.quote(conn, es_future(sid, quantity=6), TODAY)                  # 6 x 22 000 $ > 100 000 EUR
    assert not big["ok"] and any("insuffisant" in m for m in big["blocking"])


def test_future_and_unknown_root_and_month_are_refused(conn):
    sid = cto(conn)
    bad_root = es_future(sid, spec={"root": "XX", "year": 2026, "month": 12})
    assert "racine" in service.quote(conn, bad_root, TODAY)["blocking"][0]
    bad_month = es_future(sid, spec={"root": "ES", "year": 2026, "month": 11})
    assert "pas de contrat" in service.quote(conn, bad_month, TODAY)["blocking"][0]
    assert "instrument" in service.quote(conn, {"strategy_id": sid, "instrument_kind": "bond"}, TODAY)["blocking"][0]
    assert "sens" in service.quote(conn, equity(sid, quantity=1, side="sideways"), TODAY)["blocking"][0]


def test_stop_and_target_must_bracket_the_entry_price(conn):
    sid = cto(conn)
    price = fs.price_on("ESZ26.CME", "2026-01-07")
    long_bad = es_future(sid, side="long", spec={"root": "ES", "year": 2026, "month": 12, "stop": price + 10})
    assert "long : stop sous le prix" in service.quote(conn, long_bad, TODAY)["blocking"][0]
    short_bad = es_future(sid, spec={"root": "ES", "year": 2026, "month": 12, "target": price + 10})
    assert "short : stop au-dessus" in service.quote(conn, short_bad, TODAY)["blocking"][0]
    ok = es_future(sid, side="long", spec={"root": "ES", "year": 2026, "month": 12, "stop": price - 50,
                                           "target": price + 80})
    q = service.quote(conn, ok, TODAY)
    assert q["ok"] and q["order"]["spec"]["stop"] == price - 50 and q["order"]["spec"]["target"] == price + 80


def test_reduce_more_than_held_close_and_reopen_rules(conn):
    sid = cto(conn)
    pid = service.place_order(conn, equity(sid, quantity=4), TODAY)["preview"]["position_id"]
    reduce = {"strategy_id": sid, "action": "reduce", "position_id": pid, "date": "2026-01-09"}
    assert any("détenus" in m for m in service.quote(conn, {**reduce, "quantity": 9}, TODAY)["blocking"])
    assert "quantité requise" in service.quote(conn, reduce, TODAY)["blocking"][0]
    closed = service.place_order(conn, {"strategy_id": sid, "action": "close", "position_id": pid,
                                        "date": "2026-01-09"}, TODAY)
    assert closed["preview"]["quantity"] == 4 and closed["preview"]["fees"]["total"] > 0
    again = service.quote(conn, {"strategy_id": sid, "action": "increase", "position_id": pid, "quantity": 1,
                                 "date": "2026-01-12"}, TODAY)
    assert any("clôturée" in m for m in again["blocking"])
    unknown = service.quote(conn, {"strategy_id": sid, "action": "increase", "position_id": "nope", "quantity": 1,
                                   "date": "2026-01-12"}, TODAY)
    assert "position introuvable" in unknown["blocking"][0]
    assert "action inconnue" in service.quote(conn, {**reduce, "action": "explode"}, TODAY)["blocking"][0]
    snap = service.strategy_snapshot(conn, store.get_strategy(conn, sid), TODAY)
    assert [p["status"] for p in snap["positions"]] == ["closed"]


def test_modify_sets_a_stop_that_the_snapshot_reports(conn):
    sid = cto(conn)
    pid = service.place_order(conn, es_future(sid, side="long", quantity=1), TODAY)["preview"]["position_id"]
    mod = service.place_order(conn, {"strategy_id": sid, "action": "modify", "position_id": pid, "date": "2026-01-09",
                                     "spec": {"stop": 5500.0, "target": ""}}, TODAY)
    assert mod["preview"]["quantity"] == 0 and mod["preview"]["fees"]["total"] == 0 and mod["preview"]["price"] is None
    pos = service.strategy_snapshot(conn, store.get_strategy(conn, sid), TODAY)["positions"][0]
    assert pos["stop"] == 5500.0 and pos["target"] is None and pos["status"] == "open"


def test_backdated_order_that_breaks_a_later_one_is_refused(conn):
    sid = cto(conn, 10_000)
    service.place_order(conn, equity(sid, quantity=12, date="2026-01-12"), TODAY)           # ~ 8 800 EUR
    backdated = service.quote(conn, equity(sid, "TTE.PA", quantity=100), TODAY)
    assert not backdated["ok"] and any("insuffisant" in m for m in backdated["blocking"])


def test_correct_order_changes_the_opening_order_only(conn):
    sid = cto(conn)
    a = service.place_order(conn, equity(sid, "AAPL", quantity=10), TODAY)
    fut = service.place_order(conn, es_future(sid, quantity=1, date="2026-01-08"), TODAY)
    corrected = service.correct_order(conn, a["order_id"], {"quantity": 12, "date": "2026-01-08", "price": 190.0,
                                                            "fees_mode": "manual", "fees": 2.0}, TODAY)
    row = store.get_order(conn, a["order_id"])
    assert corrected["preview"]["quantity"] == 12 and row["quantity"] == 12 and row["ts"] == "2026-01-08"
    assert row["price"] == 190.0 and row["price_source"] == "manual" and row["fees"] == 2.0
    assert row["position_id"] == a["preview"]["position_id"] and len(store.list_orders(conn, sid)) == 2
    fut_fix = service.correct_order(conn, fut["order_id"], {"quantity": 2, "date": "2026-01-08"}, TODAY)
    assert fut_fix["preview"]["symbol"] == "ESZ26.CME" and store.get_order(conn, fut["order_id"])["quantity"] == 2
    reduce = service.place_order(conn, {"strategy_id": sid, "action": "reduce", "position_id": row["position_id"],
                                        "quantity": 1, "date": "2026-01-12"}, TODAY)
    with pytest.raises(store.FundError, match="ouverture"):
        service.correct_order(conn, reduce["order_id"], {"quantity": 1}, TODAY)
    with pytest.raises(service.FundRuleError):
        service.correct_order(conn, a["order_id"], {"quantity": 100_000, "date": "2026-01-08"}, TODAY)


def test_snapshot_and_overview_are_consistent_across_instruments(conn):
    sid = cto(conn)
    service.place_order(conn, equity(sid, "AAPL", quantity=10), TODAY)
    service.place_order(conn, es_future(sid, quantity=1, date="2026-01-08"), TODAY)
    service.place_order(conn, {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long",
                               "quantity": 3, "date": "2026-01-09", "spec": {"leverage": 10}}, TODAY)
    ov = service.overview(conn, TODAY)
    snap = ov["strategies"][0]
    assert not snap["violations"] and not snap["alert_days"]
    assert snap["kpis"]["nav"] - snap["kpis"]["capital"] == pytest.approx(sum(p["pnl"] for p in snap["positions"]))
    assert snap["kpis"]["n_open_positions"] == 3 and snap["kpis"]["margin_used"] > 0
    assert any("taux de référence" in n for n in snap["notes"])          # CFD en USD, FRED non configuré
    assert ov["fund"]["capital"] == 100_000 and ov["fund"]["n_strategies"] == 1 and len(snap["series"]) > 5
    assert ov["fund"]["pnl"] == pytest.approx(snap["kpis"]["pnl"])
    by_kind = {p["kind"]: p for p in snap["positions"]}
    assert by_kind["equity"]["currency"] == "USD" and by_kind["equity"]["fx_effect"] != 0
    assert by_kind["future"]["margin"] > 0 and by_kind["cfd"]["leverage"] == 10.0


def test_overview_of_an_empty_fund_and_a_strategy_without_orders(conn):
    assert service.overview(conn, TODAY) == {"strategies": [], "fund": {
        "nav": 0, "capital": 0, "pnl": 0, "pnl_pct": None, "n_strategies": 0}}
    cto(conn)
    snap = service.overview(conn, TODAY)["strategies"][0]
    assert snap["kpis"]["nav"] == 100_000 and snap["positions"] == [] and snap["orders"] == []


def test_modify_cfd_leverage_respects_the_cap(conn):
    sid = cto(conn)
    cfd = {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long", "quantity": 1,
           "date": "2026-01-07", "spec": {"leverage": 5}}
    pid = service.place_order(conn, cfd, TODAY)["preview"]["position_id"]
    modify = {"strategy_id": sid, "action": "modify", "position_id": pid, "date": "2026-01-09"}
    assert service.quote(conn, {**modify, "spec": {"leverage": 10}}, TODAY)["ok"]
    over = service.quote(conn, {**modify, "spec": {"leverage": 25}}, TODAY)
    assert not over["ok"] and any("plafond 20:1" in m for m in over["blocking"])
    keep = service.quote(conn, {**modify, "spec": {"leverage": ""}}, TODAY)
    assert keep["ok"] and "leverage" not in keep["order"]["spec"]


def test_orders_of_the_same_day_chain_on_one_position(conn):
    sid = cto(conn)
    pid = service.place_order(conn, equity(sid, quantity=4), TODAY)["preview"]["position_id"]
    more = service.place_order(conn, {"strategy_id": sid, "action": "increase", "position_id": pid, "quantity": 2,
                                      "date": "2026-01-07"}, TODAY)
    assert more["preview"]["quantity"] == 2
    close = service.place_order(conn, {"strategy_id": sid, "action": "close", "position_id": pid,
                                       "date": "2026-01-07"}, TODAY)
    assert close["preview"]["quantity"] == 6


def test_a_new_strategy_trades_the_last_close_when_there_is_no_session_today(conn):
    saturday = dt.date(2026, 1, 17)
    sid = store.create_strategy(conn, "Week-end", "CTO", 100_000, "2026-01-17")
    placed = service.place_order(conn, equity(sid, quantity=2, date="2026-01-17"), saturday)
    assert placed["preview"]["exec_day"] == "2026-01-16"
    snap = service.strategy_snapshot(conn, store.get_strategy(conn, sid), saturday)
    assert not snap["violations"] and snap["kpis"]["n_open_positions"] == 1
    assert snap["positions"][0]["quantity"] == 2


def test_a_requested_date_after_the_last_stored_quote_is_refused_instead_of_moved_earlier(conn, monkeypatch):
    from patrick.fund import prices

    def truncated(symbol, start=None):
        df, currency = fs.fake_download(symbol, start)
        return (None, None) if df is None else (df[df.index <= "2025-12-19"], currency)
    monkeypatch.setattr(prices, "download_bars", truncated)
    sid = store.create_strategy(conn, "Hors ligne", "CTO", 100_000, "2025-12-01")
    stale = service.quote(conn, equity(sid, quantity=1, date="2026-01-12"), TODAY)
    assert not stale["ok"] and "pas de cotation après le 2025-12-19" in stale["blocking"][0]
    assert service.quote(conn, equity(sid, quantity=1, date="2025-12-18"), TODAY)["ok"]


def test_quotes_dated_after_today_are_never_used_for_an_execution(conn):
    sid = cto(conn)
    q = service.quote(conn, equity(sid, quantity=1, date="2026-01-16"), TODAY)
    assert q["ok"] and q["preview"]["exec_day"] == "2026-01-16"          # les cotations stockées vont jusqu'en octobre


def test_a_future_order_on_or_after_the_contract_expiry_is_refused(conn):
    sid = cto(conn)
    today = dt.date(2026, 5, 27)
    cl = {"strategy_id": sid, "instrument_kind": "future", "side": "long", "quantity": 1,
          "spec": {"root": "CL", "year": 2026, "month": 6}}
    late = service.quote(conn, {**cl, "date": "2026-05-26"}, today)
    assert not late["ok"] and "contrat échu le 2026-05-20" in late["blocking"][0]
    early = service.quote(conn, {**cl, "date": "2026-05-18"}, today)
    assert early["ok"], early["blocking"]


def test_a_fractional_reduce_is_refused_like_a_fractional_open(conn):
    sid = cto(conn)
    pid = service.place_order(conn, equity(sid, quantity=4), TODAY)["preview"]["position_id"]
    reduce = {"strategy_id": sid, "action": "reduce", "position_id": pid, "date": "2026-01-09"}
    half = service.quote(conn, {**reduce, "quantity": 0.5}, TODAY)
    assert not half["ok"] and "quantité entière" in half["blocking"][0]
    assert service.quote(conn, {**reduce, "quantity": 1}, TODAY)["ok"]


def test_correcting_only_the_quantity_keeps_manual_price_fees_date_and_the_fee_seed(conn):
    sid = cto(conn)
    manual = service.place_order(conn, equity(sid, quantity=3, price=650.0, fees_mode="manual", fees=3.0), TODAY)
    service.correct_order(conn, manual["order_id"], {"quantity": 4}, TODAY)
    row = store.get_order(conn, manual["order_id"])
    assert row["quantity"] == 4 and row["ts"] == "2026-01-07"
    assert row["price"] == 650.0 and row["price_source"] == "manual"
    assert row["fees"] == 3.0 and row["fees_source"] == "manual"
    estimated = service.place_order(conn, equity(sid, "AAPL", quantity=5, date="2026-01-08"), TODAY)
    before = store.get_order(conn, estimated["order_id"])
    service.correct_order(conn, estimated["order_id"], {"quantity": 5}, TODAY)
    after = store.get_order(conn, estimated["order_id"])
    assert after["fee_seed"] == before["fee_seed"] and after["fees"] == before["fees"] and after["ts"] == "2026-01-08"
    service.correct_order(conn, manual["order_id"], {"quantity": 4, "price": ""}, TODAY)     # prix vide = cours du marché
    assert store.get_order(conn, manual["order_id"])["price_source"] == "market"


def test_two_concurrent_orders_cannot_spend_the_same_cash(tmp_path, monkeypatch, conn):
    import threading
    import time

    from patrick.fund import rules
    from patrick.tracking import db as trackdb

    sid = cto(conn, 10_000)
    original = rules.validate

    def slow_validate(*args, **kwargs):
        out = original(*args, **kwargs)
        time.sleep(0.3)                                  # élargit la fenêtre entre validation et écriture
        return out
    monkeypatch.setattr(rules, "validate", slow_validate)
    results = []

    def worker():
        c = trackdb.connect(str(tmp_path / "patrick.db"))
        try:
            results.append(service.place_order(c, equity(sid, quantity=12), TODAY)["order_id"])    # ~9 200 € : un seul tient
        except service.FundRuleError as exc:
            results.append(exc)
        finally:
            c.close()
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_orders(conn, sid)) == 1
    assert sum(isinstance(r, service.FundRuleError) for r in results) == 1
