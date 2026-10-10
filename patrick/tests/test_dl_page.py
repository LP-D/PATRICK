"""Page /dl (cadrage du deep learning) : vue simplifiée + vue experte, profils, traduction du formulaire en `RunConfig`, lancement
refusé sans PyTorch. Vraies routes FastAPI et vrais gabarits ; aucun worker n'est lancé (`run_manager.start_run` est remplacé)."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.config import dl_profiles
from patrick.config.schema import RunConfig
from patrick.data.sources import fundamentals_source
from patrick.models import deep as deep_models
from patrick.validation import equity_sufficiency
from patrick.webapp import forms, i18n, run_manager
from patrick.webapp.app import app


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(equity_sufficiency.yfinance_source, "download_one", lambda symbol, start: pd.Series(np.arange(100, dtype=float)))
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals", lambda symbol: pd.DataFrame(columns=["fiscalDateEnding", "metric", "value"]))


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _form(**over):
    base = {
        "family": "dl", "target_symbols": ["^VIX"], "horizons": ["5"], "regimes": "GLOBAL", "flat_thr": "0.003",
        "families": ["technical", "spike"], "vol_models": ["egarch"], "n_features_grid": "8,12", "sampler_candidates": ["none"],
        "algos": ["MLP", "GRU"], "selection_method": "shap", "n_wf_folds": "3", "tuning_enabled": "on", "n_trials": "10",
        "top_k": "1", "cv_splits": "3", "seed": "42", "min_history_years": "5", "output_dir": "",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- page


def test_the_page_offers_networks_only_and_every_training_field(client):
    html = client.get("/dl").text
    assert "Deep learning" in html and 'name="family" value="dl"' in html
    for algo in D.ALL_DL_ALGOS:
        assert f'name="algos" value="{algo}"' in html
    for tree in D.ALL_ML_ALGOS:
        assert f'name="algos" value="{tree}"' not in html
    for key in D.DEFAULT_DEEP:
        assert f'name="dl_{key}"' in html, key
    assert 'name="calibration"' in html and 'name="stacking"' in html


def test_the_simple_view_keeps_the_networks_visible_and_folds_the_detail(client):
    html = client.get("/dl").text
    assert 'id="run-form" data-mode="simple"' in html and 'id="settings-mode-toggle"' in html
    # le choix des réseaux est hors d'un bloc <details class="adv"> (visible en vue simplifiée) ...
    networks = html.index('class="dl-networks"')
    assert 'class="adv"' not in html[networks:html.index("</fieldset>", networks)]
    # ... et chaque groupe de réglages est un bloc replié de la vue experte
    for group in ("arch", "train", "compute"):
        assert f'data-adv="section_deep_{group}"' in html
    assert 'name="dl_hidden_size" step="1" min="4" max="512" value="64"' in html


def test_the_defaults_are_the_deep_learning_starting_point(client):
    html = client.get("/dl").text
    assert re.search(r'name="algos" value="MLP"\s+checked', html) and re.search(r'name="algos" value="GRU"\s+checked', html)
    assert not re.search(r'name="algos" value="LSTM"\s+checked', html)
    assert re.search(r'name="sampler_candidates" value="none"\s+checked', html)
    assert not re.search(r'name="sampler_candidates" value="SMOTE"\s+checked', html)
    assert 'name="dl_epochs" step="1" min="1" max="500" value="30"' in html
    assert 'name="n_trials"' in html and 'value="15"' in html


def test_the_optuna_bounds_section_lists_the_networks_and_no_tree(client):
    html = client.get("/dl").text
    assert 'name="ob__GRU__hidden_size__low"' in html and 'name="ob__Transformer__lookback__high"' in html
    assert 'name="ob__MLP__lookback__low"' not in html            # le MLP n'a pas de fenêtre
    assert 'name="ob__XGBoost__n_estimators__low"' not in html
    assert 'name="ob__GRU__hidden_size__low"' in html and 'value="16"' in html


def test_the_machine_learning_page_does_not_offer_networks_or_their_fields(client):
    html = client.get("/ml").text
    assert 'name="family" value="ml"' in html
    assert 'name="algos" value="MLP"' not in html and 'name="dl_hidden_size"' not in html
    assert 'name="ob__GRU__hidden_size__low"' not in html


def test_the_page_names_the_glossary_terms_of_every_network_and_setting(client):
    html = client.get("/dl").text
    for term in ("MLP", "GRU", "LSTM", "CNN1D", "Transformer", "dl_hidden_size", "dl_dropout", "dl_lookback", "dl_patience", "dl_networks"):
        assert f'data-term="{term}"' in html, term
    from patrick.webapp.glossary import GLOSSARY, TERM_LABEL_KEYS
    for key in D.DEFAULT_DEEP:
        assert GLOSSARY[f"dl_{key}"]["fr"] and GLOSSARY[f"dl_{key}"]["en"]
        assert TERM_LABEL_KEYS[f"dl_{key}"] in i18n.STRINGS


def test_english_page_leaks_no_translation_key(client):
    client.cookies.set(i18n.LANG_COOKIE, "en")
    html = client.get("/dl").text
    visible = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    assert "Averaged networks" in visible and not re.search(r"\bdl_[a-z_]+\b(?!\")", re.sub(r'(name|data-term|data-adv|id|for|value)="[^"]*"', "", visible))


def test_without_torch_the_page_warns_and_disables_the_launch_button(client, monkeypatch):
    monkeypatch.setattr(deep_models, "torch_available", lambda: False)
    html = client.get("/dl").text
    assert "PyTorch n&#39;est pas installé" in html
    assert re.search(r'id="launch-btn"\s+disabled', html)
    assert 'id="launch-btn" disabled' not in client.get("/ml").text


# --------------------------------------------------------------------------- profils


def test_every_profile_patches_only_fields_the_form_knows_and_has_its_texts():
    view = forms.to_view(forms.default_config_dict("dl"))
    assert len(dl_profiles.PROFILES) >= 6
    for profile in dl_profiles.PROFILES:
        patched = dl_profiles.apply_patch(view, profile.resolved_patch())
        assert set(patched["algos"]) <= set(D.ALL_DL_ALGOS), profile.key
        for suffix in ("name", "desc"):
            entry = i18n.STRINGS[f"prof_{profile.key}_{suffix}"]
            assert entry["fr"] and entry["en"]


def test_a_profile_prefills_the_form_and_the_gallery_links_stay_on_the_dl_page(client):
    html = client.get("/dl").text
    assert 'href="/dl?profile=dl_quick"' in html and '/ml?profile' not in html
    quick = client.get("/dl?profile=dl_quick").text
    assert 'name="dl_epochs" step="1" min="1" max="500" value="15"' in quick
    assert not re.search(r'name="algos" value="GRU"\s+checked', quick) and re.search(r'name="algos" value="MLP"\s+checked', quick)
    assert client.get("/dl?profile=nope").status_code == 404
    assert client.get("/dl?profile=quick").status_code == 404           # un profil de machine learning n'existe pas ici
    assert client.get("/ml?profile=dl_quick").status_code == 404


def test_the_retraining_advisor_is_a_machine_learning_feature(client):
    assert client.get("/dl?run_id=r1&suggest=fix_leak").status_code in (404, 303)


# --------------------------------------------------------------------------- formulaire -> configuration


def test_a_deep_form_becomes_a_valid_run_config_with_its_deep_block_and_only_its_bounds():
    cfg, errors = forms.build_config_dict(FormData(list(_flat(_form(dl_epochs="12", dl_hidden_size="24", dl_dropout="0,3",
                                                                    dl_lookback="15", dl_device="cpu")))), target_symbol="^VIX", name="dl_1")
    assert errors == []
    run = RunConfig.model_validate(cfg)
    assert run.family == "dl" and run.models.algos == ["MLP", "GRU"]
    assert run.models.deep.epochs == 12 and run.models.deep.hidden_size == 24 and run.models.deep.dropout == 0.3
    assert run.models.deep.lookback == 15 and run.models.deep.device == "cpu"
    assert set(run.tuning.optuna_bounds) >= {"MLP", "GRU", "XGBoost"} and "LSTM" not in run.tuning.optuna_bounds


def test_a_machine_learning_form_has_no_deep_block_and_no_network_bounds():
    cfg, errors = forms.build_config_dict(FormData(list(_flat(_form(family="ml", algos=["XGBoost"], sampler_candidates=["SMOTE"])))),
                                          target_symbol="^VIX", name="ml_1")
    assert errors == [] and "deep" not in cfg["models"]
    assert not set(D.ALL_DL_ALGOS) & set(cfg["tuning"]["optuna_bounds"])


@pytest.mark.parametrize("field, value, message", [
    ("dl_hidden_size", "2", "Taille cachée"), ("dl_dropout", "0.95", "Dropout"), ("dl_epochs", "abc", "Époques maximum"),
    ("dl_learning_rate", "5", "Taux d'apprentissage"), ("dl_device", "tpu", "Appareil de calcul"),
    ("dl_class_weight", "heavy", "Pondération des classes"), ("dl_lookback", "1", "Fenêtre (lookback)"),
])
def test_invalid_network_settings_are_reported_by_name_and_fall_back_to_their_default(field, value, message):
    cfg, errors = forms.build_config_dict(FormData(list(_flat(_form(**{field: value})))), target_symbol="^VIX", name="dl_1")
    assert any(message in e for e in errors), errors
    assert cfg["models"]["deep"][field[3:]] == D.DEFAULT_DEEP[field[3:]]


def test_a_window_model_with_an_oversampler_is_rejected_at_validation():
    cfg, errors = forms.build_config_dict(FormData(list(_flat(_form(algos=["GRU"], sampler_candidates=["SMOTE"])))), target_symbol="^VIX", name="dl_1")
    assert errors == []
    with pytest.raises(Exception, match="sampler"):
        RunConfig.model_validate(cfg)


def test_a_saved_deep_config_reloads_into_the_same_form_values():
    cfg, _ = forms.build_config_dict(FormData(list(_flat(_form(dl_epochs="9", dl_n_seeds="2")))), target_symbol="^VIX", name="dl_1")
    view = forms.to_view(RunConfig.model_validate(cfg).model_dump())
    assert view["dl_epochs"] == 9 and view["dl_n_seeds"] == 2 and view["algos"] == ["MLP", "GRU"]
    assert forms.to_view(forms.default_config_dict("ml"))["dl_epochs"] == D.DEFAULT_DEEP["epochs"]


def _flat(d):
    for k, v in d.items():
        if isinstance(v, list):
            for item in v:
                yield k, item
        else:
            yield k, v


# --------------------------------------------------------------------------- lancement


def test_launching_networks_without_torch_is_refused_with_a_clear_message(client, monkeypatch):
    monkeypatch.setattr(deep_models, "torch_available", lambda: False)
    monkeypatch.setattr(run_manager, "start_run", lambda cfg: pytest.fail("aucun run ne doit être mis en file"))
    resp = client.post("/runs", data=_form())
    assert resp.status_code == 400 and "PyTorch" in resp.json()["errors"][0]


def test_launching_networks_enqueues_one_job_per_target_with_the_deep_block(client, monkeypatch):
    seen = []

    def fake_start(config):
        seen.append(config)
        return {"id": f"job{len(seen)}", "status": "queued", "queue_position": len(seen)}

    monkeypatch.setattr(run_manager, "start_run", fake_start)
    monkeypatch.setattr(run_manager, "next_run_name", lambda sym: f"{forms.slug_target(sym)}_1")
    resp = client.post("/runs", data=_form(target_symbols=["^VIX", "^GSPC"], dl_epochs="11"))
    assert resp.status_code == 200, resp.text
    assert len(seen) == 2 and all(c.family == "dl" and c.models.deep.epochs == 11 for c in seen)


def test_a_window_model_with_smote_is_a_readable_400_not_a_crash(client, monkeypatch):
    monkeypatch.setattr(run_manager, "start_run", lambda cfg: pytest.fail("rien en file"))
    resp = client.post("/runs", data=_form(algos=["LSTM"], sampler_candidates=["SMOTE"]))
    assert resp.status_code == 400 and "sampler" in " ".join(resp.json()["errors"])


def test_reopening_a_run_lands_on_the_page_of_its_family(client, monkeypatch):
    cfg, _ = forms.build_config_dict(FormData(list(_flat(_form()))), target_symbol="^VIX", name="dl_1")
    run = RunConfig.model_validate(cfg)
    monkeypatch.setattr(run_manager, "get_run_config", lambda run_id: run)
    resp = client.get("/ml?run_id=abc&target=^VIX", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/dl?run_id=abc&target=%5EVIX"
    reopened = client.get("/dl?run_id=abc").text
    assert 'name="dl_epochs"' in reopened and 'name="algos" value="GRU"' in reopened
