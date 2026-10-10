"""Page /rl (cadrage du reinforcement learning), formulaire -> `RLRunConfig`, lancement, liste et lecture des runs RL. Vraies routes FastAPI
et vrais gabarits ; aucun worker n'est lancé (`run_manager.start_run` est remplacé) et aucun entraînement n'a lieu."""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.config import rl_profiles
from patrick.data.sources import fundamentals_source
from patrick.rl import agents
from patrick.rl.config import RLRunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.validation import equity_sufficiency
from patrick.webapp import forms, forms_rl, i18n, rl_routes, run_manager
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
    base = {"target_symbols": ["^GSPC"], "families": ["technical", "spike"], "start_date": "2010-01-01", "seed": "42", "output_dir": "",
            "rl_algo": "PPO", "rl_action_space": "discrete", "rl_reward": "log", "rl_cost_bps": "5", "rl_total_timesteps": "5000",
            "rl_n_folds": "3", "rl_allow_short": "on", "rl_include_position": "on", "rl_random_start": "on"}
    base.update(over)
    return base


def _flat(d):
    for k, v in d.items():
        if isinstance(v, list):
            for item in v:
                yield k, item
        else:
            yield k, v


# --------------------------------------------------------------------------- page


def test_the_page_offers_listed_targets_only_and_every_setting(client):
    html = client.get("/rl").text
    assert "Reinforcement learning" in html and 'id="rl-form" data-mode="simple"' in html
    assert 'value="^GSPC"' in html and 'value="EURUSD=X"' in html
    assert 'value="CPIAUCSL"' not in html and 'value="DGS10"' not in html            # pas de série macro : aucune position possible
    for key in D.DEFAULT_RL:
        assert f'name="rl_{key}"' in html, key
    for fam in D.RL_FEATURE_FAMILIES:
        assert f'name="families" value="{fam}"' in html


def test_the_simple_view_keeps_the_agent_essentials_visible_and_folds_the_rest(client):
    html = client.get("/rl").text
    agent = html.index("<legend>Agent")
    block = html[agent:html.index("</fieldset>", agent)]
    for key in ("algo", "action_space", "reward", "cost_bps", "total_timesteps", "n_folds", "allow_short"):
        assert f'name="rl_{key}"' in block, key
    assert 'class="adv"' not in block
    for group in ("env", "features", "policy", "learning", "validation", "compute"):
        assert f'data-adv="rl_{group}"' in html
    assert 'name="rl_policy_units"' in html[html.index('data-adv="rl_policy"'):]


def test_algorithm_specific_settings_are_tagged_for_the_form_to_hide_the_others(client):
    html = client.get("/rl").text
    assert re.search(r'<label data-algos="PPO"[^>]*>[^<]*(?:<[^>]+>[^<]*)*?<select|<label data-algos="PPO"', html)
    assert 'data-algos="DQN"' in html and 'data-algos="SAC"' in html and 'data-algos="PPO,A2C"' in html
    assert 'data-actions="discrete"' in html


def test_defaults_match_the_engine_defaults(client):
    html = client.get("/rl").text
    assert re.search(r'name="rl_algo".*?<option value="PPO" selected', html, re.DOTALL)
    assert 'name="rl_total_timesteps"' in html and 'value="30000"' in html and 'value="4"' in html
    assert re.search(r'name="rl_allow_short"\s+checked', html)


def test_the_glossary_explains_the_algorithms_and_the_settings(client):
    html = client.get("/rl").text
    for term in ("PPO", "rl_agent", "rl_reward", "rl_cost", "rl_timesteps", "rl_walkforward", "rl_gamma", "rl_seeds", "rl_policy"):
        assert f'data-term="{term}"' in html, term
    from patrick.webapp.glossary import GLOSSARY, TERM_LABEL_KEYS
    for term in rl_routes.FIELD_TERMS.values():
        if term in GLOSSARY:
            assert GLOSSARY[term]["fr"] and GLOSSARY[term]["en"]
    assert all(v in i18n.STRINGS for v in TERM_LABEL_KEYS.values())
    assert set(rl_routes.FIELD_TERMS.values()) - {"rl_turnover"} <= set(GLOSSARY)


