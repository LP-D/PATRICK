"""Mesures et panneau des modèles de valeur exacte (ADR 0032) : couverture de l'intervalle, pente de calibration, gain d'erreur absolue,
gain par position ; règle du duel IC + R² ; formats ; classement des candidats d'un run de valeur exacte dans la synthèse d'un lancement."""
from __future__ import annotations

import json

import numpy as np
import pytest

from patrick.models import value as value_lib
from patrick.tracking import db, kpi_summary
from patrick.validation import metric_panel as mp


def test_value_metrics_read_coverage_slope_and_skill_against_known_answers():
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, 4000)
    r_hat = 0.5 * r                                                       # prévisions moitié trop petites : pente du réalisé sur le prévu = 2
    err = r - r_hat
    m = value_lib.value_metrics(r, r_hat, residuals=err)                  # les erreurs du modèle sont ses vraies erreurs : couverture ≈ 80 %
    assert m["MZ_slope"] == pytest.approx(2.0, rel=1e-6)
    assert m["Cov80"] == pytest.approx(0.80, abs=0.01)
    assert m["MAE_skill"] == pytest.approx(0.5, abs=1e-9)                 # |r - r/2| = |r| / 2
    assert m["Gain_sign"] == pytest.approx(np.mean(np.abs(r)), rel=1e-9)  # signe toujours juste
    narrow = value_lib.value_metrics(r, r_hat, residuals=err * 0.3)       # un modèle qui se croit trois fois plus précis
    assert narrow["Cov80"] < 0.4


def test_coverage_needs_the_errors_and_constant_forecasts_have_no_slope():
    r = np.array([0.01, -0.02, 0.005, 0.0, 0.03])
    m = value_lib.value_metrics(r, np.full(5, 0.001))
    assert m["Cov80"] is None and m["MZ_slope"] is None and m["IC"] is None
    assert m["MAE_skill"] is not None and m["Gain_sign"] == pytest.approx(np.mean(r))


def test_the_value_duel_wants_a_better_ic_without_degrading_the_r2():
    v = mp.duel_verdict({"IC": 0.12, "R2_oos": -0.03}, {"IC": 0.10, "R2_oos": 0.0})
    assert v["criterion"] == mp.CRITERION_IC_R2 and v["winner"] == "champion" and v["reason"] == "r2_worse"
    v = mp.duel_verdict({"IC": 0.12, "R2_oos": -0.005}, {"IC": 0.10, "R2_oos": 0.0})   # dans la tolérance
    assert v["winner"] == "challenger" and v["challenger"]["IC"] == 0.12 and "Cov80" in v["challenger"]
    v = mp.duel_verdict({"IC": 0.09, "R2_oos": 0.05}, {"IC": 0.10, "R2_oos": 0.0})
    assert v["winner"] == "champion" and v["reason"] == "ic_not_better"
    v = mp.duel_verdict({"IC": 0.12}, {"IC": 0.10, "R2_oos": 0.0})                     # un côté sans R² : l'IC seule
    assert v["criterion"] == mp.CRITERION_IC and v["winner"] == "challenger"


def test_value_panel_formats_and_best_values():
    assert mp.fmt("R2_oos", -0.0123) == "-0.012" and mp.fmt("R2_oos", 0.02) == "+0.020"
    assert mp.fmt("Hit_sign", 0.5288) == "52.9 %" and mp.fmt("Cov80", 0.8) == "80.0 %"
    assert mp.fmt("Gain_sign", 0.0012) == "+0.12 %" and mp.fmt("MZ_slope", 0.734) == "0.73"
    assert mp.fmt("AUC_dir", 0.5312) == "0.531" and mp.fmt("Acc_dir_p", 0.5137) == "51.4 %"   # le panneau de direction ne change pas
    assert mp.fmt("unknown", 1.23456) == "1.235" and mp.fmt("IC", float("nan")) == "—"
    assert mp.best_of("Cov80", [0.62, 0.86, 0.95]) == 0.86                  # la plus proche de 80 %, pas la plus haute
    assert mp.better("MZ_slope", 0.9, 1.3) and not mp.better("MZ_slope", 1.3, 0.9)
    assert mp.keys_for("value") == mp.VALUE_PANEL_KEYS and mp.keys_for("directional") == mp.PANEL_KEYS
    assert mp.cells({"IC": 0.1}, mp.VALUE_PANEL_KEYS) == ["0.100", "—", "—", "—"]


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(connection, "snap", "h", None, None, None)
    yield connection
    connection.close()


def test_the_launch_summary_ranks_value_candidates_on_the_ic(conn):
    cfg = {"objective": {"target_symbol": "^GSPC", "task": "value"}, "selection": {"criterion": "IC"}, "validation": {"scheme": "walkforward"}}
    db.create_run(conn, "v1", "^GSPC__val", 5, "snap", json.dumps(cfg), "c", "s", 42)
    scores = {"XGBoost": {"IC": 0.02, "R2_oos": 0.01, "AUC_dir": 0.60}, "LightGBM": {"IC": 0.11, "R2_oos": -0.01, "AUC_dir": 0.52}}
    for algo, metrics in scores.items():
        trial_id = conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best) "
                                "VALUES ('v1', 'GLOBAL', ?, 'none', 8, 'shap', '{}', 0)", (algo,)).lastrowid
        for fold in (0, 1):
            for metric, value in metrics.items():
                conn.execute("INSERT INTO fold_metric VALUES (?, ?, 'test', ?, ?)", (trial_id, fold, metric, value))
    conn.commit()
    out = kpi_summary.summarize(conn, ["v1"])
    assert out["kind"] == "value"
    assert [r["algo"] for r in out["by_algo"]] == ["LightGBM", "XGBoost"]   # l'IC classe, pas l'AUC de direction
    assert out["by_horizon"][0]["algo"] == "LightGBM" and out["by_horizon"][0]["window_value_panel"]["IC"] == pytest.approx(0.11)
