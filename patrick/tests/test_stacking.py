"""Empilement (`models/stacking.py`) : N modèles de base divers, rigueur d'entraînement allégée, méta-modèle appris UNIQUEMENT sur des
probabilités hors-échantillon ; branché comme un algorithme de plus (« Stacking ») dans la grille du scan, le holdout et l'export."""
from __future__ import annotations

import json
import pickle

import joblib
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from patrick.config import defaults as D
from patrick.config import training_profiles
from patrick.config.schema import RunConfig
from patrick.models import registry
from patrick.models import stacking as stk
from patrick.pipeline import engine
from patrick.pipeline.leaderboard import Leaderboard
from patrick.tracking import retrain_advisor
from patrick.tracking.export import export_best_model
from patrick.webapp import forms

ALGOS = ["XGBoost", "LightGBM", "RandomForest"]


def _data(n=700, p=10, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p))
    signal = X[:, 0] * 0.8 + X[:, 1] * 0.4 + rng.normal(size=n)
    y = np.digitize(signal, np.quantile(signal, [0.25, 0.5, 0.75]))
    return X, y


# ---------------------------------------------------------------- le panel de modèles de base

def test_the_panel_is_reproducible_and_has_exactly_n_models():
    a = stk.draw_base_specs(9, ALGOS, 3, 10)
    assert len(a) == 9 and a == stk.draw_base_specs(9, ALGOS, 3, 10)
    assert a != stk.draw_base_specs(9, ALGOS, 4, 10)                         # une autre graine, un autre panel
    assert [s["algo"] for s in a] == [ALGOS[i % 3] for i in range(9)]       # les algorithmes en tournée


def test_the_panel_is_diverse_on_purpose_good_and_bad():
    specs = stk.draw_base_specs(40, ["XGBoost", "LightGBM"], 1, 12)
    depths = {s["params"]["max_depth"] for s in specs}
    assert min(depths) <= 2 and max(depths) >= 6                              # des modèles faibles ET forts, pas un seul réglage
    assert len({tuple(s["columns"]) for s in specs}) > 30                    # sous-ensembles de variables différents
    assert len({s["seed"] for s in specs}) == 40
    assert all(stk.FEATURE_FRACTION[0] - 0.1 <= len(s["columns"]) / 12 <= 1.0 for s in specs)
    for s in specs:                                                           # tout reste dans les plages déclarées
        for name, (lo, hi, _log) in stk.BASE_RANGES[s["algo"]].items():
            assert lo <= s["params"][name] <= hi, (s["algo"], name, s["params"][name])


def test_a_stack_needs_at_least_one_tree_algorithm():
    with pytest.raises(ValueError, match="arbres"):
        stk.draw_base_specs(5, ["MLP", "GRU"], 1, 10)


# ---------------------------------------------------------------- l'apprentissage : pas de fuite vers le méta-modèle

def test_meta_model_is_fitted_on_the_late_out_of_sample_rows_only(monkeypatch):
    X, y = _data(500)
    calls = []
    original = stk.StackingEnsemble._fit_base

    def spy(self, spec, X_, y_, sample_weight):
        calls.append(len(y_))
        return original(self, spec, X_, y_, sample_weight)

    monkeypatch.setattr(stk.StackingEnsemble, "_fit_base", spy)
    clf = stk.StackingEnsemble(n_models=4, algos=ALGOS, seed=1, gap=5, oof_frac=0.3).fit(X, y)
    split, base_end = 350, 345                                                # 70 % ; trou d'un horizon avant la partie récente
    assert calls == [base_end] * 4 + [500] * 4                                # bases sur l'ancien, puis réajustées sur tout
    assert clf.stacked_ and clf.meta_scaler_.n_samples_seen_ == 500 - split  # le méta-modèle ne voit que les 150 lignes récentes


