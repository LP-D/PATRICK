"""Phase 6.4 (P6.4) -- intégration bout-en-bout : `run_pipeline` (mode
walk-forward) persiste son résultat Diebold-Mariano dans `dm_result`
(migration 0009), et `tracking.stats.fdr_across_targets` l'agrège
correctement à travers PLUSIEURS cibles distinctes."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module
from patrick.tracking import stats as trackstats

# Lance deux runs pipeline complets (~70s chacun) -- exclu par défaut, cf. pyproject.toml.
pytestmark = pytest.mark.slow


def _synthetic_raw_no_floor(target_col: str, n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({target_col: target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _tiny_config(tmp_path, target_symbol: str, out_suffix: str) -> RunConfig:
    raw_yaml = {
        "name": f"fdr_test_{out_suffix}",
        "objective": {"target_symbol": target_symbol, "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / f"runs_{out_suffix}"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


def test_run_pipeline_persists_dm_result_queryable_across_targets(tmp_path, monkeypatch):
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        col = "IDX_TESTA" if objective.target_symbol == "^TESTA" else "IDX_TESTB"
        seed = 0 if objective.target_symbol == "^TESTA" else 1
        return _synthetic_raw_no_floor(col, seed=seed)

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick.db")

    result_a = engine_module.run_pipeline(
        _tiny_config(tmp_path, "^TESTA", "a"),
        store=DataStore(root=str(tmp_path / "store_a")), db_path=db_path)
    result_b = engine_module.run_pipeline(
        _tiny_config(tmp_path, "^TESTB", "b"),
        store=DataStore(root=str(tmp_path / "store_b")), db_path=db_path)

    assert result_a["diebold_mariano"] is not None
    assert result_b["diebold_mariano"] is not None

    conn = sqlite3.connect(db_path)
    n_dm_rows = conn.execute("SELECT COUNT(*) FROM dm_result").fetchone()[0]
    # Phase X5 : deux lignes par run (class_specific + common), pas une seule.
    assert n_dm_rows == 4, "deux dm_result (class-specific + commun) par run walk-forward"

    fdr_result = trackstats.fdr_across_targets(conn)
    conn.close()

    assert fdr_result["n_tested"] == 2
    assert set(fdr_result["results"].keys()) == {"^TESTA", "^TESTB"}
    for target in ("^TESTA", "^TESTB"):
        r = fdr_result["results"][target]
        assert 0.0 <= r["p_value"] <= 1.0
        assert 0.0 <= r["adjusted_p_value"] <= 1.0
        assert r["adjusted_p_value"] >= r["p_value"] - 1e-9  # BH ne peut qu'augmenter (ou égaler) p


def test_cpcv_run_never_writes_a_dm_result(tmp_path, monkeypatch):
    """Contre-épreuve P6.1/P6.4 : un run en mode CPCV ne calcule pas de
    Diebold-Mariano (limite documentée, cf. METHODOLOGY.md 11.4) -- ne doit
    donc jamais écrire de ligne dans `dm_result`, ni fausser
    `fdr_across_targets` avec une p-value walk-forward réutilisée par erreur."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor("IDX_TESTC")

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    config = _tiny_config(tmp_path, "^TESTC", "c")
    config.validation.scheme = "cpcv"
    config.validation.n_groups = 5
    config.validation.k_test_groups = 2
    db_path = str(tmp_path / "patrick_cpcv.db")

    result = engine_module.run_pipeline(
        config, store=DataStore(root=str(tmp_path / "store_c")), db_path=db_path)
    assert result["diebold_mariano"] is None

    conn = sqlite3.connect(db_path)
    n_dm_rows = conn.execute("SELECT COUNT(*) FROM dm_result").fetchone()[0]
    assert n_dm_rows == 0
    fdr_result = trackstats.fdr_across_targets(conn)
    conn.close()
    assert fdr_result["n_tested"] == 0
