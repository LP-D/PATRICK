"""Sprint 2 (optimisation exacte) -- le pool paramétrique parallèle reproduit
EXACTEMENT la boucle séquentielle : mêmes colonnes, même ordre, mêmes valeurs
(comparaison exacte, pas de tolérance), même contenu du cache SQLite."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.features import parametric_parallel
from patrick.pipeline import engine
from patrick.tracking import db as trackdb


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "settings.json"))


def _raw(n=500, cols=4, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.DataFrame({f"C{i}": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))) for i in range(cols)}, index=idx)


def _config(models):
    return RunConfig.model_validate({
        "name": "pp", "objective": {"target_symbol": "^C0", "horizons": [1]},
        "features": {"families": ["vol_models", "spike"], "vol_models": models}})


def _vol_rows(conn):
    return conn.execute("SELECT snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash, result_json "
                        "FROM vol_model_cache ORDER BY ticker, model, fit_end_idx").fetchall()


def test_resolve_jobs(monkeypatch):
    monkeypatch.delenv(parametric_parallel.ENV_JOBS, raising=False)
    assert parametric_parallel.resolve_jobs(10) == 1
    monkeypatch.setenv(parametric_parallel.ENV_JOBS, "garbage")
    assert parametric_parallel.resolve_jobs(10) == 1
    monkeypatch.setenv(parametric_parallel.ENV_JOBS, "64")
    assert parametric_parallel.resolve_jobs(3) <= 3


@pytest.mark.slow
@pytest.mark.parametrize("with_cache", [False, True])
def test_parallel_parametric_pool_is_identical_to_sequential(tmp_path, monkeypatch, with_cache):
    monkeypatch.setenv("PATRICK_FEATURE_CACHE", "0")      # comparer les calculs, pas le cache disque
    raw, cfg = _raw(), _config(["kalman", "hmm"])
    kw = {"fit_end_idx": 300, "test_end_idx": 420}

    def build(jobs, name):
        monkeypatch.setenv(parametric_parallel.ENV_JOBS, str(jobs))
        conn = trackdb.connect(str(tmp_path / f"{name}.db")) if with_cache else None
        pool = engine.build_parametric_pool(raw, cfg, conn=conn, snapshot_id="snap" if with_cache else None, **kw)
        return pool, conn

    seq, conn_s = build(1, "seq")
    par, conn_p = build(2, "par")
    pd.testing.assert_frame_equal(seq, par, check_exact=True)
    assert list(seq.columns) == list(par.columns)
    if with_cache:
        assert _vol_rows(conn_s) == _vol_rows(conn_p) and len(_vol_rows(conn_s)) == 8
        again, _ = build(2, "par")                      # 2e passage : lectures en cache côté parent
        pd.testing.assert_frame_equal(seq, again, check_exact=True)