def test_the_resampler_only_touches_the_fit_rows_never_the_meta_rows():
    X, y = _data(600)
    clf = stk.StackingEnsemble(n_models=3, algos=["XGBoost", "LightGBM"], seed=2, sampler="SMOTE", gap=3).fit(X, y)
    assert clf.meta_scaler_.n_samples_seen_ == 600 - round(600 * 0.7)   # lignes réelles, pas de ligne synthétique


def test_probabilities_are_valid_and_aligned_on_the_classes():
    X, y = _data(700)
    clf = stk.StackingEnsemble(n_models=5, algos=ALGOS, seed=3, gap=5).fit(X[:500], y[:500])
    proba = clf.predict_proba(X[500:])
    assert proba.shape == (200, 4) and np.allclose(proba.sum(axis=1), 1.0, atol=1e-6) and (proba >= 0).all()
    assert set(clf.predict(X[500:])) <= {0, 1, 2, 3}
    assert (clf.predict(X[500:]) == clf.classes_[proba.argmax(axis=1)]).all()


def test_a_class_missing_from_the_training_rows_gets_a_zero_column():
    X, y = _data(700)
    y3 = np.where(y == 0, 1, y)                                               # la classe 0 n'existe pas
    clf = stk.StackingEnsemble(n_models=4, algos=["XGBoost", "RandomForest"], seed=1, gap=5).fit(X[:500], y3[:500])
    assert list(clf.classes_) == [1, 2, 3]
    proba = clf.predict_proba(X[500:])
    assert proba.shape == (200, 3) and np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_too_short_a_train_falls_back_to_the_plain_average_without_a_meta_model():
    X, y = _data(80)
    clf = stk.StackingEnsemble(n_models=3, algos=["XGBoost"], seed=1, gap=5).fit(X, y)
    assert not clf.stacked_ and clf.meta_ is None
    assert np.allclose(clf.predict_proba(X[:5]).sum(axis=1), 1.0, atol=1e-6)


def test_the_stack_survives_pickling_and_reports_its_settings():
    X, y = _data(500)
    clf = stk.StackingEnsemble(n_models=3, algos=["XGBoost", "LightGBM"], seed=5, gap=5).fit(X, y)
    again = pickle.loads(pickle.dumps(clf))
    assert np.allclose(again.predict_proba(X[:10]), clf.predict_proba(X[:10]))
    assert clf.settings() == {"n_models": 3, "algos": ["XGBoost", "LightGBM"], "oof_frac": 0.3, "meta_c": stk.DEFAULT_META_C}


# ---------------------------------------------------------------- dans le moteur

def test_the_registry_builds_a_stack_from_the_run_settings_or_the_explicit_ones():
    registry.set_stack_defaults({"n_models": 7, "algos": ["XGBoost"]})
    try:
        assert registry.get_classifier(registry.STACK_ALGO, seed=1).n_models == 7
        assert registry.get_classifier(registry.STACK_ALGO, seed=1, stack={"n_models": 4, "algos": ["LightGBM"]}).n_models == 4
        assert registry.get_classifier("XGBoost", seed=1, stack={"n_models": 4}).__class__.__name__ == "AnyLabelXGBClassifier"
    finally:
        registry.set_stack_defaults(None)


@pytest.mark.parametrize("sampler", ["none", "SMOTE"])
def test_fit_eval_full_scores_a_stack_like_any_other_algorithm(sampler):
    X, y = _data(700)
    met, y_pred, confidence, p_up = engine._fit_eval_full(
        X[:500], y[:500], X[500:], y[500:], sampler, registry.STACK_ALGO, 42, calibration_gap=5,
        stack={"n_models": 4, "algos": ["XGBoost", "LightGBM"]})
    assert len(y_pred) == 200 and len(confidence) == 200 and len(p_up) == 200
    assert 0.0 <= met["F1_dir"] <= 1.0 and "AUC_ovr_4cls" in met and "Brier_up" in met


