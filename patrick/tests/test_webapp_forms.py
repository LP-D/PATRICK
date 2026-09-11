"""`build_config_dict` prend désormais `target_symbol`/`name` en paramètres
explicites (plus jamais lus dans `form`) -- un lancement peut soumettre
plusieurs cibles à la fois, une par appel (cf. patrick/webapp/app.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.webapp import forms
from patrick.webapp.app import app


def _minimal_form(**overrides) -> FormData:
    base = {
        "horizons": ["1", "2"],
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


def test_build_config_dict_reads_horizons_as_repeated_multi_select_values():
    """`horizons` used to be a free-text input, submitted as a single
    comma-joined string (`"1,2"`) and read with `form.get`. It is now a
    native `<select multiple name="horizons">` (see index.html), which HTML
    forms submit as several values repeated under the SAME key -- exactly
    like `families`/`algos`/`sampler_candidates` already are. `form.get`
    would silently keep only the first of those values; this asserts all
    of them make it into the parsed config, in the order submitted."""
    form = _minimal_form(horizons=["1", "5", "10"])
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_3")
    assert errors == []
    assert config_dict["objective"]["horizons"] == [1, 5, 10]


# Phase 1 (feature/hyperparams-ui) -- audit : `n_trials`/`top_k`/`cv_splits`
# etaient deja exposes dans le formulaire (index.html, section_tuning) mais
# JAMAIS valides cote serveur au-dela d'une erreur de type ("un champ
# numerique entier est invalide") -- un n_trials negatif ou un cv_splits=1
# passait tel quel jusqu'a `RunConfig` (pydantic, sans bornes, cf. docstring
# du module) puis jusqu'a Optuna/sklearn, avec une erreur illisible loin du
# formulaire. Ces tests fixent des bornes raisonnables cote `build_config_dict`.
def test_build_config_dict_rejects_non_positive_n_trials():
    form = _minimal_form(n_trials="0")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_4")
    assert any("essais optuna" in e.lower() for e in errors)


def test_build_config_dict_rejects_non_positive_top_k():
    form = _minimal_form(top_k="-1")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_5")
    assert any("top-k" in e.lower() for e in errors)


def test_build_config_dict_rejects_cv_splits_below_two():
    form = _minimal_form(cv_splits="1")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_6")
    assert any("cv" in e.lower() for e in errors)


def test_build_config_dict_accepts_valid_tuning_bounds():
    form = _minimal_form(n_trials="50", top_k="3", cv_splits="4")
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_7")
    assert errors == []
    assert config_dict["tuning"]["n_trials"] == 50
    assert config_dict["tuning"]["top_k"] == 3
    assert config_dict["tuning"]["cv_splits"] == 4


# flexibility-gaps Gap 7 -- validation.holdout_months (config/schema.py,
# already YAML-configurable, bounds 12-24) was never exposed on /launch.
# Same "server-side bound before RunConfig ever sees it" pattern as the
# n_trials/top_k/cv_splits tests above.

def test_build_config_dict_defaults_holdout_months_when_form_omits_it():
    form = _minimal_form()
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_HM_1")
    assert errors == []
    assert config_dict["validation"]["holdout_months"] == D.DEFAULT_HOLDOUT_MONTHS


def test_build_config_dict_reads_custom_holdout_months_from_form():
    form = _minimal_form(holdout_months="18")
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_HM_2")
    assert errors == []
    assert config_dict["validation"]["holdout_months"] == 18


def test_build_config_dict_rejects_holdout_months_below_twelve():
    form = _minimal_form(holdout_months="11")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_HM_3")
    assert any("holdout" in e.lower() for e in errors)


def test_build_config_dict_rejects_holdout_months_above_twenty_four():
    form = _minimal_form(holdout_months="25")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_HM_4")
    assert any("holdout" in e.lower() for e in errors)


def test_build_config_dict_holdout_months_boundaries_are_accepted():
    for value in ("12", "24"):
        form = _minimal_form(holdout_months=value)
        config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name=f"VIX_HM_{value}")
        assert errors == []
        assert config_dict["validation"]["holdout_months"] == int(value)


def test_to_view_reflects_holdout_months_from_config():
    cfg = forms.default_config_dict()
    cfg["validation"]["holdout_months"] = 20
    view = forms.to_view(cfg)
    assert view["holdout_months"] == 20


def test_to_view_defaults_holdout_months_when_absent_from_config():
    cfg = forms.default_config_dict()
    del cfg["validation"]["holdout_months"]
    view = forms.to_view(cfg)
    assert view["holdout_months"] == D.DEFAULT_HOLDOUT_MONTHS


# Phase 1 (feature/hyperparams-ui) -- la grille Optuna (bornes [low, high] par
# hyperparametre et par algo, `tuning/optuna_runner.py::suggest_params`)
# n'avait ABSOLUMENT aucune surface de configuration avant ce changement : ni
# champ de formulaire, ni cle dans `RunConfig`. `ob__{algo}__{param}__low`/
# `__high` est le nom de champ choisi cote `index.html` pour cette nouvelle
# section.
def test_build_config_dict_defaults_optuna_bounds_when_form_omits_them():
    """Un formulaire qui ne soumet pas les champs de bornes (ancien
    formulaire, ou test existant type `_minimal_form()`) doit produire
    exactement les bornes par defaut -- comportement inchange."""
    form = _minimal_form()
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_8")
    assert errors == []
    assert config_dict["tuning"]["optuna_bounds"] == D.DEFAULT_OPTUNA_BOUNDS


def test_build_config_dict_reads_custom_optuna_bounds_from_form():
    form = _minimal_form(**{
        "ob__XGBoost__n_estimators__low": "120",
        "ob__XGBoost__n_estimators__high": "180",
    })
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_9")
    assert errors == []
    assert config_dict["tuning"]["optuna_bounds"]["XGBoost"]["n_estimators"] == [120, 180]
    # Les autres hyperparametres de XGBoost, non touches, restent par defaut.
    assert config_dict["tuning"]["optuna_bounds"]["XGBoost"]["max_depth"] == \
        D.DEFAULT_OPTUNA_BOUNDS["XGBoost"]["max_depth"]


def test_build_config_dict_rejects_optuna_bound_low_greater_than_high():
    form = _minimal_form(**{
        "ob__RandomForest__n_estimators__low": "500",
        "ob__RandomForest__n_estimators__high": "100",
    })
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_10")
    assert any("randomforest.n_estimators" in e.lower() for e in errors)


def test_build_config_dict_rejects_optuna_bound_outside_allowed_range():
    form = _minimal_form(**{
        "ob__CatBoost__depth__low": "1",
        "ob__CatBoost__depth__high": "9999",
    })
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_11")
    assert any("catboost.depth" in e.lower() for e in errors)


def test_build_config_dict_rejects_non_numeric_optuna_bound():
    form = _minimal_form(**{"ob__XGBoost__max_depth__low": "abc"})
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_12")
    assert any("xgboost.max_depth" in e.lower() for e in errors)
