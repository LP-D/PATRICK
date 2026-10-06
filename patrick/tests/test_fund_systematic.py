"""Fonds, chantier 3 : mode systématique « modèle ML avec seuils ». Aucun réseau."""
from __future__ import annotations

import datetime as dt
import json

import fund_support as fs
import pandas as pd
import pytest

from patrick.fund import service, store, systematic
from patrick.tracking import db as trackdb

TODAY = dt.date(2026, 1, 16)

# jour du signal -> score haussier (P(hausse) du modèle)
SCORES = {"2026-01-05": 0.55, "2026-01-06": 0.65, "2026-01-07": 0.58, "2026-01-08": 0.45, "2026-01-09": 0.50,
          "2026-01-12": 0.70, "2026-01-13": 0.62, "2026-01-14": 0.40, "2026-01-15": 0.61}


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _model(conn, scores=SCORES, segment="holdout") -> int:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, "run1", target="^GSPC", horizon=5, snapshot_id="snap1", config_json="{}",
                       config_hash="h", git_sha="sha", seed=42)
    trial_id = trackdb.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
    for ts, score in scores.items():
        y_pred, proba = (3, score) if score >= 0.5 else (0, 1 - score)    # classe 3 = hausse forte, 0 = baisse forte
        conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba) VALUES (?, ?, ?, 3, ?, ?)",
                     (trial_id, ts, segment, y_pred, proba))
    conn.commit()
    return trial_id


def _config(trial_id, **kw) -> dict:
    cfg = {"trial_id": trial_id, "segment": "holdout", "enter": 0.6, "exit": 0.5, "allow_short": False,
           "instrument": {"kind": "equity", "symbol": "AAPL"}, "sizing": {"amount": 5000}}
    cfg.update(kw)
    return cfg


def _rule(conn, capital=100_000, **kw):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", capital, "2026-01-05")
    tid = _model(conn)
    return sid, systematic.create_rule(conn, sid, "ML seuils", _config(tid, **kw))


# --------------------------------------------------------------------------- machine à états

def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2026-01-05", periods=len(values)))


def _acts(signals):
    return [(s["ts"].strftime("%m-%d"), s["action"], s["side"]) for s in signals]


def test_decide_enters_at_threshold_and_exits_with_hysteresis():
    sig = systematic.decide(_series([0.55, 0.60, 0.55, 0.52, 0.49]), enter=0.6, exit_=0.5, allow_short=False)
    assert _acts(sig) == [("01-06", "open", "long"), ("01-09", "close", "long")]   # 0,55 et 0,52 : on garde


def test_decide_never_shorts_unless_allowed():
    scores = _series([0.30, 0.45, 0.70])
    assert _acts(systematic.decide(scores, 0.6, 0.5, allow_short=False)) == [("01-07", "open", "long")]
    assert _acts(systematic.decide(scores, 0.6, 0.5, allow_short=True)) == [
        ("01-05", "open", "short"), ("01-07", "close", "short"), ("01-07", "open", "long")]


def test_decide_flips_long_to_short_with_two_orders_the_same_day():
    sig = systematic.decide(_series([0.70, 0.55, 0.30]), enter=0.6, exit_=0.5, allow_short=True)
    assert _acts(sig) == [("01-05", "open", "long"), ("01-07", "close", "long"), ("01-07", "open", "short")]


def test_decide_ignores_missing_scores():
    sig = systematic.decide(_series([0.70, float("nan"), 0.55]), enter=0.6, exit_=0.5, allow_short=False)
    assert _acts(sig) == [("01-05", "open", "long")]


# --------------------------------------------------------------------------- configuration

@pytest.mark.parametrize("patch, message", [
    ({"enter": 0.5}, "enter"),
    ({"enter": 1.0}, "enter"),
    ({"exit": 0.7}, "exit"),
    ({"exit": 0.4}, "exit"),
    ({"segment": "demain"}, "segment"),
    ({"instrument": {"kind": "option", "symbol": "AAPL"}}, "instrument"),
    ({"instrument": {"kind": "equity", "symbol": ""}}, "symbole"),
    ({"sizing": {}}, "montant"),
    ({"sizing": {"quantity": 2}}, "montant"),
    ({"allow_short": True}, "découvert"),
])
def test_validate_config_rejects_bad_values(patch, message):
    with pytest.raises(store.FundError, match=message):
        systematic.validate_config(_config(1, **patch))


def test_validate_config_future_needs_root_year_and_month():
    base = _config(1, allow_short=True, sizing={"quantity": 1},
                   instrument={"kind": "future", "spec": {"root": "ES", "year": 2026, "month": 12}})
    assert systematic.validate_config(base)["instrument"]["spec"]["month"] == 12
    for spec in ({"root": "ES"}, {"root": "ES", "year": 2026, "month": 13}, {"root": "ES", "year": "2026", "month": 12},
                 {"year": 2026, "month": 12}):
        with pytest.raises(store.FundError, match="future"):
            systematic.validate_config({**base, "instrument": {"kind": "future", "spec": spec}})


def test_validate_config_cfd_short_needs_a_whole_quantity():
    cfg = _config(1, allow_short=True, instrument={"kind": "cfd", "symbol": "^GSPC", "spec": {"leverage": 2}},
                  sizing={"quantity": 3})
    assert systematic.validate_config(cfg)["sizing"] == {"quantity": 3}
    with pytest.raises(store.FundError, match="quantité"):
        systematic.validate_config({**cfg, "sizing": {"quantity": 1.5}})