def test_without_the_extras_the_page_warns_and_disables_the_launch_button(client, monkeypatch):
    monkeypatch.setattr(agents, "rl_available", lambda: False)
    monkeypatch.setattr(agents, "require_rl", lambda: (_ for _ in ()).throw(agents.RLUnavailableError("torch non installé")))
    html = client.get("/rl").text
    assert "torch non installé" in html and re.search(r'id="rl-launch"\s+disabled', html)
    assert client.post("/api/rl/runs", data=_form()).status_code == 400


def test_english_page_leaks_no_translation_key(client):
    client.cookies.set(i18n.LANG_COOKIE, "en")
    visible = re.sub(r"<script.*?</script>", "", client.get("/rl").text, flags=re.DOTALL)
    assert "Averaged agents" in visible
    stripped = re.sub(r'(name|data-term|data-adv|id|for|value|href|data-algos|data-actions)="[^"]*"', "", visible)
    assert not re.search(r"\b(rlp|exp|dl)_[a-z_]+\b", stripped)


# --------------------------------------------------------------------------- profils


def test_every_profile_patches_only_known_fields_and_builds_a_valid_config():
    base = forms_rl.to_view_rl(forms_rl.default_rl_config_dict())
    assert len(rl_profiles.PROFILES) >= 8
    for profile in rl_profiles.PROFILES:
        view = rl_profiles.apply_patch(base, profile.patch)
        form = FormData(list(_flat({"target_symbols": ["^GSPC"], "families": view["families"], "start_date": view["start_date"], "seed": "42",
                                    **{k: ("on" if v is True else str(v)) for k, v in view.items() if k.startswith("rl_") and v is not False}})))
        cfg, errors = forms_rl.build_rl_config_dict(form, target_symbol="^GSPC", name="p_1")
        assert errors == [], (profile.key, errors)
        RLRunConfig.model_validate(cfg)
        for suffix in ("name", "desc"):
            entry = i18n.STRINGS[f"prof_{profile.key}_{suffix}"]
            assert entry["fr"] and entry["en"]


def test_a_profile_prefills_the_form_and_the_gallery_stays_on_the_rl_page(client):
    html = client.get("/rl").text
    assert 'href="/rl?profile=rl_quick"' in html
    quick = client.get("/rl?profile=rl_quick").text
    assert re.search(r'name="rl_total_timesteps"[^>]*value="10000"', quick) and re.search(r'name="rl_n_folds"[^>]*value="3"', quick)
    sac = client.get("/rl?profile=rl_continuous").text
    assert re.search(r'<option value="SAC" selected', sac) and re.search(r'<option value="continuous" selected', sac)
    assert client.get("/rl?profile=nope").status_code == 404 and client.get("/rl?profile=quick").status_code == 404
    assert client.get("/ml?profile=rl_quick").status_code == 404


# --------------------------------------------------------------------------- formulaire -> configuration


def test_a_form_becomes_a_valid_rl_config():
    cfg, errors = forms_rl.build_rl_config_dict(FormData(list(_flat(_form(rl_n_levels="5", rl_gamma="0,95")))), target_symbol="^GSPC", name="g_rl_1")
    assert errors == []
    run = RLRunConfig.model_validate(cfg)
    assert run.kind == "rl" and run.name == "g_rl_1" and run.rl.n_levels == 5 and run.rl.gamma == 0.95 and run.rl.allow_short is True
    assert run.feature_families() == ["technical", "spike"] and run.universe.start_date == "2010-01-01"
    assert run.objective.target_symbol == "^GSPC" and "^GSPC" not in run.universe.yf_tickers
    assert run.output.dir == "runs/g_rl_1" and run.output.seed == 42       # dossier de sortie vide -> runs/<nom>


