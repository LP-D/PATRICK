"""Phase 5.3 -- infrastructure pour comparer SMOTE (suréchantillonnage) à
`class_weight="balanced"` SEUL (le pseudo-sampler `"none"`, cf.
`models/samplers.py`). L'A/B test EMPIRIQUE sur 5 cibles réelles (le
livrable demandé par le plan) ne peut pas être exécuté dans ce sandbox : pas
d'accès réseau à yfinance/FRED (vérifié -- toute requête sortante vers ces
domaines échoue). Ces tests vérifient seulement que le mécanisme lui-même
fonctionne (pas de conclusion empirique tirée de données synthétiques, qui
n'ont pas de structure exploitable réelle) ; cf. METHODOLOGY.md/rapport de
phase pour la marche à suivre en environnement avec accès réseau.
"""
from __future__ import annotations

import numpy as np
import pytest

from patrick.models.samplers import ALL_SAMPLERS, get_sampler


def test_none_sampler_returns_data_unchanged():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 4))
    y = rng.integers(0, 2, size=50)
    Xr, yr = get_sampler("none", seed=42).fit_resample(X, y)
    assert np.array_equal(Xr, X)
    assert np.array_equal(yr, y)


def test_none_is_listed_alongside_smote():
    assert "none" in ALL_SAMPLERS
    assert "SMOTE" in ALL_SAMPLERS


@pytest.mark.slow  # ~11.4s mesuré (rapport de correction, D1) : run pipeline complet
def test_pipeline_accepts_none_in_sampler_grid(tmp_path, monkeypatch):
    """Bout-en-bout (données synthétiques, sans réseau) : une config avec
    `sampler.candidates: ["SMOTE", "none"]` tourne sans erreur et produit des
    lignes de leaderboard pour les deux -- la mécanique de comparaison est
    utilisable telle quelle dès qu'un accès réseau réel est disponible."""
    import pandas as pd
    from patrick.config.schema import RunConfig
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module

    def _synthetic_raw(n=800, seed=0) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        idx = pd.bdate_range("2018-01-01", periods=n)
        target = 100 + np.cumsum(rng.normal(0, 0.5, n))
        df = pd.DataFrame({"IDX_TEST": target}, index=idx)
        df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
        df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
        df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
        return df

    monkeypatch.setattr(engine_module, "ingest",
                         lambda objective, universe, store=None, force=False: _synthetic_raw())

    config = RunConfig.model_validate({
        "name": "ab_test_smoke",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2018-01-01",
        },
        "features": {"families": ["technical"], "interact_top_base": 15,
                     "interact_top_pairs": 8, "interact_final_n": 6, "pool_prefilter": 60},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE", "none"]},
        "models": {"algos": ["RandomForest"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    })
    result = engine_module.run_pipeline(
        config, store=DataStore(root=str(tmp_path / "store")), db_path=str(tmp_path / "patrick.db"))
    board = result["leaderboard"]
    # baselines systématiques (Phase 0.6) partagent le même leaderboard mais
    # n'ont pas de colonne `sampler` (NaN) -- exclues de la comparaison.
    assert set(board["sampler"].dropna().unique()) == {"SMOTE", "none"}
