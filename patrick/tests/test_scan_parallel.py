"""Sprint 2 (optimisation exacte) -- sélection + fits du scan en parallèle :
mêmes artefacts (digests) que l'exécution séquentielle, walk-forward et CPCV."""
from __future__ import annotations

import os

import numpy as np
import pytest

from patrick import settings
from patrick.benchmark import artifacts, reference, runner
from patrick.config.schema import RunConfig
from patrick.pipeline import engine, parallel
from patrick.tracking import db as trackdb


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.delenv(parallel.ENV_JOBS, raising=False)


def test_resolve_jobs_precedence(monkeypatch):
    assert parallel.resolve_jobs() == 1
    settings.save({settings.KEY_SCAN_JOBS: 2})
    assert parallel.resolve_jobs() == min(2, os.cpu_count() or 1)
    monkeypatch.setenv(parallel.ENV_JOBS, "1")
    assert parallel.resolve_jobs() == 1
    monkeypatch.setenv(parallel.ENV_JOBS, "x")
    assert parallel.resolve_jobs() == 1


def test_run_ordered_keeps_task_order():
    tasks = [(pow, (i, 2), {}) for i in range(7)]
    assert parallel.run_ordered(tasks, 1) == [i * i for i in range(7)]
    assert parallel.run_ordered(tasks, 2) == [i * i for i in range(7)]


@pytest.mark.slow
def test_select_batch_equals_sequential_selects(tmp_path):
    cfg = RunConfig.model_validate({"name": "sb", "objective": {"target_symbol": "^X", "horizons": [1]},
                                    "selection": {"method": "shap", "shap_sample": 60}})
    rng = np.random.default_rng(1)
    X, y = rng.normal(size=(200, 12)), rng.integers(0, 3, 200)
    items = [(X, y, 4), (X, y, 6), (X, y, 4), (X[:150], y[:150], 5)]       # un doublon, deux jeux de données
    conn_a, conn_b = trackdb.connect(str(tmp_path / "a.db")), trackdb.connect(str(tmp_path / "b.db"))
    seq = engine._select_batch(conn_a, "T", 1, "snap", cfg, items, 42, 1)
    par = engine._select_batch(conn_b, "T", 1, "snap", cfg, items, 42, 2)
    assert seq == par and seq[0] == seq[2]
    rows = "SELECT data_hash, selector_config_hash, selected_columns FROM shap_selection_cache ORDER BY 1, 2"
    assert conn_a.execute(rows).fetchall() == conn_b.execute(rows).fetchall()


@pytest.mark.slow
@pytest.mark.parametrize("scheme", ["walkforward", "cpcv"])
def test_parallel_scan_gives_identical_artifacts(tmp_path, scheme):
    spec = reference.TINY
    runner.run_scenario(spec, scheme, tmp_path / "seq", baseline_dir=tmp_path / "b_seq", instrument=False)
    runner.run_scenario(spec, scheme, tmp_path / "par", baseline_dir=tmp_path / "b_par", instrument=False,
                        extra_env={parallel.ENV_JOBS: "2"})
    cmp = artifacts.compare_baselines(str(tmp_path / "b_seq"), str(tmp_path / "b_par"))
    assert cmp["identical"], cmp
