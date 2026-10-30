"""Budget d'essais d'un lancement (ADR 0010) et runs sans aucune évaluation."""
from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from patrick import cli
from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import trial_budget as tb
from patrick.webapp.app import app


def _config(**tuning) -> RunConfig:
    return RunConfig.model_validate({"objective": {"target_symbol": "^GSPC", "horizons": [1, 5]}, "tuning": tuning})


def test_planned_trials_follow_the_grid_and_the_optuna_budget():
    c = _config(enabled=True, n_trials=30, top_k=2)
    algos = len(c.models.algos)
    scan = len(c.objective.regimes) * len(c.selection.n_features_grid) * len(c.sampler.candidates) * algos
    assert tb.planned_trials_per_horizon(c) == {"scan": scan, "optuna": 60, "total": scan + 60}
    assert tb.planned_trials_per_horizon(_config(enabled=False))["optuna"] == 0


def test_the_threshold_grows_with_the_number_of_trials():
    assert tb.threshold(0) == tb.threshold(1) == 0.0
    assert 0 < tb.threshold(10) < tb.threshold(1000) < tb.threshold(100000)


def test_the_budget_adds_the_planned_trials_to_the_registry(tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.register_trials(conn, "^GSPC", 1, "scan", 400)
    trackdb.register_trials(conn, "^GSPC", 5, "scan", 50)
    config = _config(enabled=False)
    budget = tb.trial_budget(conn, config)
    planned = budget["planned"]["total"]
    by_h = {h["horizon"]: h for h in budget["horizons"]}
    assert by_h[1]["existing"] == 400 and by_h[1]["after"] == 400 + planned and by_h[5]["existing"] == 50
    assert by_h[1]["threshold_after"] > by_h[1]["threshold_before"] and by_h[1]["delta_threshold"] > 0
    assert by_h[5]["delta_threshold"] > by_h[1]["delta_threshold"]                 # le même ajout pèse plus sur une cible peu essayée
    assert budget["total_existing"] == 450
    assert "h=1j" in "\n".join(tb.describe(budget))
    conn.close()


def test_the_budget_api_and_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    client = TestClient(app)
    body = client.get("/api/trial-budget", params={"target": "^GSPC", "horizons": "1,5"}).json()
    assert [h["horizon"] for h in body["horizons"]] == [1, 5] and body["horizons"][0]["existing"] == 0
    assert client.get("/api/trial-budget", params={"target": "NOPE"}).status_code == 404
    assert client.get("/api/trial-budget", params={"target": "^GSPC", "horizons": "x"}).status_code == 422
    assert client.get("/api/trial-budget", params={"target": "^GSPC", "horizons": "0"}).status_code == 422
    out = CliRunner().invoke(cli.app, ["budget", "^GSPC", "--horizon", "3"])
    assert out.exit_code == 0 and "h=3j" in out.output


def test_the_launch_form_shows_the_trial_budget_block(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    client = TestClient(app)
    page = client.get("/ml").text
    assert 'id="trial-budget"' in page and "trial_budget.js" in page
    script = client.get("/static/trial_budget.js")
    assert script.status_code == 200 and "/api/trial-budget" in script.text
