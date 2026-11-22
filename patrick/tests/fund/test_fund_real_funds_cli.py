"""`patrick fund real-setup` : aperçu puis création du fonds PEA et du fonds CTO. Aucun réseau."""
from __future__ import annotations

import fund_support as fs
import pytest
from test_fund_selection import World
from typer.testing import CliRunner

from patrick.cli import app
from patrick.fund import store
from patrick.tracking import db as trackdb

SIGNALS = [("2026-01-14", 3, 0.6), ("2026-01-15", 3, 0.6)]


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    conn = trackdb.connect()
    world = World(conn, monkeypatch)
    for target in ("MC.PA", "AAPL"):
        trial_id = world.cell(target, 1, live=SIGNALS)
        conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, 'holdout', 'AUC_dir', 0.6)", (trial_id,))
    conn.commit()
    conn.close()
    return CliRunner()


def _run(runner, *args, code=0):
    result = runner.invoke(app, ["fund", "real-setup", "--today", "2026-01-16", *args])
    assert result.exit_code == code, result.output
    return result.output


def test_without_create_it_only_previews(runner):
    out = _run(runner)

    assert "Aperçu (rien n'est écrit)" in out and "Systematic PEA" in out and "Systematic CTO" in out and "à créer" in out
    conn = trackdb.connect()
    assert store.list_strategies(conn) == []


def test_create_makes_both_funds_then_reuses_them(runner):
    first = _run(runner, "--create")
    second = _run(runner, "--create")

    assert first.count("créé") == 2 and second.count("repris") == 2
    conn = trackdb.connect()
    funds = {s["name"]: s for s in store.list_strategies(conn)}
    assert set(funds) == {"Systematic PEA", "Systematic CTO"}
    assert all(f["category"] == "real" and f["fee_flat"] == 1.0 and f["initial_capital"] == 5_000 for f in funds.values())


def test_options_change_the_capital_the_fee_and_the_set_of_funds(runner):
    _run(runner, "--create", "--only", "PEA", "--capital", "3000", "--fee", "0.5", "--min-position", "0", "--max-models", "0")

    conn = trackdb.connect()
    (fund,) = store.list_strategies(conn)
    assert (fund["name"], fund["initial_capital"], fund["fee_flat"]) == ("Systematic PEA", 3_000, 0.5)
    settings = store.get_autopilot(conn, fund["strategy_id"])["settings"]
    assert settings["min_position"] is None and settings["max_models"] is None


def test_a_refused_request_exits_with_the_reason_and_writes_nothing(runner):
    out = _run(runner, "--create", "--capital", "400000", code=1)

    assert "Refusé" in out and "plafond" in out
    assert store.list_strategies(trackdb.connect()) == []
