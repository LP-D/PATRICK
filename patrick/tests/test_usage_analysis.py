"""Page « Séries, features et modèles » : ce que les modèles finaux utilisent réellement (`tracking/usage.py`)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import db as trackdb
from patrick.tracking import usage
from patrick.webapp.app import app

UNIVERSE = {"yf_tickers": ["^GSPC", "XLV", "GC=F", "DX-Y.NYB"], "fred_series": {"NFCI": "NFCI", "VIX": "VIXCLS"}}


def test_a_simple_feature_resolves_to_its_longest_known_series():
    known = sorted(["IDX_GSPC", "IDX_GSPC_rv", "NFCI", "GC=F", "XLV"], key=lambda s: (-len(s), s))
    assert usage.base_series("IDX_GSPC_rv_ret_1d", known) == "IDX_GSPC_rv"
    assert usage.base_series("IDX_GSPC_ret_1d", known) == "IDX_GSPC"
    assert usage.base_series("GC=F_egarch_vol", known) == "GC=F"
    assert usage.base_series("UNKNOWN_ret_1d", known) is None


def test_an_interaction_names_both_of_its_series():
    known = ["IDX_GSPC", "XLV"]
    assert usage.feature_series("IDX_GSPC_ret_1d__ratio__XLV_rsi_14d", known) == ["IDX_GSPC", "XLV"]
    assert usage.feature_family("IDX_GSPC_ret_1d__ratio__XLV_rsi_14d", "IDX_GSPC") == "interaction"


@pytest.mark.parametrize("name, family", [
    ("IDX_GSPC_ret_1d", "technical"), ("IDX_GSPC_zscore_20d", "technical"), ("XLV_arima_resid", "volatility_model"),
    ("GC=F_egarch_vol", "volatility_model"), ("XLV_lc_rangepos_252d", "long_cycle"), ("NFCI", "macro"), ("NFCI_lag5", "macro"),
])
def test_feature_families(name, family):
    series = next(s for s in ("IDX_GSPC", "XLV", "GC=F", "NFCI") if name == s or name.startswith(s + "_"))
    assert usage.feature_family(name, series) == family


def _model(conn, tmp_path, run_id, target, features, f1, auc, algo="XGBoost", champion=False):
    trackdb.upsert_snapshot(conn, "s1", "h1", None, None, None)
    cfg = {"name": run_id, "universe": UNIVERSE}
    trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="s1", config_json=json.dumps(cfg), config_hash="h",
                       git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", len(features), "shap")
    folder = tmp_path / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / f"{run_id}_best_model_h1.joblib").write_bytes(b"x")
    (folder / f"{run_id}_best_model_h1_meta.json").write_text(
        json.dumps({"algo": algo, "N": len(features), "sampler": "SMOTE", "regime": "GLOBAL", "feature_names": features}))
    trackdb.mark_best_trial(conn, tid, artifact_path=f"runs/{run_id}/{run_id}_best_model_h1.joblib")
    with conn:
        conn.execute("UPDATE run SET status = 'done' WHERE run_id = ?", (run_id,))
        for metric, value in (("F1_dir", f1), ("AUC_ovr_4cls", auc)):
            conn.execute("INSERT INTO fold_metric VALUES (?, 0, 'test', ?, ?)", (tid, metric, value))
        if champion:
            conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, reason) VALUES (?, 1, ?, ?, 'first')",
                         (target, run_id, tid))
    return tid


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv(usage.ARTIFACT_BASE_ENV, str(tmp_path))
    conn = trackdb.connect(str(tmp_path / "p.db"))
    _model(conn, tmp_path, "r1", "XLV", ["IDX_GSPC_ret_1d", "NFCI_zscore_20d", "XLV_lc_rangepos_252d"], 0.54, 0.57, champion=True)
    _model(conn, tmp_path, "r2", "GC=F", ["IDX_GSPC_ret_1d", "IDX_GSPC_ret_1d__ratio__DX_Y.NYB_rsi_14d"], 0.51, 0.55, algo="CatBoost")
    _model(conn, tmp_path, "r3", "SP500", ["IDX_GSPC_ret_1d"], 0.99, 0.60)            # fuite : écarté des comptes
    return conn


def test_the_analysis_counts_final_models_features_and_series(seeded):
    a = usage.analyse(seeded)
    assert (a["n_models"], a["n_sane"], a["n_suspect"], a["n_champions"]) == (3, 2, 1, 1)
    features = {f["feature"]: f for f in a["features"]}
    assert features["IDX_GSPC_ret_1d"]["n_models"] == 2 and features["IDX_GSPC_ret_1d"]["n_targets"] == 2
    assert "SP500" not in {t for f in a["features"] for t in [f["feature"]]}
    series = {s["series"]: s for s in a["series"]}
    assert series["IDX_GSPC"]["n_models"] == 3            # 2 features simples + 1 croisement, 2 modèles, mais 3 présences
    assert series["DX_Y.NYB"]["n_models"] == 1
    assert "XLV" not in series, "la cible elle-même n'est pas une série explicative"
    assert a["n_own_features"] == 1
    assert {"GC=F"} <= set(a["unused_series"])           # dans l'univers, jamais retenue
    assert [r["key"] for r in a["by_algo"]] == ["CatBoost", "XGBoost"]


def test_a_suspect_models_features_are_never_counted(seeded):
    names = {f["feature"] for f in usage.analyse(seeded)["features"]}
    assert names == {"IDX_GSPC_ret_1d", "NFCI_zscore_20d", "XLV_lc_rangepos_252d", "IDX_GSPC_ret_1d__ratio__DX_Y.NYB_rsi_14d"}


def test_a_model_without_a_detail_file_is_counted_but_has_no_features(seeded, tmp_path):
    (tmp_path / "runs" / "r1" / "r1_best_model_h1_meta.json").unlink()
    a = usage.analyse(seeded)
    assert a["n_sane"] == 2 and a["n_with_features"] == 1


def test_the_page_renders_and_collapses_long_tables(seeded):
    html = TestClient(app).get("/analysis").text
    assert "Séries, features et modèles" in html and "IDX_GSPC_ret_1d" in html
    assert 'id="modeles"' in html and 'id="features"' in html and 'id="series"' in html
    assert "kind-badge kind-directional" in html


def test_the_page_is_in_the_navigation(seeded):
    assert 'href="/analysis"' in TestClient(app).get("/analysis").text


def test_the_page_renders_with_an_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "empty.db"))
    assert TestClient(app).get("/analysis").status_code == 200