def test_a_stack_can_be_calibrated_like_any_other_algorithm():
    X, y = _data(900)
    met, *_ = engine._fit_eval_full(X[:700], y[:700], X[700:], y[700:], "SMOTE", registry.STACK_ALGO, 42, calibration=True,
                                    calibration_gap=5, stack={"n_models": 3, "algos": ["XGBoost", "LightGBM"]})
    assert 0.0 <= met["F1_dir"] <= 1.0


def _config(**models) -> RunConfig:
    return RunConfig.model_validate({"objective": {"target_symbol": "^GSPC", "horizons": [1]}, "models": models})


def test_the_scan_grid_gets_one_more_algorithm_only_when_stacking_is_on():
    assert engine.scan_algos(_config(algos=["XGBoost", "LightGBM"])) == ["XGBoost", "LightGBM"]
    assert engine.scan_algos(_config(algos=["XGBoost", "LightGBM"], stacking=True)) == ["XGBoost", "LightGBM", "Stacking"]


def test_optuna_never_tunes_the_stack():
    board = Leaderboard()
    board.rows = [{"horizon": 1, "algo": a, "N": 8, "sampler": "none", "regime": "GLOBAL", "fold": 1, "F1_dir": f}
                  for a, f in (("XGBoost", 0.5), (registry.STACK_ALGO, 0.9))]
    kept = engine._without_stack(board)
    assert [r["algo"] for r in kept.rows] == ["XGBoost"]
    assert [c["algo"] for c in kept.top_k(2)] == ["XGBoost"]                  # le meilleur de la grille n'est pas pris par le réglage


def test_the_estimate_of_the_progress_bar_counts_the_stack():
    from patrick import worker
    base = worker._estimate_total(_config(algos=["XGBoost", "LightGBM"]))
    assert worker._estimate_total(_config(algos=["XGBoost", "LightGBM"], stacking=True)) > base


# ---------------------------------------------------------------- la configuration

def test_a_run_without_stacking_keeps_exactly_its_serialised_configuration_and_hash():
    models = _config(algos=["XGBoost", "LightGBM"]).models.model_dump()
    assert "stacking_n_models" not in models and models["stacking"] is False
    assert "stacking_n_models" not in json.loads(_config().model_dump_json())["models"]
    on = json.loads(_config(stacking=True, stacking_n_models=15).model_dump_json())["models"]
    assert on["stacking"] is True and on["stacking_n_models"] == 15


def test_the_number_of_models_is_bounded():
    lo, hi = D.STACKING_N_MODELS_BOUNDS
    for bad in (lo - 1, hi + 1):
        with pytest.raises(ValidationError):
            _config(stacking=True, stacking_n_models=bad)
    assert _config(stacking=True, stacking_n_models=lo).models.stacking_n_models == lo


def test_stacking_is_refused_in_cpcv_and_without_a_tree_algorithm():
    with pytest.raises(ValidationError, match="CPCV"):
        RunConfig.model_validate({"objective": {"target_symbol": "^GSPC", "horizons": [1]}, "validation": {"scheme": "cpcv"},
                                  "models": {"stacking": True}})
    with pytest.raises(ValidationError, match="arbres"):
        RunConfig.model_validate({"objective": {"target_symbol": "^GSPC", "horizons": [1]}, "sampler": {"candidates": ["none"]},
                                  "models": {"algos": ["MLP", "GRU"], "stacking": True}})


# ---------------------------------------------------------------- le formulaire, les profils, le conseiller

class _Form(dict):
    def getlist(self, name):
        value = self.get(name, [])
        return value if isinstance(value, list) else [value]


def _form(**over):
    base = {"horizons": ["1"], "regimes": "GLOBAL", "families": ["technical"], "n_features_grid": "5,6", "sampler_candidates": ["SMOTE"],
            "algos": ["XGBoost", "LightGBM"], "staged_screening": "on", "track_stability": "on", "uniqueness_weights": "on",
            "data_quality_enabled": "on", "embargo_enabled": "on", "tuning_enabled": "on", "optuna_select_top_k_per_horizon": "on"}
    base.update(over)
    return _Form(base)


