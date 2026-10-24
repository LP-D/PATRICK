"""Fonds : tous les modèles au choix (p de Diebold-Mariano, instrument conseillé) ; une règle suit le champion. Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_selection import World

from patrick.fund import store, systematic

TODAY = dt.date(2026, 1, 16)
UP, DOWN = 3, 0
SIGNALS = [("2026-01-14", UP, 0.6), ("2026-01-15", DOWN, 0.6)]


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


# --------------------------------------------------------------------------- sélecteur : tous les modèles

def test_every_cell_is_offered_once_with_its_p_value_and_a_suggested_instrument(conn, world):
    world.cell("AAPL", 1, live=SIGNALS, dm_p=0.012)
    world.cell("AAPL", 5, live=SIGNALS, dm_p=0.4)
    world.cell("GC=F", 1, live=SIGNALS, dm_p=None)
    world.cell("XLK", 1, live=SIGNALS)
    world.cell("^GSPC", 3, live=SIGNALS)

    models = {(m["target"], m["horizon"]): m for m in systematic.available_models(conn)}

    assert set(models) == {("AAPL", 1), ("AAPL", 5), ("GC=F", 1), ("XLK", 1), ("^GSPC", 3)}
    assert models[("AAPL", 1)]["dm_p"] == 0.012 and models[("GC=F", 1)]["dm_p"] is None
    assert models[("AAPL", 1)]["instrument_hint"] == {"kind": "equity", "symbol": "AAPL"}
    assert models[("XLK", 1)]["instrument_hint"] == {"kind": "etf", "symbol": "XLK"}
    assert models[("GC=F", 1)]["instrument_hint"] == {"kind": "cfd", "symbol": "GC=F"}
    assert models[("^GSPC", 3)]["instrument_hint"] == {"kind": "cfd", "symbol": "^GSPC"}
    assert models[("AAPL", 1)]["segments"] == {"live": 2}


def test_a_cell_offers_its_champion_not_an_older_run(conn, world):
    world.cell("AAPL", 1, live=SIGNALS, suffix="_old", champion=False)
    champion = world.cell("AAPL", 1, live=SIGNALS, suffix="_new")

    (model,) = systematic.available_models(conn)

    assert model["trial_id"] == champion and model["champion"] is True


def test_without_a_champion_the_latest_run_of_the_cell_is_offered(conn, world):
    world.cell("AAPL", 1, live=SIGNALS, suffix="_a", champion=False)
    conn.execute("UPDATE run SET started_at = '2020-01-01 00:00:00' WHERE run_id = 'run_AAPL_1_a'")
    newest = world.cell("AAPL", 1, live=SIGNALS, suffix="_b", champion=False)

    (model,) = systematic.available_models(conn)

    assert model["trial_id"] == newest and model["champion"] is False


# --------------------------------------------------------------------------- suivre le champion

def _rule(conn, world, *, follow=True, segment="live", mode="direction"):
    tid = world.cell("AAPL", 3, live=SIGNALS)
    sid = store.create_strategy(conn, "Suit le champion", "CTO", 100_000, "2026-01-05")
    cfg = {"trial_id": tid, "segment": segment, "allow_short": False, "instrument": {"kind": "equity", "symbol": "AAPL"},
           "sizing": {"amount": 5000}, "follow_champion": follow}
    if mode == "direction":
        cfg.update(signal={"mode": "direction"}, hold={"mode": "horizon", "sessions": 3})
    else:
        cfg.update(enter=0.6, exit=0.5)
    return sid, tid, systematic.create_rule(conn, sid, "Ma règle", cfg)


def test_follow_champion_must_be_a_boolean_and_is_kept_only_when_true():
    base = {"trial_id": 1, "signal": {"mode": "direction"}, "instrument": {"kind": "equity", "symbol": "AAPL"}, "sizing": {"amount": 1}}

    assert systematic.validate_config({**base, "follow_champion": True})["follow_champion"] is True
    assert "follow_champion" not in systematic.validate_config({**base, "follow_champion": False})
    assert "follow_champion" not in systematic.validate_config(base)
    with pytest.raises(store.FundError, match="follow_champion"):
        systematic.validate_config({**base, "follow_champion": "oui"})


def test_a_better_champion_replaces_the_model_of_a_following_rule(conn, world):
    sid, _, old_rule = _rule(conn, world)
    new_tid = world.cell("AAPL", 3, live=SIGNALS, suffix="_b")                # un meilleur modèle devient champion

    report = systematic.roll_to_champions(conn, TODAY)

    assert [(r["retired"], r["trial_id"]) for r in report] == [(old_rule, new_tid)]
    rules = {r["rule_id"]: r for r in systematic.list_rules(conn, sid)}
    assert rules[old_rule]["config"]["retired_on"] == "2026-01-15"
    fresh = rules[report[0]["created"]]
    assert fresh["config"]["trial_id"] == new_tid and fresh["config"]["since"] == "2026-01-16" and fresh["name"] == "Ma règle"
    assert fresh["config"]["follow_champion"] is True and "retired_on" not in fresh["config"]
    assert systematic.roll_to_champions(conn, TODAY) == []                     # idempotent : la nouvelle règle suit déjà le champion


def test_a_rule_that_does_not_follow_is_left_alone(conn, world):
    sid, _, no_follow = _rule(conn, world, follow=False)
    world.cell("AAPL", 3, live=SIGNALS, suffix="_b")

    assert systematic.roll_to_champions(conn, TODAY) == []
    assert [r["rule_id"] for r in systematic.list_rules(conn, sid)] == [no_follow]
    assert "retired_on" not in systematic.get_rule(conn, no_follow)["config"]


def test_a_refused_champion_keeps_the_old_rule(conn, world):
    sid, _, old_rule = _rule(conn, world)
    world.cell("AAPL", 3, live=SIGNALS, suffix="_b", f1=0.99)                  # le nouveau champion est suspect : refusé

    report = systematic.roll_to_champions(conn, TODAY)

    assert len(report) == 1 and report[0]["rule_id"] == old_rule and "suspect" in report[0]["error"]
    assert [r["rule_id"] for r in systematic.list_rules(conn, sid)] == [old_rule]


def _threshold_world(conn, world, probabilities: dict[str, float]):
    tid = world.cell("AAPL", 3, live=None)
    for day, p in probabilities.items():
        conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba, p_up) VALUES (?, ?, 'live', NULL, 3, 0.6, ?)",
                     (tid, day, p))
    conn.commit()
    return tid


def test_a_threshold_rule_that_is_retired_closes_its_open_position(conn, world):
    """Une règle à seuils tient sa position tant que le signal tient : retirée, elle doit la fermer."""
    tid = _threshold_world(conn, world, {"2026-01-13": 0.7, "2026-01-14": 0.7})
    sid = store.create_strategy(conn, "Seuils", "CTO", 100_000, "2026-01-05")
    rule_id = systematic.create_rule(conn, sid, "Seuils", {
        "trial_id": tid, "segment": "live", "enter": 0.6, "exit": 0.5, "instrument": {"kind": "equity", "symbol": "AAPL"},
        "sizing": {"amount": 5000}, "follow_champion": True})
    systematic.apply(conn, rule_id, TODAY)
    assert [(o["ts"], o["action"]) for o in store.list_orders(conn, sid)] == [("2026-01-14", "open")]

    systematic.retire_rule(conn, rule_id, "2026-01-15")
    result = systematic.apply(conn, rule_id, TODAY)

    assert [o["action"] for o in result["placed"]] == ["close"]
    assert [(o["ts"], o["action"]) for o in store.list_orders(conn, sid)][-1] == ("2026-01-16", "close")


def test_since_and_retired_on_now_bound_threshold_rules_too(conn, world):
    tid = _threshold_world(conn, world, {"2026-01-12": 0.7, "2026-01-13": 0.3, "2026-01-14": 0.7})
    sid = store.create_strategy(conn, "Seuils", "CTO", 100_000, "2026-01-05")
    rule_id = systematic.create_rule(conn, sid, "Seuils", {
        "trial_id": tid, "segment": "live", "enter": 0.6, "exit": 0.5, "allow_short": True, "since": "2026-01-13",
        "retired_on": "2026-01-13", "instrument": {"kind": "cfd", "symbol": "^GSPC"}, "sizing": {"quantity": 1}})

    plan = systematic.plan(conn, systematic.get_rule(conn, rule_id))

    assert [(p["signal"], p["action"], p["side"]) for p in plan] == [("2026-01-13", "open", "short"), ("2026-01-13", "close", "short")]
