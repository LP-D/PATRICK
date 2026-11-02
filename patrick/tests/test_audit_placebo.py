"""Panel de runs placebo (`patrick/audit_placebo.py`) : configuration légère, rapport, commandes."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from patrick import audit_placebo
from patrick.cli import app as cli_app
from patrick.data.session_calendar import classify_asset_class
from patrick.tracking import db


def test_the_asia_panel_is_asian_and_the_controls_are_not():
    assert {classify_asset_class(t) for t in audit_placebo.panel_targets("asia")} == {"equities_asia_pacific"}
    assert {classify_asset_class(t) for t in audit_placebo.panel_targets("controls")} == {"equities_us", "equities_europe"}
    assert len(audit_placebo.panel_targets("all")) == 11
    with pytest.raises(ValueError):
        audit_placebo.panel_targets("mars")


def test_the_every_class_panel_covers_every_asset_class_without_duplicates():
    targets = audit_placebo.panel_targets("every_class")
    assert len(targets) == len(set(targets))
    assert {classify_asset_class(t) for t in targets} == {
        "equities_us", "equities_europe", "equities_asia_pacific", "equities_americas_other", "fx", "futures", "crypto", "volatility_index"}
    for group in ("fx", "futures", "us", "europe", "americas", "crypto", "volatility"):
        assert set(audit_placebo.panel_targets(group)) <= set(targets)
    assert {classify_asset_class(t) for t in audit_placebo.panel_targets("fx")} == {"fx"}
    assert {classify_asset_class(t) for t in audit_placebo.panel_targets("volatility")} == {"volatility_index"}


@pytest.mark.parametrize("target", audit_placebo.PANELS["every_class"])
def test_every_panel_target_builds_a_valid_config_that_excludes_itself(target):
    config = audit_placebo.build_config(target, "placebo_x")
    assert config.objective.target_symbol == target and target not in config.universe.yf_tickers


def test_a_panel_config_is_light_walk_forward_and_never_feeds_the_target_to_itself():
    config = audit_placebo.build_config("^N225", "placebo_N225_1")
    assert config.objective.horizons == [1, 3] and config.validation.scheme == "walkforward"
    assert config.models.algos == ["LightGBM"] and config.tuning.enabled is False
    assert "^N225" not in config.universe.yf_tickers and "^GSPC" in config.universe.yf_tickers
    assert config.objective.target_source == "yfinance"
    assert config.selection.criterion == "AUC_dir"


def _seed(conn, run_id, target, horizon, real, lag):
    db.create_run(conn, run_id, target, horizon, "snap", "{}", "c", "sha", 1)
    db.save_placebo(conn, run_id, "real", {"AUC_ovr_4cls": real, "F1_dir": 0.5})
    db.save_placebo(conn, run_id, "lag1", {"AUC_ovr_4cls": lag, "F1_dir": 0.5})


def test_report_gives_the_verdict_per_run_and_the_summary_per_class(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "snap", "h", 1, 1, "api")
    _seed(conn, "n225", "^N225", 1, 0.64, 0.51)         # s'effondre : repose sur le jour même
    _seed(conn, "hsi", "^HSI", 1, 0.62, 0.60)           # tient : signal d'un autre type
    _seed(conn, "gspc", "^GSPC", 1, 0.53, 0.52)
    conn.commit()
    rows = audit_placebo.report(conn)
    verdicts = {r["target"]: r["verdict"] for r in rows}
    assert verdicts == {"^GSPC": "stable", "^HSI": "stable", "^N225": "same_day"}
    assert [r["target"] for r in audit_placebo.report(conn, "asia")] == ["^HSI", "^N225"]
    summary = {(s["class"], s["horizon"]): s for s in audit_placebo.summarize(rows)}
    asia = summary[("equities_asia_pacific", 1)]
    assert asia["n"] == 2 and asia["share_same_day"] == 0.5 and asia["auc_real"] == pytest.approx(0.63)
    conn.close()


def test_coverage_says_which_classes_were_never_audited_at_a_short_horizon(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "snap", "h", 1, 1, "api")
    _seed(conn, "gspc1", "^GSPC", 1, 0.53, 0.52)
    _seed(conn, "gspc30", "^GSPC", 30, 0.53, 0.52)
    db.create_run(conn, "eur", "EURUSD=X", 1, "snap", "{}", "c", "sha", 1)       # un run de change sans placebo
    with conn:
        conn.execute("UPDATE run SET status = 'done'")
    cover = {c["class"]: c for c in audit_placebo.coverage(conn)}
    assert (cover["equities_us"]["runs"], cover["equities_us"]["with_placebo"], cover["equities_us"]["with_short_placebo"]) == (2, 2, 1)
    assert (cover["fx"]["runs"], cover["fx"]["with_placebo"], cover["fx"]["with_short_placebo"]) == (1, 0, 0)
    conn.close()


def test_enqueue_inserts_the_jobs_without_starting_any_worker(tmp_path, monkeypatch):
    from patrick.webapp import run_manager

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setattr(run_manager, "_spawn_worker", lambda *_a, **_k: pytest.fail("un worker a été lancé"))
    names = audit_placebo.enqueue("controls")
    assert names == ["placebo_GSPC_1", "placebo_FCHI_1", "placebo_GDAXI_1"]
    conn = db.connect(str(tmp_path / "p.db"))
    assert conn.execute("SELECT COUNT(*) FROM job WHERE status = 'queued'").fetchone()[0] == 3
    conn.close()
    assert audit_placebo.enqueue("controls") == []              # déjà en file : pas de doublon


def test_the_panel_commands_dry_run_and_report(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    runner = CliRunner()
    dry = runner.invoke(cli_app, ["audit", "placebo-panel", "--group", "controls", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "placebo_GSPC_1" in dry.output and "placebo_GDAXI_1" in dry.output and "dry-run" in dry.output
    conn = db.connect(str(tmp_path / "p.db"))
    assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0          # rien n'a été mis en file
    conn.close()
    empty = runner.invoke(cli_app, ["audit", "placebo-report"])
    assert empty.exit_code == 0 and "aucun" in empty.output.lower()
