"""Test de fumée bout-en-bout du pipeline complet, sans réseau : `ingest()` est
monkeypatché pour renvoyer des données synthétiques (le sandbox de dev n'a pas
accès à yfinance/FRED), tout le reste (features avancées, walk-forward, sélection,
grille, Optuna, export) tourne pour de vrai. La vérification avec de vraies
données (doit retrouver F1_dir≈0.610±0.025 sur `configs/examples/vix_direction.yaml`)
doit être relancée par un humain sur une machine avec accès réseau.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


@pytest.fixture
def tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "smoke_test",
        "objective": {
            "target_symbol": "^TEST",
            "horizons": [3, 5],
            "regimes": ["GLOBAL"],
        },
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15,
            "interact_top_pairs": 8,
            "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": True, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


def test_pipeline_runs_end_to_end_on_synthetic_data(tiny_config, monkeypatch, tmp_path):
    def fake_ingest(objective, universe, store=None, force=False):
        return _synthetic_raw()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_store"),
        db_path=str(tmp_path / "patrick_test.db"))

    board = result["leaderboard"]
    assert len(board) > 0
    assert set(["horizon", "fold", "regime", "N", "sampler", "algo", "F1_dir"]).issubset(board.columns)
    assert board["F1_dir"].between(0, 1).all()

    assert result["final_best"] is not None
    assert result["model_path"] is not None
    import os
    assert os.path.exists(result["model_path"])


def _synthetic_raw_no_floor(n=1500, seed=0) -> pd.DataFrame:
    """Variante de `_synthetic_raw` sans `.clip(min=-10)` sur la marche
    aléatoire cumulée. Ce clip fait "coller" la cible à un plancher exact
    pendant des séries de jours consécutifs dès que la marche aléatoire
    dérive suffisamment bas (attendu sur 1500 pas, écart-type cumulé ~19 pour
    un floor à 10 en dessous du niveau de départ) : ~40% des rendements à
    horizon 5j tombent alors exactement à 0.0 (prix collé au plancher des
    deux côtés de la fenêtre), quel que soit `flat_thr` (le filtre "flat" de
    `build_target` ne peut rien contre un rendement EXACTEMENT nul, pas
    seulement petit) — le dernier fold walk-forward s'effondre alors à
    quelques lignes de test. Découvert en écrivant les tests Phase 2 ; propre
    à ce test, ne touche pas `_synthetic_raw` (utilisé ailleurs avec ce
    comportement déjà implicitement accepté)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def test_phase2_holdout_dm_cumulative_trials_and_pbo_are_populated(tiny_config, monkeypatch, tmp_path):
    """Critère de sortie Phase 2 : pour la config gagnante, le pipeline produit
    une métrique holdout, une p-value Diebold-Mariano vs la meilleure baseline,
    et un compteur d'essais cumulé — avec les réglages par défaut
    (holdout_months=15, min_test_rows=20, flat_thr=0.003), sur un historique
    synthétique sans l'artefact de `_synthetic_raw` (cf.
    `_synthetic_raw_no_floor`)."""

    def fake_ingest(objective, universe, store=None, force=False):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_stats_store"),
        db_path=db_path)

    assert result["final_best"] is not None

    assert result["holdout"] is not None, "le holdout ne doit pas se désactiver sur 1500 lignes"
    assert 0 <= result["holdout"]["F1_dir"] <= 1

    assert result["diebold_mariano"] is not None
    assert result["diebold_mariano"]["baseline"] in (
        "BASELINE_majority", "BASELINE_persistence", "BASELINE_har_rv")
    assert 0 <= result["diebold_mariano"]["p_value"] <= 1

    assert result["cumulative_trials"] > 0

    assert result["pbo"] is not None
    # 2 folds (tiny_config) -> pair, CSCV utilisable tel quel (pas de recadrage).
    assert result["pbo"]["n_blocks"] == 2

    conn = sqlite3.connect(db_path)
    holdout_rows = conn.execute(
        "SELECT count(*) FROM fold_metric WHERE split = 'holdout'").fetchone()[0]
    assert holdout_rows > 0
    holdout_preds = conn.execute(
        "SELECT count(*) FROM prediction WHERE split = 'holdout'").fetchone()[0]
    assert holdout_preds > 0
    conn.close()


def test_run_writes_full_db_trail_and_is_reproducible_on_same_snapshot(tiny_config, monkeypatch, tmp_path):
    """Critère de sortie Phase 1 : un run complet écrit snapshot + run + N trials
    + fold_metrics + baselines + predictions ; deux runs identiques sur le même
    snapshot produisent des métriques identiques."""
    def fake_ingest(objective, universe, store=None, force=False):
        return _synthetic_raw()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test.db")
    store = DataStore(root=str(tmp_path / "store"))

    result1 = engine_module.run_pipeline(tiny_config, store=store, db_path=db_path)
    result2 = engine_module.run_pipeline(tiny_config, store=store, db_path=db_path)

    board1 = result1["leaderboard"].drop(columns=["test_start", "test_end"], errors="ignore")
    board2 = result2["leaderboard"].drop(columns=["test_start", "test_end"], errors="ignore")
    pd.testing.assert_frame_equal(
        board1.sort_values(list(board1.columns)).reset_index(drop=True),
        board2.sort_values(list(board2.columns)).reset_index(drop=True),
    )

    conn = sqlite3.connect(db_path)
    n_snapshots = conn.execute("SELECT count(*) FROM snapshot").fetchone()[0]
    n_runs = conn.execute("SELECT count(*) FROM run").fetchone()[0]
    n_trials = conn.execute("SELECT count(*) FROM trial").fetchone()[0]
    n_fold_metrics = conn.execute("SELECT count(*) FROM fold_metric").fetchone()[0]
    n_baselines = conn.execute("SELECT count(*) FROM baseline_metric").fetchone()[0]
    n_predictions = conn.execute("SELECT count(*) FROM prediction").fetchone()[0]

    # deux runs sur données identiques -> un seul snapshot (dédupliqué par hash),
    # mais deux fois plus de runs/trials/predictions (deux exécutions distinctes).
    assert n_snapshots == 1
    assert n_runs == 2 * len(tiny_config.objective.horizons)
    assert n_trials > 0
    assert n_fold_metrics > 0
    assert n_baselines > 0
    assert n_predictions > 0

    statuses = [r[0] for r in conn.execute("SELECT status FROM run").fetchall()]
    assert all(s == "done" for s in statuses)

    best_trials = conn.execute("SELECT count(*) FROM trial WHERE is_best = 1").fetchall()
    assert best_trials[0][0] >= 1  # au moins un trial marqué gagnant sur les deux runs
    conn.close()
