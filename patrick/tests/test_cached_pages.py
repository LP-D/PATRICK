"""Les pages lourdes lisent un cache persistant (`webapp/cached_views.py`) au lieu de recalculer à l'ouverture, et la barre de chargement dit où en
est l'actualisation. Base temporaire, aucun réseau."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from fund_support import TODAY, install
from page_support import FullPageClient

import patrick.webapp.app as webapp
from patrick.fund import service, store
from patrick.tracking import db
from patrick.webapp import cached_views


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """Une base avec un run terminé et un signal live : de quoi remplir les vues sans les moyens d'une vraie base."""
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    conn = db.connect(path)
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^GSPC", 5, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2026-11-19T00:00:00"],
                       y_true=[None], y_pred=[3], y_proba=[0.7])
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()
    install(monkeypatch)
    monkeypatch.setattr(service, "current_date", lambda: TODAY)
    return path


def _boom(*args, **kwargs):
    raise AssertionError("la page ne doit rien recalculer à l'ouverture")


def test_the_analysis_page_is_read_from_its_cache_after_the_first_computation(seeded, monkeypatch):
    client = FullPageClient(webapp.app)
    assert client.get("/analysis").status_code == 200
    from patrick.tracking import usage

    monkeypatch.setattr(usage, "analyse", _boom)
    response = client.get("/analysis")
    assert response.status_code == 200 and "Données calculées le" in response.text


def test_the_home_page_and_its_heavy_tables_are_read_from_their_caches(seeded, monkeypatch):
    client = FullPageClient(webapp.app)
    assert client.get("/").status_code == 200
    from patrick.tracking import history, home

    monkeypatch.setattr(home, "home_summary", _boom)
    monkeypatch.setattr(history, "synthesis_overview", _boom)
    response = client.get("/")                                    # cadre + fragment lourd
    assert response.status_code == 200 and "Données calculées le" in response.text


def test_the_portfolio_page_has_one_snapshot_per_set_of_pairs_and_rejects_bad_input_before_any_computation(seeded):
    client = FullPageClient(webapp.app)
    assert client.get("/portfolio?pairs=%5EGSPC:%5EVIX:inverse").status_code in (200, 400)   # saisie valide ou refusée sans calcul
    assert client.get("/portfolio?pairs=nimporte+quoi").status_code == 400
    default = cached_views.PORTFOLIO.path("", seeded)
    custom = cached_views.PORTFOLIO.path("A:B:same", seeded)
    assert default != custom


def test_the_live_results_page_is_read_from_its_cache(seeded, monkeypatch):
    client = FullPageClient(webapp.app)
    assert client.get("/reel").status_code == 200
    from patrick.tracking import live_board

    monkeypatch.setattr(live_board, "board", _boom)
    assert client.get("/reel").status_code == 200


def test_asset_class_blocks_read_the_cached_model_statistics(seeded, monkeypatch):
    client = FullPageClient(webapp.app)
    assert client.get("/indices").status_code == 200
    from patrick.tracking import class_overview

    monkeypatch.setattr(class_overview, "model_stats_by_asset", _boom)
    assert client.get("/indices").status_code == 200
    assert client.get("/api/class-signals/indices").status_code == 200