def test_the_form_reads_the_number_of_models_entered_by_hand():
    cfg, errors = forms.build_config_dict(_form(stacking="on", stacking_n_models="25"), target_symbol="^GSPC", name="G_1")
    assert not errors and cfg["models"]["stacking"] is True and cfg["models"]["stacking_n_models"] == 25
    assert RunConfig.model_validate(cfg).models.stacking_n_models == 25
    assert forms.to_view(cfg)["stacking_n_models"] == 25


def test_the_form_refuses_an_out_of_range_number_only_when_stacking_is_ticked():
    _lo, hi = D.STACKING_N_MODELS_BOUNDS
    _, errors = forms.build_config_dict(_form(stacking="on", stacking_n_models=str(hi + 1)), target_symbol="^GSPC", name="G_1")
    assert any("Modèles de base" in e and str(hi) in e for e in errors)
    _, errors = forms.build_config_dict(_form(stacking_n_models="0"), target_symbol="^GSPC", name="G_1")
    assert not any("Modèles de base" in e for e in errors)                   # case décochée : le champ ne bloque rien
    _, errors = forms.build_config_dict(_form(stacking="on", stacking_n_models="abc"), target_symbol="^GSPC", name="G_1")
    assert any("Modèles de base" in e for e in errors)


def test_the_launch_page_has_the_number_field_next_to_stacking_and_the_dl_page_has_no_stacking_box():
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app
    client = TestClient(app)
    ml = client.get("/ml").text
    assert 'name="stacking"' in ml and 'name="stacking_n_models"' in ml
    assert f'min="{D.STACKING_N_MODELS_BOUNDS[0]}" max="{D.STACKING_N_MODELS_BOUNDS[1]}"' in ml
    assert 'name="stacking"' not in client.get("/dl").text                    # la case n'y servait à rien : le stack exige des modèles à arbres


def test_the_stacking_profile_only_cites_fields_of_the_form_and_builds_a_valid_run():
    assert retrain_advisor.validate_patches() == []
    view = forms.to_view(forms.default_config_dict())
    patched = training_profiles.apply_patch(view, training_profiles.get("stacking").resolved_patch())
    cfg, errors = forms.build_config_dict(forms.FormFromView(patched), target_symbol="^GSPC", name="G_1")
    assert not errors
    run = RunConfig.model_validate(cfg)
    assert run.models.stacking and run.models.stacking_n_models == 20 and not run.tuning.enabled


def test_the_advisor_prices_a_stack_by_its_number_of_models():
    before = forms.to_view(forms.default_config_dict())
    small = {**before, "stacking": True, "stacking_n_models": 5}
    large = {**before, "stacking": True, "stacking_n_models": 40}
    assert 1.0 < retrain_advisor.cost_factor(before, small) < retrain_advisor.cost_factor(before, large)


# ---------------------------------------------------------------- l'export

