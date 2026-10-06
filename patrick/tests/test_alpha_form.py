"""Page « Lancer » : choix « Cible brute | Alpha vs benchmark », benchmark automatique ou saisi."""
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


def test_a_raw_submission_is_unchanged_and_carries_no_alpha_key():
    cfg, errors = _build("^VIX")
    assert errors == [] and "target_kind" not in cfg["objective"] and "benchmark" not in cfg["objective"]


def test_alpha_without_a_benchmark_resolves_it_automatically():
    cfg, errors = _build("^GSPC", target_kind="alpha", benchmark="")
    assert errors == [] and cfg["objective"]["target_kind"] == "alpha" and "benchmark" not in cfg["objective"]
    resolved = RunConfig.model_validate(cfg)
    assert (resolved.objective.benchmark, resolved.objective.benchmark_source) == ("URTH", "auto")


def test_alpha_with_a_typed_benchmark_keeps_it():
    cfg, errors = _build("^GSPC", target_kind="alpha", benchmark=" ^ftse ")
    resolved = RunConfig.model_validate(cfg)
    assert errors == [] and (resolved.objective.benchmark, resolved.objective.benchmark_source) == ("^FTSE", "manual")


@pytest.mark.parametrize("symbol", ["^VIX", "EURUSD=X", "BTC-USD"])
def test_alpha_on_a_target_without_a_natural_benchmark_is_refused_with_the_way_out(symbol):
    _cfg, errors = _build(symbol, target_kind="alpha")
    assert errors and any("benchmark" in e.lower() and "manuel" in e.lower() for e in errors)


def test_alpha_on_btc_works_with_a_typed_benchmark():
    cfg, errors = _build("BTC-USD", target_kind="alpha", benchmark="^GSPC")
    assert errors == [] and RunConfig.model_validate(cfg).objective.benchmark == "^GSPC"


def test_alpha_on_a_fred_target_is_refused():
    fred = next(s for s, src in forms.TARGET_SOURCE_BY_SYMBOL.items() if src == "fred")
    _cfg, errors = _build(fred, target_kind="alpha", benchmark="^GSPC")
    assert errors and any("FRED" in e for e in errors)


def test_an_unknown_target_kind_is_refused():
    _cfg, errors = _build("^GSPC", target_kind="gamma")
    assert any("type de cible" in e.lower() for e in errors)


def test_a_benchmark_typed_without_alpha_is_ignored_not_applied():
    cfg, errors = _build("^GSPC", target_kind="raw", benchmark="URTH")
    assert errors == [] and "benchmark" not in cfg["objective"]


def test_the_form_view_restores_the_choice_for_a_relaunch():
    auto = RunConfig.model_validate(_build("^GSPC", target_kind="alpha")[0]).model_dump()
    manual = RunConfig.model_validate(_build("^GSPC", target_kind="alpha", benchmark="^FTSE")[0]).model_dump()
    assert (forms.to_view(auto)["target_kind"], forms.to_view(auto)["benchmark"]) == ("alpha", "")       # auto : champ vide
    assert (forms.to_view(manual)["target_kind"], forms.to_view(manual)["benchmark"]) == ("alpha", "^FTSE")
    assert forms.to_view({"objective": {"target_symbol": "^VIX"}})["target_kind"] == "raw"


def test_the_launch_page_offers_the_choice():
    html = TestClient(app).get("/launch").text
    assert 'name="target_kind"' in html and 'name="benchmark"' in html
    assert 'value="alpha"' in html and "id=\"benchmark-field\"" in html


def test_the_launch_page_is_available_in_english_and_leaks_no_key():
    html = TestClient(app).get("/launch?lang=en").text
    assert "Excess return" in html or "excess return" in html
    assert "target_kind_alpha" not in html and "field_benchmark" not in html


def test_posting_an_impossible_alpha_launch_starts_nothing_and_explains(monkeypatch):
    from patrick.webapp import run_manager
    started = []
    monkeypatch.setattr(run_manager, "start_run", lambda cfg: started.append(cfg))
    data = {"target_symbols": ["^VIX"], "target_kind": "alpha", "horizons": ["5"], "regimes": "GLOBAL",
            "families": ["technical"], "n_features_grid": "5", "sampler_candidates": ["SMOTE"], "algos": ["RandomForest"]}

    resp = TestClient(app).post("/runs", data=data)

    assert resp.status_code == 400 and not started
    assert any("manuel" in e for e in resp.json()["errors"])
