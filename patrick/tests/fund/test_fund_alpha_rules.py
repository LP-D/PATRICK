"""Fonds, chantier 3 : règle pilotée par un modèle d'alpha. Chaque signal ouvre une paire : l'actif d'un côté, le
benchmark de l'autre pour β × le montant de l'actif (couverture). Aucun réseau (cotations factices)."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_systematic import SCORES, _model

from patrick.config.schema import RunConfig
from patrick.features import alpha_target as at
from patrick.fund import prices, store, systematic

TODAY = dt.date(2026, 1, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _alpha_model(conn, scores=SCORES) -> int:
    """Run alpha AAPL contre ^GSPC (même séance : pas de décalage), avec signaux holdout."""
    tid = _model(conn, scores=scores)
    cfg = RunConfig.model_validate({
        "objective": {"target_symbol": "AAPL", "horizons": [5], "target_kind": "alpha", "benchmark": "^GSPC"},
        "universe": {"yf_tickers": ["GOOD1"], "start_date": "2018-01-01"}})
    conn.execute("UPDATE run SET target = ?, status = 'done', config_json = ? WHERE run_id = 'run1'",
                 (cfg.objective.run_label(), cfg.model_dump_json()))
    conn.execute("UPDATE trial SET is_best = 1 WHERE trial_id = ?", (tid,))
    conn.commit()
    return tid


def _config(tid, **kw) -> dict:
    cfg = {"trial_id": tid, "segment": "holdout", "enter": 0.6, "exit": 0.5, "allow_short": False,
           "instrument": {"kind": "equity", "symbol": "AAPL"}, "sizing": {"amount": 5000},
           "hedge": {"kind": "cfd", "spec": {"leverage": 5}}}
    cfg.update(kw)
    return cfg


def _rule(conn, capital=100_000, **kw):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", capital, "2026-01-05")
    tid = _alpha_model(conn)
    return sid, systematic.create_rule(conn, sid, "Alpha couvert", _config(tid, **kw))


def _beta_at(conn, day: str) -> float:
    a = prices.ensure_bars(conn, "AAPL").df["close"]
    b = prices.ensure_bars(conn, "^GSPC").df["close"]
    return float(at.point_in_time_beta(a, b).loc[:day].dropna().iloc[-1])


# --------------------------------------------------------------------------- configuration

def test_alpha_models_are_offered_with_their_kind_and_benchmark(conn):
    _alpha_model(conn)
    (m,) = systematic.available_models(conn)
    assert (m["kind"], m["asset"], m["benchmark"]) == ("alpha", "AAPL", "^GSPC")


def test_an_alpha_rule_needs_a_hedge_and_a_raw_rule_refuses_one(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _alpha_model(conn)
    no_hedge = {k: v for k, v in _config(tid).items() if k != "hedge"}
    with pytest.raises(store.FundError, match="couverture"):
        systematic.create_rule(conn, sid, "x", no_hedge)

    conn.execute("UPDATE run SET target = '^GSPC', config_json = '{}' WHERE run_id = 'run1'")
    conn.commit()
    with pytest.raises(store.FundError, match="alpha"):
        systematic.create_rule(conn, sid, "x", _config(tid))


def test_the_traded_instrument_must_be_the_models_target(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _alpha_model(conn)
    with pytest.raises(store.FundError, match="AAPL"):
        systematic.create_rule(conn, sid, "x", _config(tid, instrument={"kind": "equity", "symbol": "MC.PA"}))


def test_the_instrument_symbol_defaults_to_the_models_target(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _alpha_model(conn)
    rule_id = systematic.create_rule(conn, sid, "x", _config(tid, instrument={"kind": "equity"}))
    assert systematic.get_rule(conn, rule_id)["config"]["instrument"]["symbol"] == "AAPL"


@pytest.mark.parametrize("hedge, message", [
    ({"kind": "equity"}, "couverture"),
    ({"kind": "future"}, "future"),
    ({"kind": "cfd", "spec": {"leverage": "x"}}, "levier"),
])
def test_bad_hedge_is_refused(conn, hedge, message):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _alpha_model(conn)
    with pytest.raises(store.FundError, match=message):
        systematic.create_rule(conn, sid, "x", _config(tid, hedge=hedge))


def test_the_hedge_defaults_to_the_models_benchmark(conn):
    _, rule_id = _rule(conn)
    assert systematic.get_rule(conn, rule_id)["config"]["hedge"]["symbol"] == "^GSPC"


# --------------------------------------------------------------------------- exécution

def test_apply_opens_the_asset_and_the_beta_weighted_hedge(conn):
    sid, rule_id = _rule(conn)

    res = systematic.apply(conn, rule_id, TODAY)

    assert res["refused"] == [], res["refused"]
    orders = store.list_orders(conn, sid)
    first_asset, first_hedge = orders[0], orders[1]
    assert (first_asset["symbol"], first_asset["side"], first_asset["action"]) == ("AAPL", "long", "open")
    assert (first_hedge["symbol"], first_hedge["side"], first_hedge["instrument_kind"]) == ("^GSPC", "short", "cfd")
    beta = _beta_at(conn, "2026-01-06")
    asset_notional = first_asset["quantity"] * first_asset["price"] * first_asset["fx_rate"]
    hedge_notional = first_hedge["quantity"] * first_hedge["price"] * first_hedge["fx_rate"]
    assert beta > 0 and hedge_notional == pytest.approx(beta * asset_notional, rel=1e-3)
    assert first_asset["note"] == f"auto:{rule_id}:2026-01-06:open"
    assert first_hedge["note"] == f"auto:{rule_id}:2026-01-06:open_hedge"
    assert first_asset["ts"] == first_hedge["ts"] == "2026-01-07"


def test_apply_closes_both_legs_together(conn):
    sid, rule_id = _rule(conn)
    systematic.apply(conn, rule_id, TODAY)

    closes = [o for o in store.list_orders(conn, sid) if o["action"] == "close"]

    assert {(o["symbol"], o["ts"]) for o in closes[:2]} == {("AAPL", "2026-01-09"), ("^GSPC", "2026-01-09")}
    assert [o["note"].rsplit(":", 1)[1] for o in closes[:2]] in (["close", "close_hedge"], ["close_hedge", "close"])
    assert len(store.list_orders(conn, sid)) == 10          # 5 signaux (3 ouvertures, 2 fermetures) x 2 jambes


def test_apply_twice_never_duplicates_a_pair(conn):
    sid, rule_id = _rule(conn)
    systematic.apply(conn, rule_id, TODAY)
    again = systematic.apply(conn, rule_id, TODAY)
    assert again["placed"] == [] and again["already"] == 5 and len(store.list_orders(conn, sid)) == 10


def test_a_refused_asset_leg_places_no_hedge_and_skips_the_closes(conn):
    sid, rule_id = _rule(conn, capital=1000)
    res = systematic.apply(conn, rule_id, TODAY)

    assert res["placed"] == [] and store.list_orders(conn, sid) == []
    assert len(res["refused"]) == 3 and [s["action"] for s in res["skipped"]] == ["close", "close"]


def test_a_blocked_hedge_leaves_no_orphan_asset_leg(conn):
    """Levier de la jambe de couverture au-delà du plafond : rien n'est placé, jamais une jambe actif non couverte."""
    sid, rule_id = _rule(conn, hedge={"kind": "cfd", "spec": {"leverage": 500}})

    res = systematic.apply(conn, rule_id, TODAY)

    assert store.list_orders(conn, sid) == []
    assert len(res["refused"]) == 3 and any("levier" in " ".join(r["reasons"]) for r in res["refused"])


