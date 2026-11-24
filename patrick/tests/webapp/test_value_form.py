"""Page « Lancer » : objectif « Direction | Valeur exacte » (liste déroulante, comme l'alpha) et son critère, sans page en plus."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_webapp_forms import _minimal_form

from patrick.config.schema import RunConfig
from patrick.webapp import forms
from patrick.webapp.app import app


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))


def _build(symbol="^GSPC", **form):
    return forms.build_config_dict(_minimal_form(**form), target_symbol=symbol, name=f"{symbol}_1")


def test_a_direction_submission_carries_no_task_key():
    cfg, errors = _build("^VIX")
    assert errors == [] and "task" not in cfg["objective"] and "criterion" not in cfg["selection"]


def test_value_submission_sets_task_criterion_and_no_resampling():
    cfg, errors = _build("^GSPC", task="value", value_criterion="R2_oos")
    assert errors == []
    assert cfg["objective"]["task"] == "value" and cfg["selection"]["criterion"] == "R2_oos" and cfg["sampler"]["candidates"] == ["none"]
    resolved = RunConfig.model_validate(cfg)
    assert resolved.objective.run_label() == "^GSPC__val"


def test_value_refuses_stacking_and_cpcv():
    _cfg, errors = _build("^GSPC", task="value", stacking="on")
    assert any("empilement" in e for e in errors)
    _cfg, errors = _build("^GSPC", task="value", scheme="cpcv")
    assert any("walk-forward" in e for e in errors)


def test_launch_pages_offer_the_objective_dropdown():
    client = TestClient(app)
    for page in ("/ml", "/dl"):
        html = client.get(page).text
        assert 'name="task"' in html and 'value="value"' in html and 'id="value-criterion-field"' in html
