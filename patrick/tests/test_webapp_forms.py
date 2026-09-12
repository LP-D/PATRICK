"""`build_config_dict` prend désormais `target_symbol`/`name` en paramètres
explicites (plus jamais lus dans `form`) -- un lancement peut soumettre
plusieurs cibles à la fois, une par appel (cf. patrick/webapp/app.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

import numpy as np
import pandas as pd

from patrick.config import defaults as D
from patrick.data.store import DataStore
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
    # feature/expanded-horizons : `build_config_dict` consulte maintenant
    # `validation/feasibility.py` (donc `data/store.py`) pour valider les
    # horizons soumis -- isole du VRAI `~/.patrick/store` de la machine de
    # dev, sinon ces tests dependraient de son contenu au moment ou ils
    # tournent (non deterministe).
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


def _seed_history(symbol: str, n_obs: int) -> None:
    store = DataStore()  # lit PATRICK_STORE_ROOT (isole par _isolated_db ci-dessus)
    idx = pd.bdate_range("2000-01-01", periods=n_obs)
    df = pd.DataFrame({symbol: np.arange(n_obs, dtype=float)}, index=idx)
    store.save(f"raw_{symbol}", df)


def test_next_run_names_endpoint_returns_one_name_per_target():
    client = TestClient(app)
    resp = client.get("/api/next-run-names", params=[("target", "^VIX"), ("target", "^AORD")])
    assert resp.status_code == 200
    assert resp.json() == {"^VIX": "VIX_1", "^AORD": "AORD_1"}


def test_horizon_feasibility_endpoint_flags_infeasible_horizon_for_short_history():
    _seed_history("BTC-USD", 4371)
    client = TestClient(app)
    resp = client.get("/api/horizon-feasibility", params=[("target", "BTC-USD")])
    assert resp.status_code == 200
    body = resp.json()
    assert body["756"]["feasible"] is False
    assert body["756"]["symbol"] == "BTC-USD"
    assert "4371" in body["756"]["reason"]
    assert body["504"]["feasible"] is True
    assert body["1"]["feasible"] is True


def test_horizon_feasibility_endpoint_all_feasible_for_long_history():
    _seed_history("^GSPC", 6885)
    client = TestClient(app)
    resp = client.get("/api/horizon-feasibility", params=[("target", "^GSPC")])
    body = resp.json()
    assert all(v["feasible"] for v in body.values())


def test_horizon_feasibility_endpoint_aggregates_across_several_targets():
    """Un seul <select multiple name="horizons"> s'applique a TOUTES les
    cibles soumises en meme temps (cf. create_run) -- un horizon infaisable
    pour UNE SEULE des cibles selectionnees doit etre remonte infaisable."""
    _seed_history("BTC-USD", 4371)
    _seed_history("^GSPC", 6885)
    client = TestClient(app)
    resp = client.get("/api/horizon-feasibility",
                       params=[("target", "^GSPC"), ("target", "BTC-USD")])
    body = resp.json()
    assert body["756"]["feasible"] is False
    assert body["756"]["symbol"] == "BTC-USD"


def test_horizon_feasibility_endpoint_feasible_when_nothing_cached():
    client = TestClient(app)
    resp = client.get("/api/horizon-feasibility", params=[("target", "^VIX")])
    body = resp.json()
    assert all(v["feasible"] for v in body.values())


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


# feature/expanded-horizons -- une combinaison (cible, horizon) infaisable
# (fold de walk-forward integralement vide apres embargo, cf.
# `validation/feasibility.py`) doit etre rejetee ICI, avant `RunConfig`/le
# pipeline, meme si le <option disabled> cote client a ete contourne (JS
# desactive, appel direct a POST /runs...).
def test_build_config_dict_rejects_horizon_infeasible_for_the_selected_target():
    _seed_history("^VIX", 4371)  # ~ meme profondeur que BTC-USD lors de l'audit
    form = _minimal_form(horizons=["756"])
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_13")
    assert any("horizons" in e.lower() and "insuffisant" in e.lower() for e in errors)


def test_build_config_dict_accepts_horizon_feasible_for_the_selected_target():
    _seed_history("^VIX", 6885)  # ~ meme profondeur que ^GSPC lors de l'audit
    form = _minimal_form(horizons=["756"])
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_14")
    assert errors == []
    assert config_dict["objective"]["horizons"] == [756]


def test_build_config_dict_does_not_block_horizons_for_a_never_cached_target():
    """Rien en cache pour cette cible : principe directeur de cette session
    (exposer avec avertissement plutot que bloquer par prudence) -- pas
    d'erreur tant que l'infaisabilite n'est pas CONNUE."""
    form = _minimal_form(horizons=["756"])
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_15")
    assert errors == []
    assert config_dict["objective"]["horizons"] == [756]


