"""Point 8 : la page d'un actif ne mélange pas modèles directionnels et alpha -- les runs alpha ont leur section, avec AUC puis F1,
et un run dont les chiffres sont trop beaux pour être vrais y est marqué « suspect »."""
from __future__ import annotations

import json

from page_support import FullPageClient as TestClient

from patrick.tracking import db
from patrick.webapp.app import app


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap", "h", None, None, None)
    for run_id, target, f1 in (("d1", "^VIX", 0.55), ("a1", "^VIX__alpha_^GSPC", 0.58), ("a2", "^VIX__alpha_QQQ", 0.99)):
        db.create_run(conn, run_id, target, 5, "snap", json.dumps({"name": run_id, "validation": {"scheme": "walkforward"}}), "c", "s", 42)
        tid = db.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, tid)
        db.add_fold_metrics(conn, tid, 1, "test", {"F1_dir": f1, "AUC_ovr_4cls": 0.60 if f1 < 0.9 else 0.97})
        db.finish_run(conn, run_id, status="done", n_trials=1)
    return conn


def test_target_page_lists_alpha_models_apart_from_directional(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    html = TestClient(app, base_url="http://127.0.0.1:8000").get("/targets/^VIX").text
    assert 'id="alpha-models"' in html
    section = html[html.index('id="alpha-models"'):]
    assert "^GSPC" in section and "QQQ" in section
    assert "0.600" in section                      # AUC puis F1 du modèle alpha sain
    assert "suspect" in section                    # le modèle à F1 = 0,99 est signalé
    assert "d1" not in section.split("</section>")[0]   # le run directionnel n'est pas dans la section alpha


def test_target_page_without_alpha_model_has_no_alpha_section(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap", "h", None, None, None)
    db.create_run(conn, "d1", "^VIX", 5, "snap", json.dumps({"name": "d1"}), "c", "s", 42)
    db.finish_run(conn, "d1", status="done", n_trials=0)
    conn.close()
    html = TestClient(app, base_url="http://127.0.0.1:8000").get("/targets/^VIX").text
    assert 'id="alpha-models"' not in html


def test_compare_runs_flags_a_mix_of_directional_and_alpha_models(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    mixed = client.get("/compare-runs", params={"run_ids": ["d1", "a1"]}).text
    assert "kind-alpha" in mixed and "kind-directional" in mixed
    assert "ne sont pas directement comparables" in mixed
    same = client.get("/compare-runs", params={"run_ids": ["a1", "a2"]}).text
    assert "ne sont pas directement comparables" not in same