def test_create_rule_needs_an_existing_model_with_signals(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    with pytest.raises(store.FundError, match="essai"):
        systematic.create_rule(conn, sid, "x", _config(999))
    tid = _model(conn)
    with pytest.raises(store.FundError, match="signal"):
        systematic.create_rule(conn, sid, "x", _config(tid, segment="live"))


def test_create_rule_counts_the_thresholds_as_a_configuration_tried(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _model(conn)
    before = conn.execute("SELECT COUNT(*) FROM trial_registry").fetchone()[0]

    rule_id = systematic.create_rule(conn, sid, "ML seuils", _config(tid))

    assert conn.execute("SELECT COUNT(*) FROM trial_registry").fetchone()[0] == before + 1
    assert conn.execute("SELECT COUNT(*) FROM simulation").fetchone()[0] == 1
    assert systematic.get_rule(conn, rule_id)["config"]["enter"] == 0.6


def test_fund_rule_is_a_personal_table_never_synced_to_github(conn):
    from patrick import sync
    assert "fund_rule" in sync.personal_tables(conn)


# --------------------------------------------------------------------------- plan

def test_plan_executes_one_session_after_the_signal_and_links_close_to_open(conn):
    _, rule_id = _rule(conn)
    plan = systematic.plan(conn, systematic.get_rule(conn, rule_id))

    assert [(p["signal"], p["action"], p["requested"]) for p in plan] == [
        ("2026-01-06", "open", "2026-01-07"), ("2026-01-08", "close", "2026-01-09"),
        ("2026-01-12", "open", "2026-01-13"), ("2026-01-14", "close", "2026-01-15"),
        ("2026-01-15", "open", "2026-01-16")]
    first_open, first_close = plan[0]["request"], plan[1]["request"]
    assert first_close["position_id"] == first_open["position_id"]
    assert plan[2]["request"]["position_id"] != first_open["position_id"]
    assert first_open["note"] == f"auto:{rule_id}:2026-01-06:open"
    assert first_open["amount"] == 5000 and first_open["symbol"] == "AAPL" and first_open["side"] == "long"
    assert all(p["requested"] > p["signal"] for p in plan)                 # jamais le jour du signal


# --------------------------------------------------------------------------- apply

def test_apply_places_the_orders_at_the_next_session_close(conn):
    sid, rule_id = _rule(conn)

    res = systematic.apply(conn, rule_id, TODAY)

    assert [o["action"] for o in res["placed"]] == ["open", "close", "open", "close", "open"]
    assert res["refused"] == [] and res["pending"] == [] and res["already"] == 0
    orders = store.list_orders(conn, sid)
    assert [(o["ts"], o["action"]) for o in orders] == [
        ("2026-01-07", "open"), ("2026-01-09", "close"), ("2026-01-13", "open"), ("2026-01-15", "close"),
        ("2026-01-16", "open")]
    assert orders[0]["price"] == pytest.approx(fs.price_on("AAPL", "2026-01-07"))
    assert orders[0]["note"] == f"auto:{rule_id}:2026-01-06:open"
    assert orders[1]["position_id"] == orders[0]["position_id"]


def test_apply_twice_never_duplicates_orders(conn):
    sid, rule_id = _rule(conn)
    systematic.apply(conn, rule_id, TODAY)

    again = systematic.apply(conn, rule_id, TODAY)

    assert again["placed"] == [] and again["already"] == 5
    assert len(store.list_orders(conn, sid)) == 5


def test_apply_keeps_a_future_execution_pending_then_places_it_later(conn):
    sid, rule_id = _rule(conn)

    early = systematic.apply(conn, rule_id, dt.date(2026, 1, 15))

    assert [p["signal"] for p in early["pending"]] == ["2026-01-15"]
    assert len(store.list_orders(conn, sid)) == 4
    late = systematic.apply(conn, rule_id, TODAY)
    assert [o["action"] for o in late["placed"]] == ["open"] and late["already"] == 4


def test_apply_reports_refused_orders_and_skips_the_close_of_a_refused_open(conn):
    sid, rule_id = _rule(conn, capital=1000)                  # 5000 € demandés pour 1000 € de capital

    res = systematic.apply(conn, rule_id, TODAY)

    assert res["placed"] == []
    assert len(res["refused"]) == 3 and all(r["reasons"] for r in res["refused"])    # les trois ouvertures
    assert [s["action"] for s in res["skipped"]] == ["close", "close"]               # fermetures sans position
    assert store.list_orders(conn, sid) == []


def test_apply_on_a_cfd_short_rule_opens_and_closes_in_both_directions(conn):
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _model(conn, scores={"2026-01-06": 0.70, "2026-01-07": 0.30, "2026-01-08": 0.55})
    cfg = _config(tid, allow_short=True, instrument={"kind": "cfd", "symbol": "^GSPC", "spec": {"leverage": 2}},
                  sizing={"quantity": 2})
    rule_id = systematic.create_rule(conn, sid, "CFD long/short", cfg)

    res = systematic.apply(conn, rule_id, TODAY)

    assert res["refused"] == [], res["refused"]
    assert [(o["action"], o["side"]) for o in store.list_orders(conn, sid)] == [
        ("open", "long"), ("close", "long"), ("open", "short"), ("close", "short")]


def test_list_rules_returns_the_rules_of_a_strategy(conn):
    sid, rule_id = _rule(conn)
    assert [r["rule_id"] for r in systematic.list_rules(conn, sid)] == [rule_id]
    assert json.loads(conn.execute("SELECT config_json FROM fund_rule").fetchone()[0])["enter"] == 0.6


def test_service_is_the_only_way_orders_are_written(conn, monkeypatch):
    """Les ordres automatiques passent par `service.place_order` (mêmes règles que les manuels)."""
    _, rule_id = _rule(conn)
    calls = []
    real = service.place_order
    monkeypatch.setattr(service, "place_order", lambda c, req, today=None: calls.append(req) or real(c, req, today))

    systematic.apply(conn, rule_id, TODAY)

    assert len(calls) == 5
