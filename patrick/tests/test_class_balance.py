"""Répartition haut/bas des classes réelles et prédites : garde-fou contre un modèle qui ne prédirait qu'une montée ou qu'une baisse
(même avec SMOTE à l'entraînement, la répartition des prédictions sur le test doit rester lisible)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import class_balance as CB
from patrick.tracking import db
from patrick.webapp.app import app
from patrick.webapp.forms import default_config_dict


def test_summary_splits_classes_in_down_and_up_shares():
    # (classe réelle, classe prédite, effectif) : réel 40 bas / 60 haut ; prédit 10 bas / 90 haut
    rows = [(0, 3, 20), (1, 2, 20), (2, 2, 30), (3, 3, 30)]
    s = CB.summarize(rows)
    assert s["n"] == 100
    assert s["true"] == pytest.approx([0.20, 0.20, 0.30, 0.30]) and s["pred"] == pytest.approx([0.0, 0.0, 0.50, 0.50])
    assert s["true_up"] == pytest.approx(0.60) and s["true_down"] == pytest.approx(0.40)
    assert s["pred_up"] == pytest.approx(1.0) and s["pred_down"] == pytest.approx(0.0)
    assert s["pred_one_sided"] is True


def test_a_balanced_prediction_is_not_flagged_and_an_empty_sample_has_no_summary():
    s = CB.summarize([(0, 0, 25), (1, 2, 25), (2, 1, 25), (3, 3, 25)])
    assert s["pred_up"] == pytest.approx(0.5) and s["pred_one_sided"] is False
    assert CB.summarize([]) is None


def test_the_flag_triggers_above_seventy_percent_on_either_side_only():
    assert CB.summarize([(0, 3, 71), (3, 0, 29)])["pred_one_sided"] is True
    assert CB.summarize([(0, 0, 71), (3, 3, 29)])["pred_one_sided"] is True
    assert CB.summarize([(0, 3, 70), (3, 0, 30)])["pred_one_sided"] is False


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    config = default_config_dict()
    config["name"] = "balance_smoke"
    config["objective"].update({"target_symbol": "^GSPC", "horizons": [1], "regimes": ["GLOBAL"]})
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^GSPC", 1, "snap1", json.dumps(config), "cfghash", "sha", 42)
    trial = db.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial)
    db.add_fold_metrics(conn, trial, 1, "test", {"F1_dir": 0.6})
    # test : réel 4 bas / 6 haut ; prédit 1 bas / 9 haut
    ts = [f"2024-01-{d:02d}" for d in range(1, 11)]
    db.add_predictions(conn, trial, 1, "test", ts, [0, 0, 1, 1, 2, 2, 2, 3, 3, 3], [3, 3, 3, 2, 2, 2, 2, 3, 3, 0])
    # holdout : réel 1 bas / 1 haut ; prédit 1 bas / 1 haut
    db.add_predictions(conn, trial, 0, "holdout", ["2025-01-02", "2025-01-03"], [1, 2], [0, 3])
    # live (résultat inconnu) et ligne sans classe réelle : jamais comptés
    db.add_predictions(conn, trial, 0, "live", ["2025-02-03"], [None], [3])
    # run sans aucune prédiction
    db.create_run(conn, "run2", "^GSPC", 5, "snap1", json.dumps(config), "cfghash2", "sha", 42)
    t2 = db.create_trial(conn, "run2", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, t2)
    db.finish_run(conn, "run1", status="done", n_trials=1)
    db.finish_run(conn, "run2", status="done", n_trials=1)
    return conn, trial


def test_for_runs_reads_the_best_trial_predictions_per_split(tmp_path, monkeypatch):
    conn, _ = _seed(tmp_path, monkeypatch)
    out = CB.for_runs(conn, ["run1", "run2", "inconnu"])
    conn.close()
    assert set(out) == {"run1"}
    test, holdout = out["run1"]["test"], out["run1"]["holdout"]
    assert test["n"] == 10 and test["true_up"] == pytest.approx(0.6) and test["pred_up"] == pytest.approx(0.9)
    assert test["pred_one_sided"] is True
    assert holdout["n"] == 2 and holdout["true_up"] == pytest.approx(0.5) and holdout["pred_up"] == pytest.approx(0.5)


def test_cpcv_test_paths_count_as_test(tmp_path, monkeypatch):
    conn, trial = _seed(tmp_path, monkeypatch)
    db.add_predictions(conn, trial, 0, "test_path", ["2024-03-01", "2024-03-02"], [0, 3], [0, 3], path_id=0)
    out = CB.for_runs(conn, ["run1"])
    conn.close()
    assert out["run1"]["test"]["n"] == 12


def test_history_page_shows_real_and_predicted_up_down_shares(tmp_path, monkeypatch):
    conn, _ = _seed(tmp_path, monkeypatch)
    conn.close()
    page = TestClient(app).get("/runs").text
    assert "60 / 40" in page and "90 / 10" in page          # réel et prédit (haut / bas, en %)
    assert "class-balance-warn" in page                      # 90 % de hausses prédites : signalé


def test_run_detail_shows_the_four_classes_for_test_and_holdout(tmp_path, monkeypatch):
    conn, _ = _seed(tmp_path, monkeypatch)
    conn.close()
    page = TestClient(app).get("/runs/run1/detail").text
    assert 'id="repartition"' in page
    assert "30.0 %" in page                                  # 3 hausses faibles sur 10 en réel
    assert "class-balance-warn" in page
    assert "&lt;span" not in page and "&lt;strong" not in page   # le balisage du tableau ne doit jamais s'afficher en texte


def test_target_page_lists_the_shares_of_each_run(tmp_path, monkeypatch):
    conn, _ = _seed(tmp_path, monkeypatch)
    conn.close()
    page = TestClient(app).get("/targets/%5EGSPC").text
    assert "60 / 40" in page and "90 / 10" in page


def test_the_query_reaches_predictions_through_the_trial_index_never_the_split_index(tmp_path, monkeypatch):
    """Mesuré sur la vraie base (4,8 Go, sans statistiques SQLite) : avec un filtre `split IN (...)`, SQLite choisissait `idx_pred_split` dès ~20 essais et
    balayait toutes les prédictions de tous les runs (> 100 s). La lecture doit passer par la clé primaire (trial_id)."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    config = default_config_dict()
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trials = []
    for i in range(40):
        db.create_run(conn, f"r{i}", "^GSPC", 1, "snap1", json.dumps(config), f"h{i}", "sha", 42)
        trial = db.create_trial(conn, f"r{i}", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, trial)
        ts = [f"2020-{1 + d // 28:02d}-{1 + d % 28:02d}" for d in range(300)]
        db.add_predictions(conn, trial, 1, "test", ts, [d % 4 for d in range(300)], [(d + 1) % 4 for d in range(300)])
        trials.append(trial)
    plan = " ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + CB.counts_sql(20), trials[-20:]))
    conn.close()
    assert "idx_pred_split" not in plan and "trial_id=?" in plan
