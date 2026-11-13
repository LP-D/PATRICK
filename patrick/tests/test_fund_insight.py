"""Fonds : journal des remplacements, attribution du P&L, témoins « toujours acheteur » / « pile ou face », plafonds de risque du pilote."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_selection import World

from patrick.fund import autopilot, insight, service, store, systematic

DAY0, DAY1 = dt.date(2026, 1, 15), dt.date(2026, 1, 16)
UP, DOWN = 3, 0
SIGNALS = [("2026-01-12", UP, 0.6), ("2026-01-13", UP, 0.6), ("2026-01-15", DOWN, 0.6)]


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _strategy(conn) -> str:
    return store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")


def _piloted(conn, world, settings: dict | None = None, cells=(("AAPL", 3), ("^GSPC", 3))) -> str:
    for target, horizon in cells:
        world.cell(target, horizon, live=SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, settings or {})
    autopilot.run(conn, sid, DAY0)
    autopilot.run(conn, sid, DAY1)                      # une position courte ouverte le 16 sur chaque cellule
    return sid


def _snapshot(conn, sid, today=DAY1):
    return service.strategy_snapshot(conn, store.get_strategy(conn, sid), today)


# --------------------------------------------------------------------------- journal des remplacements

def test_a_model_replacement_is_written_to_the_funds_journal_with_what_left(conn, world):
    sid = _piloted(conn, world)
    old = next(r for r in systematic.list_rules(conn, sid) if r["config"]["managed"]["target"] == "AAPL")
    new_tid = world.cell("AAPL", 3, live=SIGNALS, suffix="_b")

    report = autopilot.run(conn, sid, DAY1)

    (line,) = insight.replacements(conn, sid)
    assert (line["rule_name"], line["target"], line["horizon"]) == ("Auto · AAPL h3", "AAPL", 3)
    assert (line["old_trial_id"], line["new_trial_id"], line["n_orders"]) == (old["config"]["trial_id"], new_tid, 1)
    assert line["pnl_removed"] == pytest.approx(report["replaced"][0]["pnl_removed"]) and line["replaced_at"]
    assert autopilot.run(conn, sid, DAY1)["replaced"] == [] and len(insight.replacements(conn, sid)) == 1


def test_the_journal_never_blocks_a_replacement_and_dies_with_its_strategy(conn, world):
    sid = _piloted(conn, world)
    world.cell("AAPL", 3, live=SIGNALS, suffix="_b")
    autopilot.run(conn, sid, DAY1)
    assert len(insight.replacements(conn, sid)) == 1

    conn.execute("PRAGMA foreign_keys = ON")
    store.delete_strategy(conn, sid)
    assert insight.replacements(conn, sid) == []

    conn.execute("DROP TABLE fund_replacement")          # base pas encore migrée : le journal se tait, rien ne casse
    rule = {"strategy_id": sid, "name": "x", "config": {"trial_id": 1}}
    assert insight.log_replacement(conn, rule, 2, 0, None) is False and insight.replacements(conn, sid) == []


# --------------------------------------------------------------------------- attribution

def test_attribution_splits_the_pnl_by_rule_class_and_side_and_adds_up(conn, world):
    sid = _piloted(conn, world)
    service.place_order(conn, {"strategy_id": sid, "action": "open", "instrument_kind": "equity", "symbol": "TTE.PA", "side": "long",
                               "amount": 3000, "date": "2026-01-12"}, DAY1)
    snap = _snapshot(conn, sid, dt.date(2026, 1, 20))

    split = insight.attribution(conn, sid, snap)

    total = sum(p["pnl"] for p in snap["positions"])
    for table in split.values():
        assert sum(r["pnl"] for r in table) == pytest.approx(total) and sum(r["n"] for r in table) == 3
    assert {r["label"] for r in split["by_rule"]} == {"Auto · AAPL h3", "Auto · ^GSPC h3", insight.MANUAL}
    assert {r["key"] for r in split["by_side"]} == {"long", "short"}
    assert {r["key"] for r in split["by_class"]} >= {"equities_us", "equities_europe"}
    assert [r["pnl"] for r in split["by_rule"]] == sorted((r["pnl"] for r in split["by_rule"]), reverse=True)


# --------------------------------------------------------------------------- témoins

def test_witnesses_replay_the_same_orders_always_long_and_on_coin_flips(conn, world):
    """Les cours factices montent tous les jours : la position courte du pilote perd, la même en achat gagne, pile ou face est entre les deux."""
    sid = _piloted(conn, world)
    today = dt.date(2026, 1, 20)
    snap = _snapshot(conn, sid, today)

    seen = insight.witnesses(conn, store.get_strategy(conn, sid), snap, today)

    assert seen["n_positions"] == 2 and seen["nav"] == pytest.approx(snap["kpis"]["nav"])
    assert seen["always_long"] > seen["nav"]                 # pas de seuil absolu : frais et financement en changent la valeur d'un poste à l'autre
    assert seen["nav"] <= seen["coin_flip"] <= seen["always_long"]
    assert insight.witnesses(conn, store.get_strategy(conn, sid), snap, today) == seen           # tirages reproductibles
    assert len(store.list_orders(conn, sid)) == 2                                                # rien n'est écrit


def test_a_strategy_of_cash_equities_only_has_no_witness(conn):
    sid = _strategy(conn)
    service.place_order(conn, {"strategy_id": sid, "action": "open", "instrument_kind": "equity", "symbol": "AAPL", "side": "long",
                               "amount": 3000, "date": "2026-01-12"}, DAY1)

    assert insight.witnesses(conn, store.get_strategy(conn, sid), _snapshot(conn, sid), DAY1) is None


# --------------------------------------------------------------------------- plafonds de risque

def test_risk_settings_are_validated_and_kept(conn):
    base = autopilot.Settings.from_dict({})
    assert (base.max_class_share, base.max_drawdown) == (1.0, None)
    kept = autopilot.Settings.from_dict({"max_class_share": 0.4, "max_drawdown": 0.15})
    assert autopilot.Settings.from_dict(kept.to_dict()) == kept
    for bad in ({"max_class_share": 0}, {"max_class_share": 1.5}, {"max_drawdown": 0}, {"max_drawdown": 1}, {"max_drawdown": "x"}):
        with pytest.raises(store.FundError):
            autopilot.Settings.from_dict(bad)


def test_the_class_cap_trims_an_overweight_class_without_feeding_the_others(conn, world):
    world.cell("AAPL", 3, live=SIGNALS)
    world.cell("^GSPC", 3, live=SIGNALS)
    world.cell("MC.PA", 3, live=SIGNALS)
    sid = _strategy(conn)
    strategy = store.get_strategy(conn, sid)

    free = autopilot.build_plan(conn, strategy, autopilot.Settings.from_dict({}), DAY1)
    capped = autopilot.build_plan(conn, strategy, autopilot.Settings.from_dict({"max_class_share": 0.3}), DAY1)

    def weights(plan):
        return {m["target"]: m["weight"] for m in plan["selected"]}
    us_free = weights(free)["AAPL"] + weights(free)["^GSPC"]
    assert us_free > 0.3 and sum(weights(free).values()) == pytest.approx(1.0)
    assert weights(capped)["AAPL"] + weights(capped)["^GSPC"] == pytest.approx(0.3)
    assert weights(capped)["MC.PA"] == pytest.approx(min(weights(free)["MC.PA"], 0.3))          # jamais relevé par ce que les autres perdent
    assert weights(capped)["AAPL"] / weights(capped)["^GSPC"] == pytest.approx(weights(free)["AAPL"] / weights(free)["^GSPC"])


def test_beyond_the_drawdown_limit_the_autopilot_stops_opening_and_keeps_everything(conn, world):
    sid = _piloted(conn, world, {"max_drawdown": 0.000001})          # la moindre perte arrête le pilote (les cours montent, il est vendeur)
    orders_before = len(store.list_orders(conn, sid))
    day = dt.date(2026, 1, 20)
    assert insight.current_drawdown(conn, store.get_strategy(conn, sid), day) > 0

    report = autopilot.run(conn, sid, day)

    assert report["halted"]["limit"] == 0.000001 and report["halted"]["drawdown"] > 0 and report["selected"] == 0
    assert len(report["retired"]) == 2 and report["created"] == [] and report["replaced"] == []
    assert len(store.list_orders(conn, sid)) >= orders_before                                   # rien n'est effacé
    assert store.get_autopilot(conn, sid)["last_run"]["halted"]["limit"] == 0.000001
    autopilot.configure(conn, sid, {"max_drawdown": None})
    assert autopilot.run(conn, sid, day)["halted"] is None                                      # plafond levé : le pilote repart


def test_without_orders_there_is_no_drawdown(conn):
    sid = _strategy(conn)
    assert insight.current_drawdown(conn, store.get_strategy(conn, sid), DAY1) is None
