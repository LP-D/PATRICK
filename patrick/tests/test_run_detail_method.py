"""Page d'un run : méthode d'évaluation, règle d'alignement, placebo de décalage et DM sur le Brier (ADR 0007 à 0010)."""
from __future__ import annotations

import html as htmllib
import json

from fastapi.testclient import TestClient

from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.webapp.app import app


def _config(target: str, method: int, rule: int) -> str:
    return RunConfig.model_validate({"name": "m", "objective": {"target_symbol": target, "horizons": [1], "regimes": ["GLOBAL"],
                                                                "session_rule": rule},
                                     "validation": {"method_version": method}}).model_dump_json()


def _run(conn, run_id: str, target: str, method: int, rule: int) -> None:
    trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="snap", config_json=_config(target, method, rule),
                       config_hash="h", git_sha="sha", seed=1)
    trackdb.finish_run(conn, run_id, status="done", n_trials=1)


def _page(tmp_path, monkeypatch, seed):
    db = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    conn = trackdb.connect(db)
    trackdb.upsert_snapshot(conn, "snap", "hash", None, None, None)
    seed(conn)
    conn.close()
    return TestClient(app).get("/runs/r1/detail")


def test_a_method_two_run_shows_its_method_its_placebo_and_its_brier_test(tmp_path, monkeypatch):
    def seed(conn):
        _run(conn, "r1", "^GSPC", 2, 2)
        trackdb.save_placebo(conn, "r1", "real", {"AUC_ovr_4cls": 0.69})
        trackdb.save_placebo(conn, "r1", "lag1", {"AUC_ovr_4cls": 0.51})
        trackdb.save_dm_brier(conn, "r1", {"baseline": "train_up_rate", "brier_model": 0.2410, "brier_baseline": 0.2500,
                                           "dm_stat": -2.2, "p_value": 0.03, "n_obs": 280})

    page = _page(tmp_path, monkeypatch, seed)
    assert page.status_code == 200, page.text[:300]
    html = page.text
    assert "Méthode 2 · alignement 2" in html and "Diebold-Mariano sur la direction" in html
    assert "AUC 0.690 → 0.510" in html and "information du jour même" in html          # le verdict « same_day »
    assert "Diebold-Mariano sur le Brier" in html and "0.2410" in html and "280 lignes" in html


def test_a_legacy_currency_run_is_flagged_and_has_no_placebo(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch, lambda conn: _run(conn, "r1", "EURUSD=X", 1, 1))
    html = htmllib.unescape(page.text)
    assert "Méthode 1 · alignement 1" in html and "ne se compare pas" in html.replace("Ne se compare", "ne se compare")
    assert "Devise d'avant la correction" in html and "alignement des devises" in html
    assert "Pas de placebo pour ce run" in html and "Diebold-Mariano sur le Brier" not in html


def test_the_english_page_is_translated(tmp_path, monkeypatch):
    db = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    conn = trackdb.connect(db)
    trackdb.upsert_snapshot(conn, "snap", "hash", None, None, None)
    _run(conn, "r1", "^GSPC", 2, 2)
    conn.close()
    html = htmllib.unescape(TestClient(app).get("/runs/r1/detail", params={"lang": "en"}).text)
    assert "Method 2 · alignment 2" in html and "Evaluation method" in html and "No placebo for this run" in html
    assert json.dumps("Méthode 2") not in html


# --------------------------------------------------------------------------- synthèse : bloc « À faire »

def test_the_home_page_lists_what_needs_an_action_with_a_link_each(tmp_path, monkeypatch):
    db = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    conn = trackdb.connect(db)
    trackdb.upsert_snapshot(conn, "snap", "hash", None, None, None)
    _run(conn, "fx_old", "EURUSD=X", 1, 1)
    trackdb.create_trial(conn, "fx_old", "GLOBAL", "XGBoost", "none", 5, "shap")
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) "
                 "VALUES ('EURUSD=X', 1, 'fx_old', 1, datetime('now'), 'first')")
    conn.commit()
    conn.close()
    from patrick.tracking import home as trackhome

    conn = trackdb.connect(db)
    items = trackhome.action_items(conn, n_recent_failures=2, n_suspect=1)
    conn.close()
    assert [i["key"] for i in items] == ["failures", "suspect", "fx_legacy"] and items[-1]["n"] == 1
    page = htmllib.unescape(TestClient(app).get("/").text)
    assert "À faire" in page and "champion(s) de change entraîné(s) avant la correction" in page
    assert 'href="/fx"' in page


def test_the_home_page_has_no_to_do_block_when_nothing_needs_an_action(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    assert "home-actions" not in TestClient(app).get("/").text