def test_funds_are_read_from_the_cache_until_the_user_changes_something(seeded, monkeypatch):
    client = FullPageClient(webapp.app)
    conn = db.connect(seeded)
    store.create_strategy(conn, "Alpha", "PEA", 10000, "2025-06-02")
    conn.close()

    first = client.get("/fragments/fund-overview").text
    assert "Alpha" in first

    calls = []
    real = service.overview
    monkeypatch.setattr(service, "overview", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert "Alpha" in client.get("/fragments/fund-overview").text and client.get("/simulate").status_code == 200
    assert calls == []                                             # rien n'a changé : aucun recalcul, ni sur /fonds ni sur /simulate

    conn = db.connect(seeded)
    store.create_strategy(conn, "Beta", "CTO", 5000, "2025-06-02")  # l'utilisateur crée un fonds
    conn.close()
    after = client.get("/fragments/fund-overview").text
    assert "Beta" in after and "Alpha" in after                    # la page a attendu le nouveau calcul : jamais l'ancien état
    assert calls == [1]


def test_the_page_says_when_its_figures_were_computed_and_carries_the_loading_bar(seeded):
    html = FullPageClient(webapp.app).get("/analysis").text
    assert 'id="refresh-bar"' in html and 'data-views="analysis-usage"' in html and "refresh_bar.js" in html
    assert "Données calculées le" in html


def test_a_page_without_cache_yet_answers_202_with_the_bar_and_reloads_by_itself(seeded, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(cached_views, "FIRST_BUILD_WAIT_S", 0.0)
    monkeypatch.setattr(cached_views.ANALYSIS_USAGE, "compute", lambda path, key, progress: release.wait(5) or {})

    response = TestClient(webapp.app).get("/analysis")
    release.set()

    assert response.status_code == 202 and "Cette page se prépare" in response.text
    assert 'id="refresh-bar"' in response.text and "data-auto-reload" in response.text and 'data-views="analysis-usage"' in response.text


def test_the_refresh_status_api_reports_the_step_and_progress_of_a_running_computation(seeded, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(path, key, progress):
        progress.plan({"Derniers signaux": 1.0, "Mesures de direction": 3.0})
        progress.step("Derniers signaux")
        progress.step("Mesures de direction")
        started.set()
        release.wait(5)
        return {}

    monkeypatch.setattr(cached_views.ANALYSIS_USAGE, "compute", slow)
    cached_views.ANALYSIS_USAGE.request_refresh(None, seeded)
    assert started.wait(5)
    client = TestClient(webapp.app)

    data = client.get("/api/refresh-status?views=analysis-usage,class-stats&live=1").json()
    release.set()

    [running] = [v for v in data["views"] if v["name"] == "analysis-usage"]
    assert running["running"] is True and running["title"] == "séries et modèles"
    assert running["label"] == "Mesures de direction" and 0.2 <= running["fraction"] < 0.8
    assert all(v["name"] != "class-stats" or not v["running"] for v in data["views"])
    assert data["live"] is not None and set(data["live"]) == {"running", "done", "total"}
    english = client.get("/api/refresh-status?views=analysis-usage&lang=en").json()["views"]
    assert not english or english[0]["title"] in ("series and models",)
    deadline = time.monotonic() + 5
    while cached_views.ANALYSIS_USAGE.status(None, seeded)["running"] and time.monotonic() < deadline:
        time.sleep(0.05)


def test_the_refresh_status_api_only_tells_about_the_requested_views(seeded):
    client = TestClient(webapp.app)
    assert client.get("/api/refresh-status").json()["views"] == []
    assert client.get("/api/refresh-status").json()["live"] is None


def _model(trial_id: int, label: str, kind: str = "raw") -> dict:
    return {"trial_id": trial_id, "label": label, "kind": kind, "suspect": False, "segments": ["holdout"], "pup_segments": [],
            "horizon": 5, "dm_p": 0.03, "asset": label, "benchmark": None, "instrument_hint": {"symbol": label, "kind": "equity"}}


def test_the_model_options_are_rendered_once_per_list_of_models_and_language():
    from patrick.webapp import fund_routes, i18n

    models = [_model(1, "B"), _model(2, "A"), _model(3, "C", "alpha")]
    fr, en = i18n.translator("fr"), i18n.translator("en")

    first = fund_routes._model_options(webapp.templates, models, fr, "fr")
    assert fund_routes._model_options(webapp.templates, models, fr, "fr") is first          # même liste, même langue : rien n'est refait
    assert fund_routes._model_options(webapp.templates, models, en, "en") is not first      # autre langue : ses propres libellés
    assert fund_routes._model_options(webapp.templates, list(models), fr, "fr") is not first  # autre liste (recalculée) : nouveau rendu
    assert first.index('value="2"') < first.index('value="1"')                              # triées par nom : A avant B
    assert 'data-kind="alpha"' in first and "<optgroup" in first


def test_the_simulation_page_uses_the_pre_rendered_options(seeded, monkeypatch):
    conn = db.connect(seeded)
    store.create_strategy(conn, "Alpha", "PEA", 10000, "2025-06-02")
    conn.close()
    from patrick.webapp import fund_routes

    models = [_model(7, "ZZMODEL")]
    monkeypatch.setattr(fund_routes, "_cached_models", lambda conn: models)
    html = FullPageClient(webapp.app).get("/simulate").text
    assert "ZZMODEL" in html and 'value="7"' in html


def test_the_nightly_refresh_prepares_every_default_view_then_only_what_changed(seeded):
    first = cached_views.refresh_all_sync(seeded)
    assert set(first) == {v.name for v, _ in cached_views.DEFAULT_KEYS}
    assert cached_views.refresh_all_sync(seeded) == []                                      # rien de neuf : pas de second calcul


def test_the_end_of_a_live_pass_refreshes_the_other_pages_too(seeded):
    from patrick import live_refresh

    live_refresh.refresh_predictions_snapshot(seeded, background=False)
    assert cached_views.HOME_SUMMARY.load(None, seeded) is not None
    assert cached_views.FUND_MODELS.load(None, seeded) is not None


def test_the_startup_warm_up_prepares_the_missing_views_in_the_background(seeded):
    cached_views.warm_async(seeded)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and any(v.load(k, seeded) is None for v, k in cached_views.DEFAULT_KEYS):
        time.sleep(0.1)
    assert all(v.load(k, seeded) is not None for v, k in cached_views.DEFAULT_KEYS)
