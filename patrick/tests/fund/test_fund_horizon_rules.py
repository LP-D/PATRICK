"""Fonds, pilote automatique : règle « direction + sortie à l'horizon » (spec 2026-10-16, §4). Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pandas as pd
import pytest

from patrick.fund import store, systematic
from patrick.tracking import db as trackdb

TODAY = dt.date(2026, 1, 16)
UP, DOWN, NEUTRAL = 1, -1, 0


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _signals(values: dict[str, int]) -> pd.Series:
    return pd.Series(list(values.values()), index=pd.to_datetime(list(values)), dtype=float)


def _brief(events):
    return [(e["signal"], e["action"], e["side"], e["requested"]) for e in events]


# --------------------------------------------------------------------------- machine à états

def test_a_lone_signal_opens_then_closes_at_the_horizon():
    events = systematic.decide_directional(_signals({"2026-01-05": UP}), allow_short=False, sessions=3)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-09", "close", "long", "2026-01-09")]
    assert events[1]["reason"] == "horizon"


def test_a_same_side_signal_before_the_expiry_renews_without_any_order():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-06": UP, "2026-01-07": UP}),
                                           allow_short=False, sessions=3)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-13", "close", "long", "2026-01-13")]       # 3 séances après le dernier renouvellement


def test_an_opposite_signal_closes_and_reopens_the_same_day():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-06": DOWN}), allow_short=True, sessions=3)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-06", "close", "long", "2026-01-07"),
                              ("2026-01-06", "open", "short", "2026-01-07"),
                              ("2026-01-12", "close", "short", "2026-01-12")]
    assert events[1]["reason"] == events[2]["reason"] == "signal"


def test_without_short_selling_an_opposite_signal_only_closes():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-06": DOWN}), allow_short=False, sessions=3)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-06", "close", "long", "2026-01-07")]


def test_a_neutral_signal_changes_nothing():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-06": NEUTRAL}), allow_short=False, sessions=3)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-09", "close", "long", "2026-01-09")]


def test_a_signal_executed_on_the_expiry_day_still_renews():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-07": UP}), allow_short=False, sessions=2)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-12", "close", "long", "2026-01-12")]          # pas de fermeture-réouverture le même jour


def test_a_signal_after_the_expiry_opens_a_new_position():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-09": UP}), allow_short=False, sessions=2)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-08", "close", "long", "2026-01-08"),
                              ("2026-01-09", "open", "long", "2026-01-10"),
                              ("2026-01-13", "close", "long", "2026-01-13")]


def test_a_retired_rule_opens_and_renews_nothing_after_its_retirement_date():
    signals = _signals({"2026-01-05": UP, "2026-01-06": UP, "2026-01-07": UP})

    events = systematic.decide_directional(signals, allow_short=False, sessions=3, retired_on="2026-01-05")

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-09", "close", "long", "2026-01-09")]


def test_without_a_horizon_the_position_lasts_until_the_signal_turns():
    events = systematic.decide_directional(_signals({"2026-01-05": UP, "2026-01-06": UP, "2026-01-07": NEUTRAL}),
                                           allow_short=False, sessions=None)

    assert _brief(events) == [("2026-01-05", "open", "long", "2026-01-06"),
                              ("2026-01-07", "close", "long", "2026-01-08")]


# --------------------------------------------------------------------------- configuration

def _config(trial_id=1, **kw) -> dict:
    cfg = {"trial_id": trial_id, "segment": "live", "allow_short": False, "signal": {"mode": "direction"},
           "hold": {"mode": "horizon", "sessions": 5}, "instrument": {"kind": "equity", "symbol": "AAPL"},
           "sizing": {"amount": 5000}}
    cfg.update(kw)
    return cfg


def test_the_direction_mode_needs_no_thresholds():
    cfg = systematic.validate_config(_config())

    assert cfg["signal"] == {"mode": "direction", "min_confidence": 0.0}
    assert cfg["hold"] == {"mode": "horizon", "sessions": 5}


@pytest.mark.parametrize("patch, message", [
    ({"signal": {"mode": "magie"}}, "signal"),
    ({"signal": {"mode": "direction", "min_confidence": 1.2}}, "min_confidence"),
    ({"hold": {"mode": "horizon", "sessions": 0}}, "sessions"),
    ({"hold": {"mode": "horizon", "sessions": "5"}}, "sessions"),
    ({"hold": {"mode": "perpétuel"}}, "hold"),
    ({"since": "pas une date"}, "since"),
    ({"retired_on": 5}, "retired_on"),
    ({"managed": "oui"}, "managed"),
])
def test_validate_config_rejects_bad_new_fields(patch, message):
    with pytest.raises(store.FundError, match=message):
        systematic.validate_config(_config(**patch))


def test_a_threshold_rule_keeps_its_old_behaviour_and_defaults():
    cfg = systematic.validate_config({"trial_id": 1, "enter": 0.6, "exit": 0.5, "instrument": {"kind": "equity", "symbol": "AAPL"},
                                      "sizing": {"amount": 1000}})

    assert cfg["signal"] == {"mode": "score"} and cfg["hold"] == {"mode": "signal"}
    assert "since" not in cfg and "managed" not in cfg


def test_cfd_quantities_may_be_fractional_but_futures_stay_whole():
    cfd = {"instrument": {"kind": "cfd", "symbol": "^GSPC", "spec": {}}, "sizing": {"quantity": 0.8317}}
    assert systematic.validate_config(_config(**cfd))["sizing"] == {"quantity": 0.8317}
    for bad in (0, -1, "x"):
        with pytest.raises(store.FundError, match="quantité"):
            systematic.validate_config(_config(**{**cfd, "sizing": {"quantity": bad}}))
    future = {"instrument": {"kind": "future", "spec": {"root": "ES", "year": 2026, "month": 12}}, "allow_short": True}
    assert systematic.validate_config(_config(**future, sizing={"quantity": 2}))["sizing"] == {"quantity": 2}
    with pytest.raises(store.FundError, match="quantité"):
        systematic.validate_config(_config(**future, sizing={"quantity": 1.5}))


# --------------------------------------------------------------------------- de la base aux ordres

def _model(conn, rows: dict[str, tuple[int, float]], segment="live") -> int:
    """`rows` : jour du signal -> (classe prédite, probabilité de cette classe) ; classes 0/1 = baisse, 2/3 = hausse."""
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, "run1", target="^GSPC", horizon=3, snapshot_id="snap1", config_json="{}",
                       config_hash="h", git_sha="sha", seed=42)
    trial_id = trackdb.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
    for ts, (y_pred, proba) in rows.items():
        conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba) VALUES (?, ?, ?, 3, ?, ?)",
                     (trial_id, ts, segment, y_pred, proba))
    conn.commit()
    return trial_id


def _rule(conn, rows, *, capital=100_000, **kw):
    sid = store.create_strategy(conn, "Auto", "CTO", capital, "2026-01-05")
    tid = _model(conn, rows)
    return sid, systematic.create_rule(conn, sid, "Auto AAPL h3", _config(tid, **kw)), tid


def test_the_signal_direction_comes_from_the_predicted_class_not_from_the_probability(conn):
    """Un haussier peu confiant (classe 3, probabilité 0,4) reste un long : l'ancien score à seuils en faisait un vendeur."""
    _, rule_id, _tid = _rule(conn, {"2026-01-05": (3, 0.40), "2026-01-06": (0, 0.45)}, allow_short=False)

    series = systematic.load_signals(conn, systematic.get_rule(conn, rule_id)["config"])

    assert series.to_dict() == {pd.Timestamp("2026-01-05"): 1.0, pd.Timestamp("2026-01-06"): -1.0}


