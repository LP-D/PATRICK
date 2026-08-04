"""`build_config_dict` prend désormais `target_symbol`/`name` en paramètres
explicites (plus jamais lus dans `form`) -- un lancement peut soumettre
plusieurs cibles à la fois, une par appel (cf. patrick/webapp/app.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.webapp import forms
from patrick.webapp.app import app


def _minimal_form(**overrides) -> FormData:
    base = {
        "horizons": "1,2",
        "regimes": "GLOBAL",
        "families": ["technical"],
        "n_features_grid": "5,8",
        "sampler_candidates": ["SMOTE"],
        "algos": ["RandomForest"],
    }
    base.update(overrides)
    items = []
    for k, v in base.items():
        if isinstance(v, list):
            items.extend((k, x) for x in v)
        else:
            items.append((k, v))
    return FormData(items)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))


def test_next_run_names_endpoint_returns_one_name_per_target():
    client = TestClient(app)
    resp = client.get("/api/next-run-names", params=[("target", "^VIX"), ("target", "^AORD")])
    assert resp.status_code == 200
    assert resp.json() == {"^VIX": "VIX_1", "^AORD": "AORD_1"}


def test_next_run_names_endpoint_dedupes_repeated_targets():
    client = TestClient(app)
    resp = client.get("/api/next-run-names", params=[("target", "^VIX"), ("target", "^VIX")])
    assert resp.json() == {"^VIX": "VIX_1"}


def test_build_config_dict_uses_explicit_target_and_name():
    form = _minimal_form()
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_1")
    assert errors == []
    assert config_dict["objective"]["target_symbol"] == "^VIX"
    assert config_dict["name"] == "VIX_1"
    assert config_dict["output"]["dir"] == "runs/VIX_1"


def test_build_config_dict_rejects_unknown_target():
    form = _minimal_form()
    _config_dict, errors = forms.build_config_dict(form, target_symbol="NOT_A_TARGET", name="X_1")
    assert any("invalide" in e.lower() for e in errors)


def test_build_config_dict_respects_explicit_output_dir():
    form = _minimal_form(output_dir="/tmp/custom_runs")
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_2")
    assert errors == []
    assert config_dict["output"]["dir"] == "/tmp/custom_runs"
