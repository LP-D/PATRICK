"""Phase 7 (interface) -- test de fumée FastAPI des nouvelles pages
d'historique (`/runs`, `/runs/{id}`, `/targets/{ticker}`, `/universe`) : rend
les gabarits Jinja pour de vrai sur une base pré-remplie directement (pas de
run pipeline réel, contrairement à `test_webapp_smoke.py`) -- rapide, suffit à
détecter une erreur de gabarit/route."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.tracking import history as trackhistory
from patrick.webapp.app import app


def _seed_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    config = {
        "name": "vix_smoke", "target": "^VIX",
        "validation": {"scheme": "walkforward"},
        "data_quality": {"enabled": True},
        "selection": {"track_stability": True},
    }
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps(config), "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6})
    db.add_fold_metrics(conn, trial_id, 2, "test", {"F1_dir": 0.62})
    db.add_fold_metrics(conn, trial_id, 0, "holdout", {"F1_dir": 0.55})
    db.add_baseline_metrics(conn, "run1", "majority", "test", {"F1_dir": 0.5})
    db.save_dm_result(conn, "run1", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03})
    db.finish_run(conn, "run1", status="done", n_trials=1)

    config_cpcv = {
        "name": "vix_cpcv_smoke",
        "validation": {"scheme": "cpcv", "n_groups": 7, "k_test_groups": 2},
    }
    db.upsert_snapshot(conn, "snap2", "hash2", None, None, None)
    db.create_run(conn, "run2", "^VIX", 10, "snap2", json.dumps(config_cpcv), "cfghash2", "sha", 42)
    trial_id2 = db.create_trial(conn, "run2", "GLOBAL", "XGBoost", "SMOTE", 6, "shap")
    db.mark_best_trial(conn, trial_id2)
    for path_id in range(6):
        db.add_fold_metrics(conn, trial_id2, path_id, "test_path", {"F1_dir": 0.5 + path_id * 0.01})
    db.finish_run(conn, "run2", status="done", n_trials=1)
    conn.close()


def test_runs_explorer_lists_seeded_runs(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert "run1" in resp.text or "vix_smoke" in resp.text
    assert "run2" in resp.text or "vix_cpcv_smoke" in resp.text


def test_runs_explorer_filters_by_scheme(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/runs", params={"scheme": "cpcv"})
    assert resp.status_code == 200
    assert "vix_cpcv_smoke" in resp.text
    assert "vix_smoke" not in resp.text


def test_run_detail_page_renders_for_walkforward_run(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/runs/run1")
    assert resp.status_code == 200
    assert "vix_smoke" in resp.text
    assert "0.03" in resp.text  # p-value DM


def test_run_detail_page_renders_for_cpcv_run(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/runs/run2")
    assert resp.status_code == 200
    assert "vix_cpcv_smoke" in resp.text


def test_run_detail_page_404_for_unknown_run(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404


def test_target_page_renders_with_history(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/targets/^VIX")
    assert resp.status_code == 200
    assert "run1" in resp.text or "vix_smoke" in resp.text


def test_target_page_shows_real_fdr_correction_not_hardcoded_none(tmp_path, monkeypatch):
    """Bug trouve en verification navigateur (rapport de session precedente) :
    app.py::target_page construit son dict `detail` a la main avec
    `"target_fdr": None` code en dur (commentaire "Phase 5+: PBO/FDR requires
    stats.py"), au lieu d'appeler trackhistory.target_detail() -- qui, lui,
    calcule bien target_fdr via trackstats.fdr_across_targets(). Consequence :
    la branche warning/ok de target.html (p-value FDR non significative /
    significative) est INATTEIGNABLE en production, quelles que soient les
    donnees reelles -- run1/^VIX a pourtant un dm_result reel (p=0.03, seede
    par _seed_db) que trackhistory.target_detail() sait lire.

    Ce test compare la route reelle a ce que trackhistory.target_detail()
    calcule sur la MEME base -- pas juste "target_fdr n'est pas None" dans
    l'abstrait, mais que la page affiche la vraie p-value ajustee BH."""
    _seed_db(tmp_path, monkeypatch)

    conn = db.connect(str(tmp_path / "patrick.db"))
    expected = trackhistory.target_detail(conn, "^VIX")
    conn.close()
    assert expected["target_fdr"] is not None, (
        "precondition du test invalide : trackhistory.target_detail() devrait "
        "calculer un target_fdr reel a partir du dm_result seede par _seed_db"
    )

    client = TestClient(app)
    resp = client.get("/targets/^VIX")
    assert resp.status_code == 200
    expected_p = "%.4f" % expected["target_fdr"]["adjusted_p_value"]
    assert expected_p in resp.text, (
        f"la p-value FDR ajustee reelle ({expected_p}) n'apparait pas dans la page -- "
        "target_page() ignore trackhistory.target_detail() et code target_fdr=None en dur"
    )


def test_target_page_renders_empty_state_without_history(tmp_path, monkeypatch):
    """^GSPC (pas AAPL) : univers réduit (feature/universe-reduction) --
    AAPL a été retiré avec tout le groupe "Actions individuelles", /targets/
    AAPL renvoie donc désormais 404 ("Cible inconnue") plutôt que la page
    vide que ce test vérifie. ^GSPC reste dans l'univers réduit et n'a pas
    de run seedé par _seed_db (seul ^VIX en a) -- même rôle que jouait AAPL."""
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/targets/%5EGSPC")
    assert resp.status_code == 200
    assert "Aucun run pour cette cible" in resp.text


def test_universe_page_renders(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/universe")
    assert resp.status_code == 200
    assert "VIX" in resp.text
