"""`patrick fund autopilot-select|autopilot-enable|autopilot-run|autopilot-off`. Aucun réseau."""
from __future__ import annotations

import re

import fund_support as fs
import pytest
from test_fund_selection import World
from typer.testing import CliRunner

from patrick.cli import app
from patrick.fund import store, systematic
from patrick.tracking import db as trackdb

UP, DOWN = 3, 0
SIGNALS = [("2026-01-14", UP, 0.6), ("2026-01-15", DOWN, 0.6)]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    conn = trackdb.connect()
    world = World(conn, monkeypatch)
    world.cell("AAPL", 3, live=SIGNALS)
    world.cell("ZZZ", 3, live=SIGNALS)
    sid = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")
    conn.close()
    return sid, CliRunner()


def run(runner, *args):
    result = runner.invoke(app, ["fund", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_select_without_a_strategy_lists_the_models_and_the_exclusions(setup):
    _, runner = setup

    out = run(runner, "autopilot-select", "--today", "2026-01-16")

    assert "2 modèle(s) retenu(s) sur 2 cellules" in out
    assert "AAPL h3" in out and "ZZZ h3" in out and "DM p=0,010" in out


def test_select_with_a_strategy_sizes_the_models_and_reports_what_it_cannot_trade(setup):
    sid, runner = setup

    out = run(runner, "autopilot-select", "--strategy", sid, "--gross", "0.5", "--today", "2026-01-16")

    assert "1 modèle(s) retenu(s) sur 2 cellules" in out and "AAPL h3" in out and "CFD AAPL" in out
    assert "poids 100,0 %" in out
    assert "Écartés (1)" in out and "no_quotes" in out and "ZZZ h3" in out


def test_enable_run_and_off_through_the_cli(setup):
    sid, runner = setup

    assert "activé" in run(runner, "autopilot-enable", "--strategy", sid, "--tier", "large", "--gross", "0.8")
    first = run(runner, "autopilot-run", "--strategy", sid, "--today", "2026-01-15")
    assert "1 règle(s) créée(s)" in first and "0 ordre(s) placé(s)" in first and "2 en attente" in first
    second = run(runner, "autopilot-run", "--strategy", sid, "--today", "2026-01-16")
    assert "1 ordre(s) placé(s)" in second

    conn = trackdb.connect()
    assert len(store.list_orders(conn, sid)) == 1
    off = run(runner, "autopilot-off", "--strategy", sid)
    assert "1 règle(s) supprimée(s)" in off
    assert systematic.list_rules(conn, sid) == []
    conn.close()


def test_run_all_goes_through_every_enabled_strategy(setup):
    sid, runner = setup
    run(runner, "autopilot-enable", "--strategy", sid)

    out = run(runner, "autopilot-run", "--all", "--today", "2026-01-15")

    assert sid in out and "1 règle(s) créée(s)" in out


def test_run_on_a_strategy_without_autopilot_is_refused(setup):
    sid, runner = setup

    result = runner.invoke(app, ["fund", "autopilot-run", "--strategy", sid, "--today", "2026-01-15"])

    assert result.exit_code == 1 and "Refusé" in result.output and "pilote" in result.output


def test_run_needs_a_strategy_or_all(setup):
    _, runner = setup

    result = runner.invoke(app, ["fund", "autopilot-run"])

    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)                  # Typer colore les noms d'options selon le terminal
    assert result.exit_code == 2 and "strategy" in plain and "--all" in plain


def test_a_bad_setting_is_refused(setup):
    sid, runner = setup

    result = runner.invoke(app, ["fund", "autopilot-enable", "--strategy", sid, "--gross", "9"])

    assert result.exit_code == 1 and "Refusé" in result.output and "gross" in result.output


def test_rule_list_names_the_mode_of_the_autopilot_rules(setup):
    sid, runner = setup
    run(runner, "autopilot-enable", "--strategy", sid)
    run(runner, "autopilot-run", "--strategy", sid, "--today", "2026-01-15")

    out = run(runner, "rule-list", "--strategy", sid)

    assert "direction" in out and "horizon 3" in out


def test_classes_preview_writes_nothing_then_create_makes_one_strategy_per_class(setup):
    sid, runner = setup

    preview = run(runner, "autopilot-classes", "--class", "Future", "--class", "Devises", "--today", "2026-01-16")
    assert "Aperçu" in preview and "Systematic Future" in preview and "Systematic Devises" in preview and "à créer" in preview

    created = run(runner, "autopilot-classes", "--create", "--class", "Future", "--class", "Devises", "--today", "2026-01-16")
    assert "créée" in created
    again = run(runner, "autopilot-classes", "--create", "--class", "Future", "--today", "2026-01-16")
    assert "reprise" in again and sid not in again

    conn = trackdb.connect()
    names = [s["name"] for s in store.list_strategies(conn)]
    conn.close()
    assert sorted(names) == ["Pilote", "Systematic Devises", "Systematic Future"]


def test_tiers_preview_writes_nothing_then_create_makes_the_two_evidence_strategies(setup):
    sid, runner = setup

    preview = run(runner, "autopilot-tiers", "--today", "2026-01-16")
    assert "Aperçu" in preview and "Systematic Diebold-Mariano" in preview and "Systematic Benjamini-Hochberg" in preview
    assert preview.count("à créer") == 2

    created = run(runner, "autopilot-tiers", "--create", "--today", "2026-01-16")
    assert created.count("créée") == 2
    again = run(runner, "autopilot-tiers", "--create", "--tier", "dm", "--today", "2026-01-16")
    assert "reprise" in again and sid not in again

    conn = trackdb.connect()
    names = [s["name"] for s in store.list_strategies(conn)]
    capitals = {s["name"]: s["initial_capital"] for s in store.list_strategies(conn)}
    conn.close()
    assert sorted(names) == ["Pilote", "Systematic Benjamini-Hochberg", "Systematic Diebold-Mariano"]
    assert capitals["Systematic Diebold-Mariano"] == 10_000_000


def test_tiers_refuses_a_tier_that_has_no_strategy_of_its_own(setup):
    _, runner = setup

    result = runner.invoke(app, ["fund", "autopilot-tiers", "--tier", "large"])

    assert result.exit_code == 1 and "niveau" in result.output


def test_enable_on_a_class_strategy_changes_the_tier_but_keeps_its_scope(setup):
    _, runner = setup
    run(runner, "autopilot-classes", "--create", "--class", "Future", "--today", "2026-01-16")
    conn = trackdb.connect()
    future = next(s["strategy_id"] for s in store.list_strategies(conn) if s["name"] == "Systematic Future")
    conn.close()

    run(runner, "autopilot-enable", "--strategy", future, "--tier", "dm", "--max-models", "0")

    conn = trackdb.connect()
    settings = store.get_autopilot(conn, future)["settings"]
    conn.close()
    assert settings["tier"] == "dm" and settings["horizons"] == [1] and settings["groups"]       # le périmètre de la classe reste


def test_classes_refuses_an_unknown_class(setup):
    _, runner = setup

    result = runner.invoke(app, ["fund", "autopilot-classes", "--class", "Nulle part"])

    assert result.exit_code == 1 and "classe" in result.output


def test_rule_roll_reports_nothing_when_every_rule_follows_its_champion(setup):
    _, runner = setup

    assert "Aucune règle à remplacer" in run(runner, "rule-roll", "--today", "2026-01-16")


def test_a_zero_max_models_means_no_cap_on_the_command_line(setup):
    sid, runner = setup

    out = run(runner, "autopilot-enable", "--strategy", sid, "--max-models", "0")

    assert "sans plafond" in out
    conn = trackdb.connect()
    assert store.get_autopilot(conn, sid)["settings"]["max_models"] is None
    conn.close()
