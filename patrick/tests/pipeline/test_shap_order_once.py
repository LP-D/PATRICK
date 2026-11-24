"""B10 : la grille de N d'un même jeu d'entraînement ne refait qu'UN modèle pilote SHAP, et chaque sélection est identique à l'ancienne."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.config.schema import RunConfig
from patrick.pipeline import engine, parallel
from patrick.selection import shap_select
from patrick.selection.registry import select_features
from patrick.tracking import db as trackdb


def _data(seed=0, n=400, p=30):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p))
    score = X[:, 3] + 0.5 * X[:, 7] - 0.3 * X[:, 11] + rng.normal(0, 1, n)
    y = np.digitize(score, np.quantile(score, [0.25, 0.5, 0.75]))          # 4 classes contiguës, comme la cible du moteur
    return X, y


@pytest.fixture
def setup(tmp_path, monkeypatch):
    conn = trackdb.connect(str(tmp_path / "p.db"))
    cfg = RunConfig.model_validate({"name": "t", "objective": {"target_symbol": "AAPL"}, "validation": {"method_version": 2}})
    engine._SHAP_ORDERS.clear()
    calls = []
    real = shap_select.shap_order

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(engine, "shap_order", counted)
    return conn, cfg, calls


def test_the_grid_costs_one_pilot_and_matches_the_old_selection(setup):
    conn, cfg, calls = setup
    X, y = _data()
    for n in (3, 5, 10, 20):
        got = engine._select(conn, "AAPL", 1, "snap", cfg, X, y, n, seed=42)
        old = [int(c) for c in select_features("shap", X, y, n, cfg.features.pool_prefilter, seed=42,
                                                shap_sample=cfg.selection.shap_sample, shap_recent=True)]
        assert got == old
    assert len(calls) == 1


def test_another_training_set_gets_its_own_order(setup):
    conn, cfg, calls = setup
    for seed in (0, 1):
        X, y = _data(seed)
        engine._select(conn, "AAPL", 1, "snap", cfg, X, y, 5, seed=42)
    assert len(calls) == 2


def test_the_parallel_batch_gives_the_same_columns_with_one_order_per_training_set(setup, monkeypatch):
    conn, cfg, _calls = setup
    sent = []
    real = parallel.run_ordered

    def spy(tasks, jobs):
        sent.extend(t[0] for t in tasks)
        return real(tasks, 1)
    monkeypatch.setattr(parallel, "run_ordered", spy)
    X0, y0 = _data(0)
    X1, y1 = _data(1)
    items = [(X0, y0, 3), (X0, y0, 10), (X1, y1, 3), (X1, y1, 10)]
    got = engine._select_batch(conn, "AAPL", 1, "snap", cfg, items, seed=42, jobs=2)
    assert sent == ["shap_order", "shap_order"]
    engine._SHAP_ORDERS.clear()
    seq = [engine._select(trackdb.connect(":memory:"), "AAPL", 1, "s2", cfg, X, y, n, seed=42) for X, y, n in items]
    assert got == seq


def test_the_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(engine, "_SHAP_ORDERS_MAX", 3)
    engine._SHAP_ORDERS.clear()
    for i in range(5):
        engine._remember_shap_order((str(i), "s"), np.arange(3))
    assert list(engine._SHAP_ORDERS) == [("2", "s"), ("3", "s"), ("4", "s")]