def test_without_the_macro_family_no_fred_series_is_downloaded():
    cfg, _ = forms_rl.build_rl_config_dict(FormData([("families", "technical"), ("families", "spike")]), target_symbol="^GSPC", name="x")
    assert cfg["universe"]["fred_series"] == {} and cfg["universe"]["yf_tickers"]
    cfg, _ = forms_rl.build_rl_config_dict(FormData([("families", "technical"), ("families", "macro")]), target_symbol="^GSPC", name="x")
    assert len(cfg["universe"]["fred_series"]) > 10


def test_unchecked_boxes_mean_false_and_missing_fields_take_their_defaults():
    cfg, errors = forms_rl.build_rl_config_dict(FormData([("families", "technical")]), target_symbol="^GSPC", name="x")
    assert errors == []
    assert cfg["rl"]["allow_short"] is False and cfg["rl"]["include_position"] is False and cfg["rl"]["random_start"] is False
    assert cfg["rl"]["total_timesteps"] == D.DEFAULT_RL["total_timesteps"] and cfg["rl"]["algo"] == "PPO"


@pytest.mark.parametrize("field, value, message", [
    ("rl_cost_bps", "-3", "Frais"), ("rl_gamma", "1.5", "gamma"), ("rl_total_timesteps", "abc", "Pas d'entraînement"),
    ("rl_algo", "TD3", "Algorithme"), ("rl_action_space", "mixed", "Espace d'actions"), ("rl_n_folds", "0", "Plis"),
    ("rl_max_leverage", "99", "Levier"), ("rl_retrain", "never", "Fenêtre"),
])
def test_invalid_settings_are_reported_by_name_and_fall_back_to_their_default(field, value, message):
    cfg, errors = forms_rl.build_rl_config_dict(FormData(list(_flat(_form(**{field: value})))), target_symbol="^GSPC", name="x")
    assert any(message in e for e in errors), errors
    assert cfg["rl"][field[3:]] == D.DEFAULT_RL[field[3:]]


def test_a_macro_series_and_an_empty_family_list_are_refused():
    _, errors = forms_rl.build_rl_config_dict(FormData(list(_flat(_form()))), target_symbol="CPIAUCSL", name="x")
    assert any("FRED" in e for e in errors)
    _, errors = forms_rl.build_rl_config_dict(FormData(list(_flat(_form(families=["vol_models"])))), target_symbol="^GSPC", name="x")
    assert any("Familles" in e for e in errors)


def test_incompatible_algorithm_and_action_space_are_a_validation_error_not_a_crash(client, monkeypatch):
    monkeypatch.setattr(agents, "rl_available", lambda: True)
    monkeypatch.setattr(run_manager, "start_run", lambda cfg: pytest.fail("rien en file"))
    resp = client.post("/api/rl/runs", data=_form(rl_algo="DQN", rl_action_space="continuous"))
    assert resp.status_code == 400 and "DQN" in " ".join(resp.json()["errors"])


# --------------------------------------------------------------------------- lancement et lecture


def test_launching_enqueues_one_rl_job_per_target_with_distinct_names(client, monkeypatch):
    monkeypatch.setattr(agents, "rl_available", lambda: True)
    seen = []

    def fake_start(config):
        seen.append(config)
        conn = trackdb.connect(str(trackdb.default_db_path()))
        try:
            job_id = jobs_db.enqueue_job(conn, config.model_dump_json())
        finally:
            conn.close()
        return {"id": job_id, "status": "queued", "queue_position": len(seen)}

    monkeypatch.setattr(run_manager, "start_run", fake_start)
    resp = client.post("/api/rl/runs", data=_form(target_symbols=["^GSPC", "EURUSD=X"]))
    assert resp.status_code == 200, resp.text
    runs = resp.json()["runs"]
    assert [r["target"] for r in runs] == ["^GSPC", "EURUSD=X"] and len({r["name"] for r in runs}) == 2
    assert all(isinstance(c, RLRunConfig) and c.kind == "rl" for c in seen)
    again = client.post("/api/rl/runs", data=_form())
    assert again.json()["runs"][0]["name"] == "GSPC_rl_2"                       # le numéro suit les runs RL déjà créés
    assert client.post("/api/rl/runs", data={"rl_algo": "PPO"}).status_code == 400            # aucune cible


