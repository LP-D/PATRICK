"""CPCV : les formules d'interaction d'une combinaison ne doivent rien lire de ses groupes de test.

Constat de l'audit du 2026-10-19. `_run_cpcv_scan` découvrait les formules UNE fois, sur le groupe 0 (étiquettes
comprises). Or le groupe 0 est un groupe de TEST dans 6 combinaisons sur 21 (7 groupes, k=2) : le choix des
variables d'interaction de ces combinaisons était informé par les étiquettes qu'on prétendait prédire. Chaque
combinaison découvre désormais ses formules sur ses seules lignes d'entraînement (purgées et mises sous embargo).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.pipeline import engine
from patrick.validation import cpcv

TARGET = "tgt"
HORIZON = 5


def _config() -> RunConfig:
    return RunConfig.model_validate({
        "name": "t", "objective": {"target_symbol": "X", "target_source": "yfinance", "horizons": [HORIZON]},
        "features": {"interact_top_base": 6, "interact_top_pairs": 4, "interact_final_n": 5},
        "output": {"dir": "out", "seed": 42}})


def _data(n: int = 520, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    pool = pd.DataFrame(rng.standard_normal((n, 8)), index=idx, columns=[f"f{i}" for i in range(8)])
    pool[TARGET] = 100 + np.cumsum(rng.standard_normal(n))
    signal = pool["f0"] * pool["f1"] + 0.5 * rng.standard_normal(n)
    y = pd.Series(np.digitize(signal, np.quantile(signal, [0.25, 0.5, 0.75])), index=idx)
    return pool, y


def _garble(pool: pd.DataFrame, y: pd.Series, rows: np.ndarray) -> tuple[pd.DataFrame, pd.Series]:
    """Copie où les lignes `rows` (features ET étiquettes) sont remplacées par autre chose."""
    rng = np.random.default_rng(999)
    pool2, y2 = pool.copy(), y.copy()
    feature_cols = [c for c in pool.columns if c != TARGET]
    pool2.loc[rows, feature_cols] = rng.standard_normal((int(rows.sum()), len(feature_cols))) * 5
    y2[rows] = 3 - y2[rows]
    return pool2, y2


def test_discovery_reads_only_the_rows_it_is_given():
    pool, y = _data()
    cfg = _config()
    rows = np.zeros(len(y), dtype=bool)
    rows[:300] = True
    pool2, y2 = _garble(pool, y, ~rows)

    assert engine._discover_formulas_on_rows(pool2, y2, rows, cfg, TARGET) == \
        engine._discover_formulas_on_rows(pool, y, rows, cfg, TARGET)
    # Contrôle : le bouleversement est bien visible quand les lignes sont autorisées (le test n'est pas vacant).
    everything = np.ones(len(y), dtype=bool)
    assert engine._discover_formulas_on_rows(pool2, y2, everything, cfg, TARGET) != \
        engine._discover_formulas_on_rows(pool, y, everything, cfg, TARGET)


def test_each_cpcv_combination_gets_formulas_discovered_without_its_test_groups():
    pool, y = _data()
    cfg = _config()
    groups = cpcv.build_groups(len(pool), 4)
    combos = cpcv.all_combinations(4, 2)
    base = engine._cpcv_interaction_formulas(pool, y, cfg, TARGET, groups, combos, HORIZON, None)
    assert set(base) == set(combos)
    for combo in combos:
        split = cpcv.build_split(groups, combo, HORIZON, None)
        outside_train = ~np.asarray(y.index.isin(pool.index[split.train_mask]))
        assert outside_train.any()
        pool2, y2 = _garble(pool, y, outside_train)
        again = engine._cpcv_interaction_formulas(pool2, y2, cfg, TARGET, groups, [combo], HORIZON, None)
        assert again[combo] == base[combo], f"combination {combo}: formulas depend on rows outside its training set"


def test_a_combination_only_sees_its_own_interaction_columns():
    feature_pool = ["a", "b", "a__prod__b", "a__minus__b", "b__sum__a"]
    out = engine._combo_feature_pool(feature_pool, all_formulas=["a__prod__b", "a__minus__b", "b__sum__a"],
                                     combo_formulas=["a__minus__b"])
    assert out == ["a", "b", "a__minus__b"]


@pytest.mark.slow
def test_cpcv_scan_discovers_each_combinations_formulas_on_its_training_bars(tmp_path, monkeypatch):
    """Le scan réel : chaque combinaison a SA découverte, qui ne voit aucune ligne de ses groupes de test (ni de sa
    zone purgée). Avant : une seule découverte, sur le groupe 0 -- groupe de test de 4 combinaisons sur 10 ici."""
    from test_run_pipeline_golden import _config, _raw

    from patrick.data.store import DataStore

    raw = _raw()
    monkeypatch.setattr(engine, "ingest", lambda *a, **k: raw.copy())
    monkeypatch.setattr(engine, "download_ohlc", lambda *a, **k: None)
    seen: list[set] = []
    real = engine.discover_interactions

    def spy(X_df, y, *args, **kwargs):
        seen.append(set(X_df.index))
        return real(X_df, y, *args, **kwargs)

    monkeypatch.setattr(engine, "discover_interactions", spy)
    config = _config(tmp_path, "cpcv")
    engine.run_pipeline(config, store=DataStore(root=str(tmp_path / "s")), db_path=str(tmp_path / "patrick.db"))

    groups = cpcv.build_groups(len(raw), config.validation.n_groups)
    horizon = max(config.objective.horizons)
    for combo in cpcv.all_combinations(config.validation.n_groups, config.validation.k_test_groups):
        split = cpcv.build_split(groups, combo, horizon, config.validation.embargo_bars)
        train_dates = set(raw.index[split.train_mask])
        assert any(rows <= train_dates for rows in seen), f"combination {combo}: no discovery avoided its test groups"
