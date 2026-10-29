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


def test_a_reused_strategy_without_orders_takes_the_requested_capital_but_one_with_orders_keeps_its_own(conn):
    empty = store.create_strategy(conn, "Systematic Future", "CTO", 100_000, "2026-01-05")
    busy = store.create_strategy(conn, "Systematic Devises", "CTO", 100_000, "2026-01-05")
    store.insert_order(conn, {"strategy_id": busy, "position_id": "pos_a", "ts": "2026-01-07", "action": "open",
                              "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4.0, "price": 700.0,
                              "price_source": "market", "currency": "EUR", "fx_rate": 1.0, "fees": 1.0,
                              "fees_source": "estimated", "fee_seed": 7, "spec": {}, "note": None})

    out = {r["class"]: r for r in asset_classes.setup(conn, today=TODAY, capital=10_000_000, only=["Future", "Devises"])}

    assert store.get_strategy(conn, empty)["initial_capital"] == 10_000_000 and out["Future"]["capital_changed"] is True
    assert store.get_strategy(conn, busy)["initial_capital"] == 100_000 and out["Devises"]["capital_changed"] is False


def test_the_initial_capital_of_a_strategy_with_orders_is_frozen(conn):
    sid = store.create_strategy(conn, "A", "CTO", 100_000, "2026-01-05")
    store.set_initial_capital(conn, sid, "2 500 000,5")
    assert store.get_strategy(conn, sid)["initial_capital"] == 2_500_000.5
    for bad in (0, -5, "abc", float("inf")):
        with pytest.raises(store.FundError):
            store.set_initial_capital(conn, sid, bad)
    pea = store.create_strategy(conn, "P", "PEA", 50_000, "2026-01-05")
    with pytest.raises(store.FundError, match="plafond"):
        store.set_initial_capital(conn, pea, 200_000)
    store.insert_order(conn, {"strategy_id": sid, "position_id": "pos_a", "ts": "2026-01-07", "action": "open",
                              "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4.0, "price": 700.0,
                              "price_source": "market", "currency": "EUR", "fx_rate": 1.0, "fees": 1.0,
                              "fees_source": "estimated", "fee_seed": 7, "spec": {}, "note": None})
    with pytest.raises(store.FundError, match="figé"):
        store.set_initial_capital(conn, sid, 1_000_000)


def test_setup_counts_each_chosen_model_once_in_the_trial_registry_but_a_dry_run_counts_nothing(conn, monkeypatch):
    world = World(conn, monkeypatch)
    world.cell("GC=F", 1, live=[("2026-01-15", 3, 0.6)])
    world.cell("SI=F", 1, live=[("2026-01-15", 3, 0.6)])
    count = lambda: conn.execute("SELECT COALESCE(SUM(n_trials), 0) FROM trial_registry WHERE detail LIKE 'fund_selection:%'").fetchone()[0]
    asset_classes.setup(conn, today=TODAY, capital=50_000, tier="large", dry_run=True)
    assert count() == 0
    out = asset_classes.setup(conn, today=TODAY, capital=50_000, tier="large")
    assert count() == sum(r["candidates"] for r in out) == 2
    rows = conn.execute("SELECT detail FROM trial_registry WHERE detail LIKE 'fund_selection:%'").fetchall()
    assert {d.split(":", 1)[1] for (d,) in rows} <= {r["name"] for r in out}


# --- une stratégie globale par preuve statistique (Diebold-Mariano seul, Benjamini-Hochberg seul) ----------------------


def test_setup_tiers_creates_one_global_strategy_per_evidence_tier_over_every_class(conn):
    out = asset_classes.setup_tiers(conn, today=TODAY, capital=50_000)

    assert [(r["tier"], r["name"], r["created"]) for r in out] == [
        ("dm", "Systematic Diebold-Mariano", True), ("bh", "Systematic Benjamini-Hochberg", True)]
    for row in out:
        strategy = store.get_strategy(conn, row["strategy_id"])
        assert strategy["name"] == row["name"] and strategy["wrapper"] == "CTO" and strategy["initial_capital"] == 50_000
        stored = store.get_autopilot(conn, row["strategy_id"])
        assert stored["enabled"] is True
        assert stored["settings"]["tier"] == row["tier"] and stored["settings"]["horizons"] == [1]
        assert stored["settings"]["groups"] is None and stored["settings"]["max_models"] is None     # toutes les classes, sans plafond


def test_each_tier_strategy_keeps_only_the_models_that_pass_its_own_test(conn, monkeypatch):
    world = World(conn, monkeypatch)
    world.cell("AAPL", 1, live=[("2026-01-15", 3, 0.6)], dm_p=0.01, bh=(False, 0.50))        # DM seul
    world.cell("GC=F", 1, live=[("2026-01-15", 3, 0.6)], dm_p=0.60, bh=(True, 0.01))         # BH seul
    world.cell("SI=F", 1, live=[("2026-01-15", 3, 0.6)], dm_p=0.02, bh=(True, 0.01))     # les deux

    out = {r["tier"]: r for r in asset_classes.setup_tiers(conn, today=TODAY)}
    selected = {tier: sorted(m["target"] for m in autopilot.preview(conn, row["strategy_id"], TODAY)["selected"])
                for tier, row in out.items()}

    assert out["dm"]["candidates"] == 2 and out["bh"]["candidates"] == 2
    assert selected["dm"] == ["AAPL", "SI=F"] and selected["bh"] == ["GC=F", "SI=F"]


def test_setup_tiers_never_duplicates_counts_the_trials_and_a_dry_run_writes_nothing(conn, monkeypatch):
    world = World(conn, monkeypatch)
    world.cell("GC=F", 1, live=[("2026-01-15", 3, 0.6)])
    count = lambda: conn.execute("SELECT COALESCE(SUM(n_trials), 0) FROM trial_registry WHERE detail LIKE 'fund_selection:%'").fetchone()[0]

    dry = asset_classes.setup_tiers(conn, today=TODAY, dry_run=True)
    assert [r["candidates"] for r in dry] == [1, 1] and store.list_strategies(conn) == [] and count() == 0
    first = asset_classes.setup_tiers(conn, today=TODAY)
    second = asset_classes.setup_tiers(conn, today=TODAY)

    assert [r["created"] for r in first] == [True, True] and [r["created"] for r in second] == [False, False]
    assert [r["strategy_id"] for r in first] == [r["strategy_id"] for r in second] and len(store.list_strategies(conn)) == 2
    assert {d.split(":", 1)[1] for (d,) in conn.execute(
        "SELECT detail FROM trial_registry WHERE detail LIKE 'fund_selection:%'")} == {r["name"] for r in first}


def test_setup_tiers_refuses_an_unknown_tier_and_writes_nothing(conn):
    with pytest.raises(store.FundError, match="niveau"):
        asset_classes.setup_tiers(conn, today=TODAY, tiers=("dm", "large"))
    assert store.list_strategies(conn) == []