def test_min_confidence_makes_a_weak_signal_neutral(conn):
    _, rule_id, _ = _rule(conn, {"2026-01-05": (3, 0.40), "2026-01-06": (3, 0.70)},
                          signal={"mode": "direction", "min_confidence": 0.5})

    series = systematic.load_signals(conn, systematic.get_rule(conn, rule_id)["config"])

    assert series.to_dict() == {pd.Timestamp("2026-01-05"): 0.0, pd.Timestamp("2026-01-06"): 1.0}


def test_since_drops_the_older_signals(conn):
    _, rule_id, _ = _rule(conn, {"2026-01-02": (3, 0.6), "2026-01-05": (3, 0.6)}, since="2026-01-05")

    series = systematic.load_signals(conn, systematic.get_rule(conn, rule_id)["config"])

    assert list(series.index) == [pd.Timestamp("2026-01-05")]


def test_apply_opens_renews_and_closes_at_the_horizon(conn):
    sid, rule_id, _ = _rule(conn, {"2026-01-05": (3, 0.6), "2026-01-06": (3, 0.6)}, hold={"mode": "horizon", "sessions": 3})

    res = systematic.apply(conn, rule_id, TODAY)

    assert [(o["action"], o["requested"]) for o in res["placed"]] == [("open", "2026-01-06"), ("close", "2026-01-12")]
    orders = store.list_orders(conn, sid)
    assert [(o["ts"], o["action"]) for o in orders] == [("2026-01-06", "open"), ("2026-01-12", "close")]
    assert orders[1]["position_id"] == orders[0]["position_id"]
    assert systematic.apply(conn, rule_id, TODAY)["placed"] == []                     # idempotent


def test_a_close_in_the_future_stays_pending(conn):
    sid, rule_id, _ = _rule(conn, {"2026-01-14": (3, 0.6)}, hold={"mode": "horizon", "sessions": 10})

    res = systematic.apply(conn, rule_id, TODAY)

    assert [o["action"] for o in res["placed"]] == ["open"]
    assert [(p["action"], p["requested"]) for p in res["pending"]] == [("close", "2026-01-29")]
    assert len(store.list_orders(conn, sid)) == 1


def test_a_cfd_rule_sizes_by_a_fractional_quantity(conn):
    sid, rule_id, _ = _rule(conn, {"2026-01-05": (0, 0.6)}, allow_short=True,
                            instrument={"kind": "cfd", "symbol": "^GSPC", "spec": {}}, sizing={"quantity": 0.8317})

    systematic.apply(conn, rule_id, TODAY)

    opened = store.list_orders(conn, sid)[0]
    assert opened["side"] == "short" and opened["quantity"] == pytest.approx(0.8317)
