"""Une stratégie en pilote automatique par classe d'actifs (horizon 1 par défaut). Aucun réseau."""
from __future__ import annotations

import datetime as dt

import pytest
from test_fund_selection import World

from patrick.config import universe_extension as UX
from patrick.fund import asset_classes, autopilot, store

TODAY = dt.date(2026, 1, 16)


def test_every_tradable_group_belongs_to_exactly_one_class():
    """Un nouveau groupe de l'univers sans classe ne serait tradé par aucune stratégie : le test le dit."""
    groups = {g for g in UX.all_target_groups() if g != asset_classes.UNTRADABLE_GROUP}
    listed = [g for names in asset_classes.CLASSES.values() for g in names]

    assert sorted(listed) == sorted(groups)
    assert asset_classes.UNTRADABLE_GROUP in UX.all_target_groups()


def test_setup_creates_one_strategy_per_class_with_the_autopilot_scope(conn):
    out = asset_classes.setup(conn, today=TODAY, capital=50_000, tier="large")

    names = {r["class"]: r for r in out}
    assert set(names) == set(asset_classes.CLASSES) and all(r["created"] for r in out)
    future = store.get_strategy(conn, names["Future"]["strategy_id"])
    assert future["name"] == "Systematic Future" and future["wrapper"] == "CTO" and future["initial_capital"] == 50_000
    stored = store.get_autopilot(conn, future["strategy_id"])
    assert stored["enabled"] is True
    settings = stored["settings"]
    assert settings["horizons"] == [1] and settings["tier"] == "large"
    assert settings["groups"] == list(asset_classes.CLASSES["Future"])


def test_setup_reuses_an_existing_strategy_of_the_same_name_and_never_duplicates(conn):
    mine = store.create_strategy(conn, "Systematic Future", "CTO", 100_000, "2026-01-05")

    first = asset_classes.setup(conn, today=TODAY, only=["Future", "Devises"])
    second = asset_classes.setup(conn, today=TODAY, only=["Future", "Devises"])

    assert {r["class"]: r["strategy_id"] for r in first}["Future"] == mine
    assert [r["created"] for r in first] == [False, True] and [r["created"] for r in second] == [False, False]
    assert len(store.list_strategies(conn)) == 2


def test_setup_dry_run_writes_nothing_and_counts_the_candidates(conn, monkeypatch):
    world = World(conn, monkeypatch)
    world.cell("GC=F", 1, live=[("2026-01-15", 3, 0.6)])
    world.cell("GC=F", 5, live=[("2026-01-15", 3, 0.6)])
    world.cell("CL=F", 1, live=[("2026-01-15", 3, 0.6)])

    out = asset_classes.setup(conn, today=TODAY, tier="large", dry_run=True, only=["Future"])

    assert out[0]["candidates"] == 2 and out[0]["strategy_id"] is None
    assert store.list_strategies(conn) == []


def test_setup_refuses_an_unknown_class(conn):
    with pytest.raises(store.FundError, match="classe"):
        asset_classes.setup(conn, today=TODAY, only=["Nulle part"])


def test_the_scope_reaches_the_selection(conn, monkeypatch):
    world = World(conn, monkeypatch)
    world.cell("AAPL", 1, live=[("2026-01-15", 3, 0.6)])
    world.cell("GC=F", 1, live=[("2026-01-15", 3, 0.6)])
    out = asset_classes.setup(conn, today=TODAY, tier="large", only=["Future"])
    sid = out[0]["strategy_id"]

    plan = autopilot.preview(conn, sid, TODAY)

    assert [m["target"] for m in plan["selected"] + [{"target": e["target"]} for e in plan["excluded"]]] == ["GC=F"]


def test_setup_has_no_cap_on_the_number_of_models_by_default(conn):
    out = asset_classes.setup(conn, today=TODAY, only=["Devises"])

    assert store.get_autopilot(conn, out[0]["strategy_id"])["settings"]["max_models"] is None
