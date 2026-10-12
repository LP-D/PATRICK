"""Lots prêts à lancer des pages Modèles (`webapp/launch_batches.py`, `/fragments/launch-batches`, `POST /runs` avec `only_missing`,
`/api/launch-batches/recommended`) : ce qui compte comme « fait », les trois lots, et l'équivalence entre un lot lancé côté serveur et
le formulaire pré-rempli que l'utilisateur soumettrait lui-même."""
from __future__ import annotations

import json
from datetime import date
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.config import dl_profiles, training_profiles
from patrick.config.schema import RunConfig
from patrick.tracking import db
from patrick.tracking import jobs as jobs_db
from patrick.webapp import forms, launch_batches, run_manager
from patrick.webapp.app import app

TODAY = date(2026, 10, 11)


def _cfg(target: str, horizons=(1,), algos=("XGBoost", "LightGBM")) -> dict:
    cfg = forms.default_config_dict()
    cfg["objective"].update(target_symbol=target, horizons=list(horizons))
    cfg["models"]["algos"] = list(algos)
    return cfg


def _add_run(conn, run_id: str, target: str, horizon: int, status: str, algos=("XGBoost", "LightGBM")) -> None:
    db.create_run(conn, run_id, target, horizon, "snap", json.dumps(_cfg(target, (horizon,), algos)), "c", "s", 42)
    if status != "running":
        db.finish_run(conn, run_id, status=status, n_trials=1)


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


# --------------------------------------------------------------------------- ce qui compte comme « fait »


def test_the_family_follows_the_algorithms():
    assert launch_batches.config_family(_cfg("^VIX", algos=("MLP", "GRU"))) == "dl"
    assert launch_batches.config_family(_cfg("^VIX", algos=("MLP", "XGBoost"))) == "ml"
    assert launch_batches.config_family({}) == "ml"


def test_done_running_and_pending_runs_count_but_failed_runs_do_not(conn):
    _add_run(conn, "a1", "^GSPC", 1, "done")
    _add_run(conn, "a2", "^GSPC", 5, "running")
    _add_run(conn, "a3", "^GSPC", 10, "failed")
    jobs_db.enqueue_job(conn, json.dumps(_cfg("^VIX", horizons=(1, 2))))
    assert launch_batches.executed_pairs(conn, "ml") == {"^GSPC": {1, 5}, "^VIX": {1, 2}}


def test_machine_learning_and_deep_learning_are_counted_apart(conn):
    _add_run(conn, "m1", "^GSPC", 1, "done")
    _add_run(conn, "d1", "^VIX", 1, "done", algos=("MLP",))
    assert launch_batches.executed_pairs(conn, "ml") == {"^GSPC": {1}}
    assert launch_batches.executed_pairs(conn, "dl") == {"^VIX": {1}}


def test_alpha_runs_and_reinforcement_jobs_are_not_classification_runs(conn):
    _add_run(conn, "al", "AAPL__alpha_^GSPC", 1, "done")
    jobs_db.enqueue_job(conn, json.dumps({"kind": "rl", "objective": {"target_symbol": "AAPL"}}, separators=(",", ":")))
    assert launch_batches.executed_pairs(conn, "ml") == {}


def test_reinforcement_targets_ignore_failed_and_deleted_runs(conn):
    def rl_job(symbol: str) -> str:
        return jobs_db.enqueue_job(conn, json.dumps({"kind": "rl", "objective": {"target_symbol": symbol}}, separators=(",", ":")))
    rl_job("AAPL")
    failed, deleted = rl_job("MSFT"), rl_job("NVDA")
    conn.execute("UPDATE job SET status = 'error' WHERE job_id = ?", (failed,))
    conn.execute("UPDATE job SET phase = 'deleted' WHERE job_id = ?", (deleted,))
    conn.commit()
    assert launch_batches.rl_executed_targets(conn) == {"AAPL"}


# --------------------------------------------------------------------------- les lots


def test_never_run_targets_and_missing_default_horizons(conn):
    for h in (1, 2, 3, 5, 7, 10):
        _add_run(conn, f"full{h}", "^GSPC", h, "done")
    _add_run(conn, "part", "^VIX", 1, "done")
    out = launch_batches.overview(conn, "ml", ["^GSPC", "^VIX", "GC=F"], {}, TODAY)
    assert out["never"] == ["GC=F"]                                       # aucun run
    assert out["missing"] == {"^VIX": [2, 3, 5, 7, 10]}                   # ^GSPC a tout, ^VIX n'a que l'horizon 1


def test_a_pending_job_already_covers_its_pairs(conn):
    jobs_db.enqueue_job(conn, json.dumps(_cfg("^VIX", horizons=D.DEFAULT_HORIZONS)))
    out = launch_batches.overview(conn, "ml", ["^VIX", "GC=F"], {}, TODAY)
    assert out == {"never": ["GC=F"], "missing": {}}


