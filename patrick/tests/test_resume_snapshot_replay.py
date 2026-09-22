"""`patrick resume` must replay EXACTLY the data of the run's original
snapshot (`run.snapshot_id`), never the latest snapshot available for the
same key -- otherwise a resumed run silently trains on a different FRED
vintage / Yahoo revision than the one it was launched on, and its trials
are no longer comparable with those already persisted before the
interruption."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick import cli
from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module
from patrick.tracking import db as trackdb


class _StopAfterIngest(Exception):
    """Raised by the spy to stop `run_pipeline` right after data loading --
    the test only cares about which data reached feature construction."""


def _raw(value_shift: float) -> pd.DataFrame:
    idx = pd.bdate_range("2000-01-03", periods=300)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"IDX_TEST": 15 + np.cumsum(rng.normal(0, 0.5, 300))}, index=idx)
    df["NFCI"] = np.linspace(0.0, 1.0, 300) + value_shift
    return df


def _config(tmp_path) -> RunConfig:
    return RunConfig.model_validate({
        "name": "resume_replay",
        "objective": {"target_symbol": "^TEST", "horizons": [3], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": [], "fred_series": {"NFCI": "NFCI"}, "start_date": "2000-01-01"},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    })


def _no_network(*args, **kwargs):
    raise AssertionError("resume must not hit the network: the run's snapshot is already local")


def test_resume_replays_original_snapshot_not_latest(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    store_root = str(tmp_path / "store")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", store_root)
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    from patrick.data.sources import fred_source, yfinance_source
    monkeypatch.setattr(yfinance_source, "download_target", _no_network)
    monkeypatch.setattr(fred_source, "download_series", _no_network)

    store = DataStore(root=store_root)
    config = _config(tmp_path)

    # (a) Run launched on snapshot A (frozen mocked data).
    raw_a = _raw(value_shift=0.0)
    snapshot_a = store.save("raw_^TEST", raw_a)
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, snapshot_a, raw_a.attrs["data_hash"], 0, 1, "api")
    trackdb.create_run(conn, "resume_replay_h3_deadbeef", target="^TEST", horizon=3,
                       snapshot_id=snapshot_a, config_json=config.model_dump_json(),
                       config_hash="x", git_sha="x", seed=42)
    conn.close()

    # (b) A newer FRED vintage lands in the store: snapshot B, different content.
    raw_b = _raw(value_shift=100.0)
    snapshot_b = store.save("raw_^TEST", raw_b)
    assert snapshot_b != snapshot_a
    assert store.latest_snapshot_id("raw_^TEST") == snapshot_b

    seen: dict = {}

    def spy_base_pool(raw, cfg, target_col):
        seen["raw"] = raw.copy()
        seen["snapshot_id"] = raw.attrs.get("snapshot_id")
        raise _StopAfterIngest()

    monkeypatch.setattr(engine_module, "build_base_feature_pool", spy_base_pool)

    # (c) resume the run.
    with pytest.raises(_StopAfterIngest):
        cli.resume_cmd(run_id="resume_replay_h3_deadbeef")

    # (d) the data used is snapshot A's, not B's.
    assert seen["snapshot_id"] == snapshot_a
    pd.testing.assert_frame_equal(seen["raw"], raw_a, check_freq=False)


def test_run_pipeline_rejects_unknown_snapshot_instead_of_falling_back_to_latest(tmp_path, monkeypatch):
    """A resumed run whose snapshot is no longer in the store must fail
    loudly -- silently replaying `latest` is exactly the bug being fixed."""
    store = DataStore(root=str(tmp_path / "store"))
    store.save("raw_^TEST", _raw(value_shift=0.0))
    monkeypatch.setattr(engine_module, "build_base_feature_pool",
                        lambda *a, **k: pytest.fail("must not reach feature construction"))
    with pytest.raises(FileNotFoundError, match="introuvable"):
        engine_module.run_pipeline(_config(tmp_path), store=store,
                                   db_path=str(tmp_path / "patrick.db"),
                                   snapshot_id="1999-01-01__raw_IDX_TEST__000000000000")