def test_the_exported_stack_records_its_panel_so_a_duel_can_replay_it(tmp_path):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=500)
    pool = pd.DataFrame({"TGT": 100 + np.cumsum(rng.normal(0, 1, 500))}, index=idx)
    for j in range(6):
        pool[f"f{j}"] = rng.normal(0, 0.01, 500)
    feature_pool = [c for c in pool.columns if c != "TGT"]
    config = RunConfig.model_validate({
        "objective": {"target_symbol": "^TGT", "horizons": [1]}, "selection": {"method": "shap", "n_features_grid": [4], "shap_sample": 100},
        "features": {"pool_prefilter": 10}, "models": {"algos": ["XGBoost", "LightGBM"], "stacking": True, "stacking_n_models": 4},
    })
    registry.set_stack_defaults(config.models.stack_settings())
    try:
        best_cfg = {"horizon": 1, "regime": "GLOBAL", "N": 4, "sampler": "SMOTE", "algo": registry.STACK_ALGO}
        path = export_best_model(pool, "TGT", feature_pool, config, best_cfg, str(tmp_path))
    finally:
        registry.set_stack_defaults(None)
    bundle = joblib.load(path)
    assert isinstance(bundle["model"], stk.StackingEnsemble) and bundle["model"].n_models == 4
    with open(path[: -len(".joblib")] + "_meta.json") as f:
        meta = json.load(f)
    assert meta["algo"] == "Stacking"
    assert meta["best_params"]["stack"] == {"n_models": 4, "algos": ["XGBoost", "LightGBM"], "oof_frac": 0.3, "meta_c": stk.DEFAULT_META_C}
    proba = bundle["model"].predict_proba(bundle["scaler"].transform(pool[feature_pool].iloc[-3:].to_numpy())[:, [feature_pool.index(f) for f in bundle["feature_names"]]])
    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)


# ---------------------------------------------------------------- bout en bout (lent : un vrai run sur données synthétiques)

@pytest.mark.slow
def test_a_whole_run_scans_the_stack_skips_optuna_for_it_and_exports_a_working_model(tmp_path, monkeypatch):
    from patrick.data.store import DataStore

    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=1500)
    raw = pd.DataFrame({"IDX_TEST": 15 + np.cumsum(rng.normal(0, 0.5, 1500))}, index=idx)
    raw["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, 1500))
    raw["NFCI"] = np.cumsum(rng.normal(0, 0.02, 1500))
    config = RunConfig.model_validate({
        "name": "stack_e2e", "objective": {"target_symbol": "^TEST", "horizons": [3], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI"}, "start_date": "2015-01-01"},
        "features": {"families": ["technical", "macro"], "pool_prefilter": 40},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 100},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["XGBoost", "LightGBM"], "stacking": True, "stacking_n_models": 4},
        "tuning": {"enabled": True, "top_k": 3, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    })
    monkeypatch.setattr(engine, "ingest", lambda *a, **k: raw)
    result = engine.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")), db_path=str(tmp_path / "p.db"))

    board = result["leaderboard"]
    assert set(board.loc[board["N"].notna(), "algo"]) >= {"XGBoost", "LightGBM", "Stacking"}
    assert board["F1_dir"].between(0, 1).all()
    assert len(result["tuned"]) > 0 and "Stacking" not in set(result["tuned"]["algo"])   # Optuna ne règle jamais l'empilement
    assert result["model_path"] and result["final_best"] is not None
    bundle = joblib.load(result["model_path"])
    assert hasattr(bundle["model"], "predict_proba")


# ---------------------------------------------------------------- l'explication d'une prédiction

def test_a_stack_is_explained_by_permutation_shapley_not_by_a_tree_explainer():
    from sklearn.preprocessing import RobustScaler

    from patrick import explain

    X, y = _data(500, p=6)
    names = [f"f{i}" for i in range(6)]
    scaler = RobustScaler().fit(X)
    model = stk.StackingEnsemble(n_models=4, algos=["XGBoost", "LightGBM"], seed=1, gap=3).fit(scaler.transform(X), y)
    assert model.is_stack and not getattr(model, "is_deep", False)
    idx = pd.bdate_range("2020-01-01", periods=len(X))
    pool = pd.DataFrame(X, index=idx, columns=names)
    ts = idx[-1]
    row = scaler.transform(pool.loc[[ts], names].to_numpy())
    pred_class = int(model.predict(row)[0])
    contrib, base, units = explain._deep_contributions(model, pool, names, scaler, list(range(6)), ts, pred_class)
    assert units == "probability" and contrib.shape == (6,)
    final = float(model.predict_proba(row)[0][list(model.classes_).index(pred_class)])
    assert base + contrib.sum() == pytest.approx(final, abs=1e-6)          # additivité : la somme redonne la probabilité