def test_a_target_with_a_known_short_history_is_left_out(conn):
    first_dates = {"NEW": "2022-01-03", "OLD": "2000-01-03"}          # 4,8 ans / 26 ans, seuil 10 ans
    out = launch_batches.overview(conn, "ml", ["NEW", "OLD", "UNKNOWN"], first_dates, TODAY)
    assert out["never"] == ["OLD", "UNKNOWN"]                           # historique inconnu : on ne sait pas, on garde


def test_reinforcement_has_no_horizons(conn):
    jobs_db.enqueue_job(conn, json.dumps({"kind": "rl", "objective": {"target_symbol": "AAPL"}}, separators=(",", ":")))
    _add_run(conn, "ml1", "^GSPC", 1, "done")
    out = launch_batches.overview(conn, "rl", ["AAPL", "^GSPC"], {}, TODAY)
    assert out == {"never": ["^GSPC"], "missing": {}}


# --------------------------------------------------------------------------- le fragment et les pages


def test_the_pages_load_their_batches_after_the_first_paint(client):
    for family in ("ml", "dl", "rl"):
        html = client.get(f"/{family}").text
        assert f'data-lazy-url="/fragments/launch-batches?family={family}"' in html, family
        assert 'id="batch-gallery"' in html and "/static/launch_batches.js" in html
        assert 'data-batch="never"' not in html                          # les cartes n'arrivent qu'avec le fragment


def test_the_fragment_offers_the_lots_of_each_family(client, conn):
    _add_run(conn, "p1", "^VIX", 1, "done")
    ml = client.get("/fragments/launch-batches?family=ml").text
    assert 'data-batch="never"' in ml and 'data-batch="missing"' in ml and 'data-batch="recommended"' in ml
    gaps = json.loads(ml.split("data-gaps='")[1].split("'")[0])
    assert gaps["^VIX"] == [2, 3, 5, 7, 10]
    never = json.loads(ml.split("data-symbols='")[1].split("'")[0])
    assert "^VIX" not in never and "^GSPC" in never
    dl = client.get("/fragments/launch-batches?family=dl").text
    assert 'data-batch="never"' in dl and 'data-batch="missing"' in dl and 'data-batch="recommended"' not in dl
    rl = client.get("/fragments/launch-batches?family=rl").text
    assert 'data-batch="never"' in rl and 'data-batch="missing"' not in rl and 'data-batch="recommended"' not in rl


def test_an_unknown_family_is_a_404(client):
    assert client.get("/fragments/launch-batches?family=xx").status_code == 404


def test_the_fragment_is_translated(client):
    assert "Never-run targets" in client.get("/fragments/launch-batches?family=ml&lang=en").text
    assert "Cibles jamais lancées" in client.get("/fragments/launch-batches?family=ml").text


# --------------------------------------------------------------------------- « horizons jamais lancés » à la soumission


def _post_data(**over) -> dict:
    base = {
        "family": "ml", "target_symbols": ["^GSPC", "^VIX", "GC=F"], "horizons": ["1", "5"], "regimes": "GLOBAL", "flat_thr": "0.003",
        "families": ["technical", "spike"], "vol_models": ["egarch"], "n_features_grid": "8,12", "sampler_candidates": ["none"],
        "algos": ["XGBoost", "LightGBM"], "selection_method": "shap", "n_wf_folds": "3", "tuning_enabled": "on", "n_trials": "10",
        "top_k": "1", "cv_splits": "3", "seed": "42", "min_history_years": "5", "output_dir": "",
    }
    base.update(over)
    return base


@pytest.fixture
def seen(monkeypatch):
    configs: list[RunConfig] = []

    def fake_start(config):
        configs.append(config)
        return {"id": f"job{len(configs)}", "status": "queued", "queue_position": len(configs)}

    monkeypatch.setattr(run_manager, "start_run", fake_start)
    monkeypatch.setattr(run_manager, "next_run_name", lambda sym: f"{forms.slug_target(sym)}_1")
    return configs


def test_without_the_flag_the_form_is_submitted_as_is(client, conn, seen):
    _add_run(conn, "g1", "^GSPC", 1, "done")
    assert client.post("/runs", data=_post_data()).status_code == 200
    assert {c.objective.target_symbol: c.objective.horizons for c in seen} == {"^GSPC": [1, 5], "^VIX": [1, 5], "GC=F": [1, 5]}