def test_build_config_dict_rejects_horizon_infeasible_under_the_actually_submitted_n_wf_folds():
    """Suivi d'audit : `build_config_dict` appelait
    `feasibility.check_feasibility(target_symbol, h)` SANS jamais transmettre
    les `n_wf_folds`/`min_train_frac` reellement soumis dans `form` (les deux
    sont personnalisables sur /launch depuis feature/hyperparams-ui) --
    verifiant donc toujours la faisabilite sous
    DEFAULT_N_WF_FOLDS/DEFAULT_MIN_TRAIN_FRAC, quelle que soit la
    configuration reellement demandee pour CE run.

    Cas concret construit a la main (verifie directement via
    `feasibility.min_test_fold_size`) : n_obs=1000, horizon=100.
      - Sous les defauts (n_wf_folds=5, min_train_frac=0.40) :
        fold=120 > 100 -> feasible=True.
      - Sous n_wf_folds=10 (min_train_frac inchange) reellement soumis dans
        `form` : fold=60 <= 100 -> feasible=False -- ce run produirait un
        fold de test integralement vide apres embargo (embargo_bars=horizon
        par defaut, cf. validation/embargo.py), pas juste un indicateur UI
        perime : `pipeline/engine.py::build_fold_cuts` utilisera bien
        n_wf_folds=10 pour CE run.

    Avant correction : aucune erreur (le backend valide sous les DEFAUTS,
    pas sous ce qui est reellement soumis) -- la combinaison passe a tort."""
    _seed_history("^VIX", 1000)
    form = _minimal_form(horizons=["100"], n_wf_folds="10")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_16")
    assert any("horizons" in e.lower() and "insuffisant" in e.lower() for e in errors), (
        "la combinaison (^VIX, horizon=100, n_wf_folds=10 reellement soumis) est "
        "infaisable (fold=60<=100) mais aucune erreur n'a ete levee -- le backend "
        "valide sous DEFAULT_N_WF_FOLDS=5 (fold=120>100), pas sous ce qui est "
        "reellement demande pour ce run"
    )


# Phase 3 (feature/hyperparams-lookbacks) -- les lookbacks de features
# (fenetres de returns/zscore/ma_ratio/rolling_vol/ohlc_vol,
# `features/technical.py`) n'avaient aucune surface de configuration avant
# ce changement (audit : fonctions deja parametrees via un argument
# `windows=`, jamais appelees avec un argument explicite depuis
# `pipeline/engine.py`). `tl__{champ}` est le nom de champ choisi cote
# `index.html` (une liste d'entiers separee par des virgules, meme
# convention que `n_features_grid`).
def test_build_config_dict_defaults_technical_lookbacks_when_form_omits_them():
    """Un formulaire qui ne soumet pas les champs de lookbacks (ancien
    formulaire, ou test existant type `_minimal_form()`) doit produire
    exactement les lookbacks par defaut -- comportement inchange."""
    form = _minimal_form()
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_17")
    assert errors == []
    tl = config_dict["features"]["technical_lookbacks"]
    assert tl["returns_windows"] == D.DEFAULT_RETURNS_WINDOWS
    assert tl["zscore_windows"] == D.DEFAULT_ZSCORE_WINDOWS
    assert tl["ma_ratio_windows"] == D.DEFAULT_MA_RATIO_WINDOWS
    assert tl["rolling_vol_windows"] == D.DEFAULT_ROLLING_VOL_WINDOWS
    assert tl["ohlc_vol_windows"] == D.DEFAULT_OHLC_VOL_WINDOWS


def test_build_config_dict_reads_custom_technical_lookbacks_from_form():
    form = _minimal_form(**{"tl__returns_windows": "3,7,14"})
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_18")
    assert errors == []
    assert config_dict["features"]["technical_lookbacks"]["returns_windows"] == [3, 7, 14]
    # Les autres champs, non touches, restent par defaut.
    assert config_dict["features"]["technical_lookbacks"]["zscore_windows"] == D.DEFAULT_ZSCORE_WINDOWS


def test_build_config_dict_accepts_range_syntax_for_technical_lookbacks():
    """Meme syntaxe `lo-hi` que `n_features_grid` (`_int_list`)."""
    form = _minimal_form(**{"tl__rolling_vol_windows": "5-7"})
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_19")
    assert errors == []
    assert config_dict["features"]["technical_lookbacks"]["rolling_vol_windows"] == [5, 6, 7]


def test_build_config_dict_rejects_non_positive_returns_window():
    form = _minimal_form(**{"tl__returns_windows": "-3,5"})
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_20")
    assert any("rendements" in e.lower() for e in errors)


def test_build_config_dict_rejects_zero_zscore_window():
    form = _minimal_form(**{"tl__zscore_windows": "0,10"})
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_21")
    assert any("z-score" in e.lower() for e in errors)


def test_build_config_dict_rejects_ohlc_vol_window_below_two():
    """`yang_zhang_vol` divise par (window - 1) -- window=1 ferait planter
    le pipeline avec un ZeroDivisionError (mesure, voir
    tests/test_technical_lookbacks.py) plutot que d'etre rejete ici."""
    form = _minimal_form(**{"tl__ohlc_vol_windows": "1,10"})
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_22")
    assert any("ohlc" in e.lower() for e in errors)


def test_build_config_dict_rejects_non_numeric_technical_lookback():
    form = _minimal_form(**{"tl__ma_ratio_windows": "abc"})
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_23")
    assert any("moyenne mobile" in e.lower() for e in errors)


def test_build_config_dict_rejects_technical_lookback_above_max_allowed():
    form = _minimal_form(**{"tl__returns_windows": "999999"})
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_24")
    assert any("rendements" in e.lower() for e in errors)