def test_the_list_shows_rl_jobs_only_with_their_key_numbers_once_done(client):
    conn = trackdb.connect(str(trackdb.default_db_path()))
    cfg = RLRunConfig.model_validate({"name": "a_rl_1", "objective": {"target_symbol": "^GSPC"}})
    done = jobs_db.enqueue_job(conn, cfg.model_dump_json())
    jobs_db.enqueue_job(conn, '{"name": "ml_job", "objective": {"target_symbol": "^GSPC"}}')           # un job ML : exclu
    claimed = jobs_db.claim_next_job(conn, 123)
    jobs_db.finish_job(conn, claimed["job_id"], "done", result_json=json.dumps(
        {"strategy": {"sharpe": 0.8, "total_return": 0.2, "max_drawdown": -0.1}, "baselines": {"buy_hold": {"sharpe": 0.5}}}))
    conn.close()
    runs = client.get("/api/rl/runs").json()["runs"]
    assert [r["name"] for r in runs] == ["a_rl_1"] and runs[0]["status"] == "done"
    assert runs[0]["sharpe"] == 0.8 and runs[0]["sharpe_buy_hold"] == 0.5 and runs[0]["run_id"] == done


def test_an_rl_job_opens_on_the_rl_page_and_never_on_the_ml_page(client):
    conn = trackdb.connect(str(trackdb.default_db_path()))
    cfg = RLRunConfig.model_validate({"name": "b_rl_1", "objective": {"target_symbol": "^GSPC"}, "rl": {"algo": "A2C", "n_folds": 2}})
    job_id = jobs_db.enqueue_job(conn, cfg.model_dump_json())
    conn.close()
    assert client.get(f"/runs/{job_id}", follow_redirects=False).headers["location"] == f"/rl?open={job_id}"
    page = client.get(f"/rl?open={job_id}").text
    assert f'data-initial-run="{job_id}"' in page and re.search(r'<option value="A2C" selected', page)
    reuse = client.get(f"/rl?run_id={job_id}").text
    assert 'data-initial-run=""' in reuse and re.search(r'<option value="A2C" selected', reuse)
    assert client.get("/rl?open=nope").status_code == 404
    assert run_manager.get_run_kind(job_id) == "rl" and run_manager.get_run_config(job_id) is None


def test_a_machine_learning_job_opened_on_rl_is_sent_to_its_own_page(client):
    conn = trackdb.connect(str(trackdb.default_db_path()))
    job_id = jobs_db.enqueue_job(conn, forms.default_config_dict.__module__ and json.dumps(
        {"name": "m", "objective": {"target_symbol": "^GSPC"}, "models": {"algos": ["MLP"], "deep": {}}, "sampler": {"candidates": ["none"]}}))
    conn.close()
    resp = client.get(f"/rl?run_id={job_id}", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == f"/dl?run_id={job_id}"


def test_rl_names_never_collide_with_each_other_or_with_ml_names():
    conn = trackdb.connect(str(trackdb.default_db_path()))
    for i in (1, 2):
        jobs_db.enqueue_job(conn, RLRunConfig.model_validate({"name": f"GSPC_rl_{i}", "objective": {"target_symbol": "^GSPC"}}).model_dump_json())
    conn.close()
    assert run_manager.next_rl_run_name("^GSPC") == "GSPC_rl_3" and run_manager.next_rl_run_name("EURUSD=X") == "EURUSD_X_rl_1"