def test_only_missing_creates_only_the_pairs_without_a_run(client, conn, seen):
    _add_run(conn, "g1", "^GSPC", 1, "done")
    _add_run(conn, "g5", "^GSPC", 5, "done")
    _add_run(conn, "v1", "^VIX", 1, "done")
    resp = client.post("/runs", data=_post_data(only_missing="1"))
    assert resp.status_code == 200
    assert {c.objective.target_symbol: c.objective.horizons for c in seen} == {"^VIX": [5], "GC=F": [1, 5]}
    assert resp.json()["skipped"] == ["^GSPC"]                            # plus rien à lancer pour elle


def test_only_missing_does_not_touch_the_deep_learning_runs_of_a_target(client, conn, seen):
    _add_run(conn, "d1", "^VIX", 1, "done", algos=("MLP",))                # un run DL ne dispense pas du run ML
    client.post("/runs", data=_post_data(only_missing="1", target_symbols=["^VIX"], horizons=["1"]))
    assert [c.objective.horizons for c in seen] == [[1]]


# --------------------------------------------------------------------------- le formulaire dit côté serveur


class _Scrape(HTMLParser):
    """Ce que le navigateur enverrait en soumettant `#run-form` de la page rendue (cases cochées, listes, premier choix d'un menu)."""

    def __init__(self):
        super().__init__()
        self.in_form, self.pairs, self.select, self.multiple, self.options = False, [], None, False, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == "run-form":
            self.in_form = True
        elif not self.in_form:
            return
        elif tag == "input":
            kind = (a.get("type") or "text").lower()
            sent = a.get("name") and "disabled" not in a and kind not in ("button", "submit", "reset", "file")
            if sent and (kind not in ("checkbox", "radio") or "checked" in a):
                self.pairs.append((a["name"], a.get("value", "on" if kind in ("checkbox", "radio") else "")))
        elif tag == "select":
            self.select, self.multiple, self.options = a.get("name"), "multiple" in a, []
        elif tag == "option" and self.select:
            self.options.append((a.get("value"), "selected" in a))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False
        elif tag == "select" and self.select:
            chosen = [v for v, picked in self.options if picked] or ([] if self.multiple or not self.options else [self.options[0][0]])
            self.pairs.extend((self.select, v) for v in chosen)
            self.select = None


def _scrape(html: str) -> FormData:
    parser = _Scrape()
    parser.feed(html)
    return FormData(parser.pairs)


@pytest.mark.parametrize("url,family,profile", [
    ("/ml", "ml", None), ("/ml?profile=deep", "ml", "deep"), ("/ml?profile=robust", "ml", "robust"),
    ("/ml?profile=regimes", "ml", "regimes"), ("/dl", "dl", None),
])
def test_a_view_said_by_the_server_builds_the_same_config_as_the_rendered_form(client, url, family, profile):
    """Le garde-fou : si le gabarit du formulaire change de nom de champ, `FormFromView` et la page ne disent plus la même chose."""
    view = forms.to_view(forms.default_config_dict(family))
    if profile:
        view = training_profiles.apply_patch(view, (dl_profiles if family == "dl" else training_profiles).get(profile).resolved_patch())
    from_page, _ = forms.build_config_dict(_scrape(client.get(url).text), target_symbol="^VIX", name="cmp")
    from_view, _ = forms.build_config_dict(forms.FormFromView(view), target_symbol="^VIX", name="cmp")
    assert from_view == from_page


def test_every_field_said_by_the_server_exists_in_a_rendered_form(client):
    """Chaque nom de champ que `FormFromView` envoie existe dans la page ML ou DL : le gabarit n'a pas renommé un champ sans que le lot
    le sache (la page ML ne montre pas les réglages des réseaux, la page DL ne montre pas les bornes Optuna des arbres)."""
    names = {n for page in ("/ml", "/dl") for n, _ in _scrape(client.get(page).text).multi_items()}
    said = set(forms.FormFromView(forms.to_view(forms.default_config_dict("dl")))._values)
    assert {n for n in said - names if n not in ("name", "target_symbol")} == set()


def test_a_changed_view_changes_the_submitted_config():
    """Les réglages que la page ne rend qu'en valeur par défaut au test précédent passent bien par le bon nom de champ."""
    view = forms.to_view(forms.default_config_dict())
    view["technical_lookbacks"] = {**view["technical_lookbacks"], "returns_windows": "3,9"}
    view["optuna_bounds"] = {**view["optuna_bounds"], "XGBoost": {**view["optuna_bounds"]["XGBoost"], "max_depth": [4, 6]}}
    view["regime_threshold_values"] = (0.2, 0.7)
    view.update(staged_screening=True, purge=True, holdout_months=18, reduction_corr_threshold=0.8, regimes="GLOBAL,CALM")
    cfg, errors = forms.build_config_dict(forms.FormFromView(view), target_symbol="^VIX", name="cmp")
    assert not errors
    assert cfg["features"]["technical_lookbacks"]["returns_windows"] == [3, 9]
    assert cfg["tuning"]["optuna_bounds"]["XGBoost"]["max_depth"] == [4, 6]
    assert tuple(cfg["validation"]["regime_threshold_values"]) == (0.2, 0.7)
    assert cfg["selection"]["screening_mode"] == "total_window" and cfg["validation"]["purge"] is True
    assert cfg["validation"]["holdout_months"] == 18 and cfg["universe"]["reduction_corr_threshold"] == 0.8
    assert cfg["objective"]["regimes"] == ["GLOBAL", "CALM"]


