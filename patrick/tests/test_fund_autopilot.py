"""Fonds, pilote automatique : réglages, aperçu, cycle (règles gérées + ordres), désactivation (spec 2026-10-16, §5-6)."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pandas as pd
import pytest
from test_fund_selection import World

from patrick.fund import autopilot, store, systematic

TODAY = dt.date(2026, 1, 16)
UP, DOWN = 3, 0

# signaux live d'AAPL : lundi et mardi haussiers (renouvellement), jeudi baissier (retournement)
AAPL_SIGNALS = [("2026-01-12", UP, 0.6), ("2026-01-13", UP, 0.6), ("2026-01-15", DOWN, 0.6)]


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _strategy(conn, wrapper="CTO", capital=100_000, opened="2026-01-05") -> str:
    return store.create_strategy(conn, "Pilote", wrapper, capital, opened)


def _vol(symbol: str, today=TODAY) -> float:
    close = pd.Series({d: fs.price_on(symbol, d.strftime("%Y-%m-%d")) for d in fs.IDX if d <= pd.Timestamp(today)})
    return float(close.pct_change().dropna().tail(60).std())


# --------------------------------------------------------------------------- réglages

def test_settings_defaults_and_round_trip():
    settings = autopilot.Settings.from_dict({})

    assert (settings.selection.tier, settings.gross, settings.allow_short, settings.min_confidence) == ("strict", 1.0, True, 0.0)
    assert autopilot.Settings.from_dict(settings.to_dict()) == settings


@pytest.mark.parametrize("patch, message", [
    ({"gross": 0}, "gross"), ({"gross": 5}, "gross"), ({"gross": "x"}, "gross"),
    ({"allow_short": "oui"}, "allow_short"), ({"min_confidence": 1}, "min_confidence"), ({"tier": "folle"}, "tier"),
    ({"max_models": 0}, "max_models")])
def test_settings_reject_bad_values(patch, message):
    with pytest.raises(store.FundError, match=message):
        autopilot.Settings.from_dict(patch)


def test_configure_enables_the_autopilot_and_stores_the_settings(conn):
    sid = _strategy(conn)

    autopilot.configure(conn, sid, {"tier": "large", "gross": 0.5})

    stored = store.get_autopilot(conn, sid)
    assert stored["enabled"] is True and stored["settings"]["tier"] == "large" and stored["settings"]["gross"] == 0.5


def test_configure_refuses_an_unknown_strategy(conn):
    with pytest.raises(store.FundError, match="introuvable"):
        autopilot.configure(conn, "str_inconnue", {})


# --------------------------------------------------------------------------- aperçu

def test_preview_sizes_the_models_by_inverse_volatility_to_the_gross_exposure(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    world.cell("^GSPC", 3, live=[("2026-01-15", UP, 0.6)])
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {"gross": 0.8})

    out = autopilot.preview(conn, sid, TODAY)

    by_target = {m["target"]: m for m in out["selected"]}
    assert sorted(by_target) == ["AAPL", "^GSPC"] and out["excluded"] == []
    assert sum(m["notional"] for m in out["selected"]) == pytest.approx(80_000, abs=0.05)
    ratio = by_target["AAPL"]["weight"] / by_target["^GSPC"]["weight"]
    assert ratio == pytest.approx(_vol("^GSPC") / _vol("AAPL"), rel=1e-6)
    for model in by_target.values():
        assert model["instrument"]["kind"] == "cfd"                         # vente à découvert permise : tout en CFD
        assert model["sizing"]["quantity"] > 0
    unit = fs.price_on("AAPL", "2026-01-16") * fs.fx_on("2026-01-16")
    assert by_target["AAPL"]["sizing"]["quantity"] == pytest.approx(by_target["AAPL"]["notional"] / unit, abs=1e-3)


def test_a_target_with_several_horizons_shares_its_budget_equally(conn, world):
    world.cell("AAPL", 1, live=AAPL_SIGNALS)
    world.cell("AAPL", 5, live=AAPL_SIGNALS)
    world.cell("^GSPC", 5, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})

    out = autopilot.preview(conn, sid, TODAY)

    notionals = {(m["target"], m["horizon"]): m["notional"] for m in out["selected"]}
    assert notionals[("AAPL", 1)] == pytest.approx(notionals[("AAPL", 5)])
    assert sum(notionals.values()) == pytest.approx(100_000, abs=0.05)


def test_a_pea_gets_cash_instruments_long_only_and_excludes_what_needs_a_cfd(conn, world):
    world.cell("MC.PA", 3, live=AAPL_SIGNALS)
    world.cell("^GSPC", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn, wrapper="PEA")
    autopilot.configure(conn, sid, {})

    out = autopilot.preview(conn, sid, TODAY)

    (model,) = out["selected"]
    assert model["target"] == "MC.PA" and model["instrument"]["kind"] == "equity" and model["allow_short"] is False
    assert model["sizing"] == {"amount": pytest.approx(model["notional"], abs=0.01)}
    assert [(e["target"], e["code"]) for e in out["excluded"]] == [("^GSPC", "pea")]


def test_cash_instruments_are_used_for_equities_when_short_selling_is_off(conn, world):
    world.cell("MC.PA", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {"allow_short": False})

    (model,) = autopilot.preview(conn, sid, TODAY)["selected"]

    assert model["instrument"]["kind"] == "equity" and model["allow_short"] is False


def test_a_target_without_quotes_is_excluded_with_its_reason(conn, world):
    world.cell("ZZZ", 3, live=AAPL_SIGNALS)
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})

    out = autopilot.preview(conn, sid, TODAY)

    assert [m["target"] for m in out["selected"]] == ["AAPL"]
    assert [(e["target"], e["code"]) for e in out["excluded"]] == [("ZZZ", "no_quotes")]


def test_preview_writes_nothing(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})

    autopilot.preview(conn, sid, TODAY)

    assert systematic.list_rules(conn, sid) == [] and store.list_orders(conn, sid) == []


# --------------------------------------------------------------------------- cycle

DAY0, DAY1 = dt.date(2026, 1, 15), dt.date(2026, 1, 16)      # jeudi, vendredi : le signal du 15 s'exécute le 16


def _orders(conn, sid):
    return [(o["ts"], o["action"], o["side"]) for o in store.list_orders(conn, sid)]


def test_run_creates_the_managed_rules_and_trades_only_from_the_first_cycle_day(conn, world):
    """Une règle neuve ne rejoue pas l'historique : elle démarre le jour du premier cycle (rejouer des signaux passés avec
    une sélection faite aujourd'hui serait du recul). Le signal du jour s'exécute à la séance suivante."""
    world.cell("AAPL", 3, live=[("2026-01-02", UP, 0.6), *AAPL_SIGNALS])
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})

    first = autopilot.run(conn, sid, DAY0)

    (rule,) = systematic.list_rules(conn, sid)
    cfg = rule["config"]
    assert rule["name"] == "Auto · AAPL h3"
    assert cfg["managed"] == {"by": "autopilot", "target": "AAPL", "horizon": 3}
    assert cfg["segment"] == "live" and cfg["signal"]["mode"] == "direction" and cfg["hold"] == {"mode": "horizon", "sessions": 3}
    assert cfg["since"] == "2026-01-15" and cfg["allow_short"] is True
    assert len(first["created"]) == 1 and first["placed"] == 0 and first["pending"] == 2     # ouverture du 16 et échéance du 21
    assert first["rules"] == 1 and first["selected"] == 1 and store.list_orders(conn, sid) == []

    second = autopilot.run(conn, sid, DAY1)

    assert _orders(conn, sid) == [("2026-01-16", "open", "short")] and second["placed"] == 1 and second["refused"] == []


def test_running_every_day_opens_renews_flips_and_closes(conn, world):
    tid = world.cell("AAPL", 3, live=None)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    signals = {"2026-01-12": UP, "2026-01-13": UP, "2026-01-15": DOWN, "2026-01-21": DOWN}
    for day in ("2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-21"):
        if day in signals:
            world.signal(tid, day, signals[day])
        autopilot.run(conn, sid, dt.date.fromisoformat(day))

    # le 13 renouvelle la position ouverte le 13 ; le 15 la retourne ; plus de signal avant le 21 : échéance, puis
    # le signal du 21 (exécuté le 22) rouvre une position demain.
    assert _orders(conn, sid) == [("2026-01-13", "open", "long"), ("2026-01-16", "close", "long"),
                                  ("2026-01-16", "open", "short"), ("2026-01-21", "close", "short")]
    assert len(systematic.list_rules(conn, sid)) == 1                          # une seule règle, jamais recréée


def test_a_second_run_changes_nothing(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    autopilot.run(conn, sid, DAY1)
    before = (len(store.list_orders(conn, sid)), systematic.list_rules(conn, sid))

    report = autopilot.run(conn, sid, DAY1)

    assert report["created"] == report["updated"] == report["retired"] == [] and report["placed"] == 0
    assert (len(store.list_orders(conn, sid)), systematic.list_rules(conn, sid)) == before


def test_a_model_that_drops_out_is_retired_and_its_position_dies_at_the_horizon(conn, world):
    tid = world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    autopilot.run(conn, sid, DAY1)                                           # position courte ouverte le 16, échéance le 21
    conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, 'holdout', 'F1_dir', 0.99)", (tid,))
    world.signal(tid, "2026-01-22", UP)
    conn.commit()

    report = autopilot.run(conn, sid, dt.date(2026, 1, 22))

    (rule,) = systematic.list_rules(conn, sid)
    assert report["retired"] == [rule["rule_id"]] and rule["config"]["retired_on"] == "2026-01-21"
    assert _orders(conn, sid) == [("2026-01-16", "open", "short"), ("2026-01-21", "close", "short")]   # l'échéance est honorée
    opens_after = [p for p in systematic.plan(conn, rule) if p["action"] == "open" and p["requested"] > "2026-01-21"]
    assert opens_after == [] and report["selected"] == 0                      # le signal du 22 n'ouvre plus rien


def test_a_champion_change_retires_the_old_rule_and_starts_a_new_one_without_overlap(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    (old,) = systematic.list_rules(conn, sid)

    world.cell("AAPL", 3, live=AAPL_SIGNALS, suffix="_b")                    # un nouveau champion, d'un autre essai
    report = autopilot.run(conn, sid, DAY0)

    rules = {r["rule_id"]: r for r in systematic.list_rules(conn, sid)}
    assert len(rules) == 2 and report["retired"] == [old["rule_id"]] and len(report["created"]) == 1
    assert rules[old["rule_id"]]["config"]["retired_on"] == "2026-01-14"
    new = rules[report["created"][0]]
    assert new["config"]["trial_id"] != old["config"]["trial_id"] and "retired_on" not in new["config"]
    assert new["config"]["since"] == "2026-01-15"                              # l'ancienne règle s'arrête la veille


def test_changing_a_behaviour_setting_replaces_the_rule_instead_of_rewriting_its_history(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    (old,) = systematic.list_rules(conn, sid)

    autopilot.configure(conn, sid, {"allow_short": False})                   # change le sens des signaux tradés
    report = autopilot.run(conn, sid, DAY0)

    assert report["retired"] == [old["rule_id"]] and len(report["created"]) == 1
    assert {r["config"]["allow_short"] for r in systematic.list_rules(conn, sid) if "retired_on" not in r["config"]} == {False}


def test_a_model_that_comes_back_gets_a_fresh_rule_not_a_replay_of_the_gap(conn, world):
    tid = world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    conn.execute("UPDATE champion SET trial_id = trial_id + 1000 WHERE target = 'AAPL'")      # le champion disparaît un temps
    conn.commit()
    autopilot.run(conn, sid, DAY0)
    conn.execute("UPDATE champion SET trial_id = ? WHERE target = 'AAPL'", (tid,))
    conn.commit()

    report = autopilot.run(conn, sid, dt.date(2026, 1, 19))

    rules = systematic.list_rules(conn, sid)
    assert len(rules) == 2 and len(report["created"]) == 1
    fresh = next(r for r in rules if r["rule_id"] == report["created"][0])
    assert fresh["config"]["since"] == "2026-01-19" and "retired_on" not in fresh["config"]


def test_manual_rules_are_never_touched(conn, world):
    tid = world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    manual = systematic.create_rule(conn, sid, "Ma règle", {
        "trial_id": tid, "segment": "live", "enter": 0.55, "exit": 0.5, "instrument": {"kind": "equity", "symbol": "AAPL"},
        "sizing": {"amount": 1000}})
    autopilot.configure(conn, sid, {})
    conn.execute("DELETE FROM champion")                                      # plus aucun modèle retenu
    conn.commit()

    autopilot.run(conn, sid, DAY1)

    (rule,) = systematic.list_rules(conn, sid)
    assert rule["rule_id"] == manual and "retired_on" not in rule["config"] and "managed" not in rule["config"]


def test_disable_removes_the_managed_rules_and_keeps_the_orders(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    autopilot.run(conn, sid, DAY1)
    n_orders = len(store.list_orders(conn, sid))
    assert n_orders == 1

    out = autopilot.disable(conn, sid)

    assert out == {"removed_rules": 1} and systematic.list_rules(conn, sid) == []
    assert len(store.list_orders(conn, sid)) == n_orders
    assert store.get_autopilot(conn, sid)["enabled"] is False


def test_run_refuses_a_disabled_or_unconfigured_autopilot(conn, world):
    sid = _strategy(conn)
    with pytest.raises(store.FundError, match="pilote"):
        autopilot.run(conn, sid, DAY0)
    autopilot.configure(conn, sid, {})
    autopilot.disable(conn, sid)
    with pytest.raises(store.FundError, match="pilote"):
        autopilot.run(conn, sid, DAY0)


def test_the_last_run_summary_is_stored_with_the_settings(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = _strategy(conn)
    autopilot.configure(conn, sid, {})

    autopilot.run(conn, sid, DAY0)

    stored = store.get_autopilot(conn, sid)
    assert stored["last_run"]["selected"] == 1 and stored["last_run"]["pending"] == 2 and stored["last_run"]["day"] == "2026-01-15"
    assert stored["enabled"] is True and "settings" in stored


def test_run_all_runs_only_enabled_active_strategies_and_isolates_errors(conn, world, monkeypatch):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    good, broken, off, archived = (_strategy(conn) for _ in range(4))
    for sid in (good, broken, archived):
        autopilot.configure(conn, sid, {})
    autopilot.configure(conn, off, {})
    autopilot.disable(conn, off)
    store.update_strategy(conn, archived, archived=1)
    real = autopilot.run

    def flaky(c, strategy_id, today=None):
        if strategy_id == broken:
            raise RuntimeError("base verrouillée")
        return real(c, strategy_id, today)
    monkeypatch.setattr(autopilot, "run", flaky)

    out = {r["strategy_id"]: r for r in autopilot.run_all(conn, DAY0)}

    assert set(out) == {good, broken}
    assert len(out[good]["created"]) == 1 and "base verrouillée" in out[broken]["error"]


def test_sizing_changes_below_ten_percent_are_ignored():
    assert autopilot._stable_sizing({"quantity": 1.0}, {"quantity": 1.09}) == {"quantity": 1.0}
    assert autopilot._stable_sizing({"quantity": 1.0}, {"quantity": 1.2}) == {"quantity": 1.2}
    assert autopilot._stable_sizing({"amount": 5000.0}, {"amount": 5200.0}) == {"amount": 5000.0}
    assert autopilot._stable_sizing({"amount": 5000.0}, {"quantity": 2}) == {"quantity": 2}
    assert autopilot._stable_sizing(None, {"amount": 10.0}) == {"amount": 10.0}