def test_an_unknown_beta_refuses_the_pair(conn):
    """Signal avant `min_obs` rendements communs : pas de β, donc pas de couverture possible."""
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2025-06-02")
    tid = _alpha_model(conn, scores={"2025-06-10": 0.8, "2025-06-11": 0.3})
    rule_id = systematic.create_rule(conn, sid, "x", _config(tid))

    res = systematic.apply(conn, rule_id, TODAY)

    assert store.list_orders(conn, sid) == []
    assert res["refused"] and any("β" in r for x in res["refused"] for r in x["reasons"])


def test_a_short_alpha_signal_shorts_the_asset_and_buys_the_hedge(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _alpha_model(conn, scores={"2026-01-06": 0.30, "2026-01-08": 0.55})
    cfg = _config(tid, allow_short=True, instrument={"kind": "cfd", "spec": {"leverage": 2}}, sizing={"quantity": 20})
    rule_id = systematic.create_rule(conn, sid, "short alpha", cfg)

    res = systematic.apply(conn, rule_id, TODAY)

    assert res["refused"] == [], res["refused"]
    opens = [o for o in store.list_orders(conn, sid) if o["action"] == "open"]
    assert [(o["symbol"], o["side"]) for o in opens] == [("AAPL", "short"), ("^GSPC", "long")]


def test_the_orders_still_go_through_the_fund_service(conn, monkeypatch):
    from patrick.fund import service
    _, rule_id = _rule(conn)
    placed = []
    real = service.place_order

    def spy(c, req, today=None):
        placed.append(req.get("symbol", "?"))
        return real(c, req, today)

    monkeypatch.setattr(service, "place_order", spy)
    systematic.apply(conn, rule_id, TODAY)
    assert "AAPL" in placed and "^GSPC" in placed


def test_a_failing_hedge_placement_rolls_the_asset_leg_back(conn, monkeypatch):
    """Si la seconde jambe échoue après la première (course, base occupée), la première est retirée : jamais
    de jambe actif non couverte."""
    from patrick.fund import service
    sid, rule_id = _rule(conn)
    real = service.place_order

    def flaky(c, req, today=None):
        if req.get("symbol") == "^GSPC":
            raise store.FundError("base occupée")
        return real(c, req, today)

    monkeypatch.setattr(service, "place_order", flaky)

    res = systematic.apply(conn, rule_id, TODAY)

    assert store.list_orders(conn, sid) == []
    assert len(res["refused"]) == 3 and any("base occupée" in " ".join(r["reasons"]) for r in res["refused"])


def test_drift_does_not_flag_the_hedge_notes_of_the_plan(conn):
    _, rule_id = _rule(conn)
    assert systematic.apply(conn, rule_id, TODAY)["drift"] == []
    assert systematic.apply(conn, rule_id, TODAY)["drift"] == []