# --------------------------------------------------------------------------- « runs conseillés »


def _suspect_run(conn, run_id: str = "r1", target: str = "^VIX", horizon: int = 5) -> None:
    """Un run terminé au score trop beau (F1 0,95) : le conseiller propose d'abord de refaire avec la garde anti-fuite."""
    cfg = _cfg(target, (horizon,))
    cfg["name"] = run_id
    db.create_run(conn, run_id, target, horizon, "snap", json.dumps(cfg), "c", "s", 42)
    trial = db.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial)
    for fold, auc in enumerate((0.97, 0.96, 0.98), 1):
        db.add_fold_metrics(conn, trial, fold, "test", {"F1_dir": 0.95, "AUC_ovr_4cls": auc})
    db.finish_run(conn, run_id, status="done", n_trials=1)


def test_the_recommended_lot_takes_the_best_proposal_for_each_target(conn):
    _suspect_run(conn)
    items = launch_batches.recommended(conn, {})
    assert [(i["run_id"], i["target"], i["key"]) for i in items] == [("r1", "^VIX", "fix_leak")]
    assert launch_batches.summarize(items)["by_key"] == {"fix_leak": 1}


def test_a_target_no_longer_in_the_launchable_universe_is_not_recommended(conn):
    """`^EVZ` a d'anciens runs terminés mais n'est plus lançable : le proposer ferait refuser tout le lot à la mise en file."""
    assert "^EVZ" not in forms.TARGET_SOURCE_BY_SYMBOL
    _suspect_run(conn, "old", "^EVZ")
    _suspect_run(conn, "r1", "^VIX")
    items = launch_batches.recommended(conn, {})
    assert [i["target"] for i in items] == ["^VIX"]
    for item in items:
        config, errs = launch_batches.build_recommended_config(conn, item["run_id"], item["key"], {})
        assert config is not None and not errs


def test_a_target_already_in_the_queue_is_not_recommended_again(conn):
    _suspect_run(conn)
    jobs_db.enqueue_job(conn, json.dumps(_cfg("^VIX")))
    assert launch_batches.recommended(conn, {}) == []


def test_the_recommended_config_is_the_one_the_prefilled_form_would_submit(client, conn, monkeypatch):
    _suspect_run(conn)
    monkeypatch.setattr(run_manager, "next_run_name", lambda sym: "cmp")
    page = client.get("/ml?run_id=r1&suggest=fix_leak")
    assert page.status_code == 200
    expected, errors = forms.build_config_dict(_scrape(page.text), target_symbol="^VIX", name="cmp")
    assert not errors
    config, errs = launch_batches.build_recommended_config(conn, "r1", "fix_leak", {})
    assert errs == [] and config.model_dump() == RunConfig.model_validate(expected).model_dump()


def test_a_suggestion_that_is_no_longer_proposed_is_an_error_not_a_launch(conn):
    _suspect_run(conn)
    config, errs = launch_batches.build_recommended_config(conn, "r1", "calibrate", {})
    assert config is None and "calibrate" in errs[0]
    config, errs = launch_batches.build_recommended_config(conn, "nope", "fix_leak", {})
    assert config is None and "introuvable" in errs[0]


def test_the_recommended_endpoint_analyses_then_launches_on_confirmation(client, conn, seen):
    _suspect_run(conn)
    plan = client.get("/api/launch-batches/recommended").json()
    assert plan["n"] == 1 and plan["items"][0]["key"] == "fix_leak"
    assert "garde anti-fuite" in plan["lines"] and "(1)" in plan["lines"]
    resp = client.post("/api/launch-batches/recommended", json={"items": [{"run_id": "r1", "key": "fix_leak"}]})
    assert resp.status_code == 200 and len(resp.json()["runs"]) == 1
    assert [c.objective.target_symbol for c in seen] == ["^VIX"] and seen[0].objective.horizons == [5]


def test_one_invalid_recommended_item_enqueues_nothing(client, conn, seen):
    _suspect_run(conn)
    resp = client.post("/api/launch-batches/recommended",
                       json={"items": [{"run_id": "r1", "key": "fix_leak"}, {"run_id": "nope", "key": "fix_leak"}]})
    assert resp.status_code == 400 and seen == []
    assert client.post("/api/launch-batches/recommended", json={"items": []}).status_code == 400
