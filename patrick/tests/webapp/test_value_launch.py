"""Lancement des modèles de valeur exacte (ADR 0032) : lots prêts à lancer comptés par objectif, profils de valeur exacte et profils
« max » (ML, DL, RL), galerie groupée par objectif. Les profils sont validés par le chemin du formulaire : un profil que la page refuserait
à la soumission (comme « robust » avant le 2026-11-27) est un échec ici."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from patrick.config import dl_profiles, rl_profiles, training_profiles
from patrick.config.schema import RunConfig
from patrick.tracking import db
from patrick.tracking import jobs as jobs_db
from patrick.webapp import forms, forms_rl, launch_batches, run_manager
from patrick.webapp.app import app

TODAY = date(2026, 11, 27)


def _cfg(target: str, horizons=(1,), algos=("XGBoost", "LightGBM"), task: str = "direction") -> dict:
    cfg = forms.default_config_dict()
    cfg["objective"].update(target_symbol=target, horizons=list(horizons))
    if task == "value":
        cfg["objective"]["task"] = "value"
        cfg["selection"]["criterion"] = "IC"
        cfg["sampler"]["candidates"] = ["none"]
    cfg["models"]["algos"] = list(algos)
    return cfg


def _add_run(conn, run_id: str, symbol: str, horizon: int, algos=("XGBoost", "LightGBM"), task: str = "direction") -> None:
    label = f"{symbol}__val" if task == "value" else symbol
    db.create_run(conn, run_id, label, horizon, "snap", json.dumps(_cfg(symbol, (horizon,), algos, task)), "c", "s", 42)
    db.finish_run(conn, run_id, status="done", n_trials=1)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    connection = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(connection, "snap", "h", None, None, None)
    yield connection
    connection.close()


@pytest.fixture
def client(conn):
    return TestClient(app, base_url="http://127.0.0.1:8000")


# --------------------------------------------------------------------------- ce qui compte comme « fait », par objectif


def test_a_value_run_counts_for_the_value_objective_only(conn):
    _add_run(conn, "d1", "^GSPC", 1)
    _add_run(conn, "v5", "^GSPC", 5, task="value")
    assert launch_batches.executed_pairs(conn, "ml") == {"^GSPC": {1}}
    assert launch_batches.executed_pairs(conn, "ml", "value") == {"^GSPC": {5}}          # clé : le symbole, pas `^GSPC__val`


def test_a_queued_value_job_does_not_cover_the_direction_of_its_target(conn):
    jobs_db.enqueue_job(conn, json.dumps(_cfg("^VIX", horizons=(1, 2), task="value")))
    assert launch_batches.executed_pairs(conn, "ml") == {}
    assert launch_batches.executed_pairs(conn, "ml", "value") == {"^VIX": {1, 2}}
    assert launch_batches.pending_targets(conn, "ml") == set()
    assert launch_batches.pending_targets(conn, "ml", "value") == {"^VIX"}
    assert launch_batches.pending_pairs(conn) == {"^VIX__val": {1, 2}}                  # « À faire » : la direction de ^VIX reste relançable


def test_value_overview_says_which_targets_were_only_tried_by_the_other_family(conn):
    _add_run(conn, "n1", "^GSPC", 5, algos=("MLP",), task="value")                       # des réseaux, jamais d'arbres
    _add_run(conn, "t1", "GC=F", 5, task="value")
    ml = launch_batches.overview(conn, "ml", ["^GSPC", "GC=F", "^VIX"], {}, TODAY, task="value")
    assert ml["never"] == ["^GSPC", "^VIX"] and ml["cross"] == ["^GSPC"]
    assert ml["missing"] == {"GC=F": [1, 2, 3, 7, 10]}
    dl = launch_batches.overview(conn, "dl", ["^GSPC", "GC=F", "^VIX"], {}, TODAY, task="value")
    assert dl["cross"] == ["GC=F"]
    assert "cross" not in launch_batches.overview(conn, "ml", ["^GSPC"], {}, TODAY)      # la direction n'a pas ce lot


def test_value_where_signal_keeps_the_most_predictable_targets_without_a_value_model(conn, monkeypatch):
    monkeypatch.setattr(launch_batches, "top_signal", lambda c, cands, n=50: [s for s in ("^VIX", "GC=F", "^GSPC") if s in cands][:n])
    assert launch_batches.value_where_signal(conn, ["^GSPC", "GC=F", "^VIX"], never_value=["^GSPC", "^VIX"]) == ["^VIX", "^GSPC"]


def test_a_finished_value_run_no_longer_breaks_the_home_summary_and_has_its_own_column(conn):
    """Avant le 2026-11-27, `home_summary` levait KeyError('value') : l'instantané de l'accueil ne se rafraîchissait plus."""
    from patrick.tracking import class_overview, home

    _add_run(conn, "d1", "^GSPC", 1)
    _add_run(conn, "v1", "^GSPC", 5, task="value")
    out = home.home_summary(conn, forms.TARGET_GROUPS)
    assert out["kinds"]["value"]["n"] == 1 and out["kinds"]["directional"]["n"] == 1
    stats = class_overview.model_stats_by_asset(conn)["^GSPC"]
    assert stats["directional"]["n"] == 1 and stats["value"]["n"] == 1


# --------------------------------------------------------------------------- le fragment et la soumission


def test_the_fragment_adds_value_cards_that_switch_the_form_objective(client, conn):
    _add_run(conn, "d1", "^VIX", 1)
    _add_run(conn, "v1", "^VIX", 1, task="value")
    ml = client.get("/fragments/launch-batches?family=ml").text
    assert 'data-task="direction"' in ml and 'data-task="value"' in ml
    value_part = ml.split('batch-grid-value')[1]
    gaps = json.loads(value_part.split("data-gaps='")[1].split("'")[0])
    assert gaps["^VIX"] == [2, 3, 5, 7, 10]
    assert "Valeur exacte" in ml and "sans valeur exacte" in ml
    rl = client.get("/fragments/launch-batches?family=rl").text
    assert 'data-task="value"' not in rl                                                # le RL n'a pas cet objectif


@pytest.fixture
def seen(monkeypatch):
    configs: list[RunConfig] = []

    def fake_start(config):
        configs.append(config)
        return {"id": f"job{len(configs)}", "status": "queued", "queue_position": len(configs)}

    monkeypatch.setattr(run_manager, "start_run", fake_start)
    monkeypatch.setattr(run_manager, "next_run_name", lambda sym: f"{forms.slug_target(sym)}_1")
    return configs


def _post(**over) -> dict:
    base = {
        "family": "ml", "target_symbols": ["^GSPC", "^VIX"], "horizons": ["1", "5"], "regimes": "GLOBAL", "flat_thr": "0.003",
        "families": ["technical", "spike"], "vol_models": ["egarch"], "n_features_grid": "8,12", "sampler_candidates": ["none"],
        "algos": ["XGBoost", "LightGBM"], "selection_method": "shap", "n_wf_folds": "3", "tuning_enabled": "on", "n_trials": "10",
        "top_k": "1", "cv_splits": "3", "seed": "42", "min_history_years": "5", "output_dir": "",
    }
    base.update(over)
    return base


def test_only_missing_reads_the_pairs_of_the_submitted_objective(client, conn, seen):
    _add_run(conn, "d1", "^GSPC", 1)
    _add_run(conn, "d5", "^GSPC", 5)                                                     # la direction de ^GSPC est complète...
    _add_run(conn, "v1", "^VIX", 1, task="value")
    resp = client.post("/runs", data=_post(only_missing="1", task="value", value_criterion="IC"))
    assert resp.status_code == 200
    # ... mais pas sa valeur exacte ; ^VIX a déjà sa valeur exacte à 1 jour
    assert {c.objective.target_symbol: c.objective.horizons for c in seen} == {"^GSPC": [1, 5], "^VIX": [5]}
    assert all(c.objective.task == "value" for c in seen)


# --------------------------------------------------------------------------- profils


def _built(family: str, profile) -> RunConfig:
    module = dl_profiles if family == "dl" else training_profiles
    view = module.apply_patch(forms.to_view(forms.default_config_dict(family)), profile.resolved_patch())
    cfg, errors = forms.build_config_dict(forms.FormFromView(view), target_symbol="^GSPC", name="chk")
    assert errors == [], (profile.key, errors)
    return RunConfig.model_validate(cfg)


@pytest.mark.parametrize("family,key", [("ml", p.key) for p in training_profiles.PROFILES] + [("dl", p.key) for p in dl_profiles.PROFILES])
def test_every_shipped_profile_is_accepted_by_the_form_with_its_objective(family, key):
    profile = (dl_profiles if family == "dl" else training_profiles).get(key)
    config = _built(family, profile)
    assert config.objective.task == profile.task
    assert config.family == family
    if profile.task == "value":
        assert config.sampler.candidates == ["none"] and not config.models.stacking and config.validation.scheme == "walkforward"


def test_each_family_has_a_max_profile_and_value_has_its_own():
    assert {"max", "value_max"} <= set(training_profiles.BY_KEY)
    assert {"dl_max", "dl_value_max"} <= set(dl_profiles.BY_KEY)
    assert "rl_max" in rl_profiles.BY_KEY
    for p in (training_profiles.get("max"), training_profiles.get("value_max"), dl_profiles.get("dl_max"), dl_profiles.get("dl_value_max"),
              rl_profiles.get("rl_max")):
        assert p.cost == "max" and "prof_warn_max" in p.warnings


def test_the_max_profiles_search_wider_than_the_deepest_ones():
    ml_max, deep = _built("ml", training_profiles.get("max")), _built("ml", training_profiles.get("deep"))
    assert ml_max.tuning.n_trials > deep.tuning.n_trials and ml_max.models.stacking_n_models >= deep.models.stacking_n_models
    assert max(ml_max.selection.n_features_grid) > max(deep.selection.n_features_grid)
    assert ml_max.validation.n_wf_folds > deep.validation.n_wf_folds and ml_max.models.algos == deep.models.algos
    value_max = _built("ml", training_profiles.get("value_max"))
    assert value_max.objective.task == "value" and value_max.tuning.n_trials == ml_max.tuning.n_trials


def test_the_rl_max_profile_is_accepted_by_the_rl_form():
    view = rl_profiles.apply_patch(forms_rl.to_view_rl(forms_rl.default_rl_config_dict()), rl_profiles.get("rl_max").patch)

    class Form(dict):
        def getlist(self, k):
            v = self.get(k)
            return list(v) if isinstance(v, (list, tuple)) else ([] if v is None else [v])

    flat = Form({k: (("on" if v else None) if isinstance(v, bool) else v) for k, v in view.items()})
    cfg, errors = forms_rl.build_rl_config_dict(flat, target_symbol="^GSPC", name="chk")
    assert errors == []
    assert cfg["rl"]["total_timesteps"] == 200000 and cfg["rl"]["n_seeds"] == 5


def test_identify_never_gives_a_direction_profile_to_a_value_run():
    default_view = forms.to_view(forms.default_config_dict("ml"))
    value_default = {**default_view, "task": "value", "value_criterion": "IC", "calibration": False}
    assert training_profiles.identify(value_default, default_view) == "value_standard"
    quick_but_value = training_profiles.apply_patch(default_view, {**training_profiles.get("quick").resolved_patch(), "task": "value"})
    assert training_profiles.identify(quick_but_value, default_view) != "quick"


def test_the_gallery_groups_profiles_by_objective_and_a_value_profile_prefills_the_objective(client):
    html = client.get("/ml").text
    assert "prof_group" not in html                                                        # titres de groupe traduits
    assert "Valeur exacte" in html and 'href="/ml?profile=value_quick"' in html and 'href="/ml?profile=max"' in html
    page = client.get("/ml?profile=value_quick").text
    assert '<option value="value" selected>' in page
    assert "walk-forward" in page                                                          # avertissement de la valeur exacte
    dl = client.get("/dl").text
    assert 'href="/dl?profile=dl_value_quick"' in dl and 'href="/dl?profile=dl_max"' in dl
    assert "très long" in client.get("/rl").text                                           # coût du profil rl_max
