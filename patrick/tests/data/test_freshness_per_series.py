"""The freshness dashboard could only observe tickers that had themselves
been a run TARGET: `ingest` saves one joined frame under `raw_<target>`, its
feature columns forward-filled (the real last observation is lost). Measured
on the real data lake: 3 of the 68 configured tickers observable.

Every ingestion now records, per series of the universe, the date of its last
REALLY published observation (before any forward fill) in the data lake
(`DataStore.record_series_observations`); `compute_freshness` reads it for
any series that was never a target.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import freshness
from patrick.data import ingest as ingest_module
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore

START = "1990-01-01"


def _ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    idx = pd.bdate_range(START, "2024-06-28")
    gold = pd.Series(np.linspace(300, 2300, len(idx)), index=idx)
    gold.loc["2024-06-20":] = np.nan
    batch = pd.DataFrame({"GC=F": gold, "IDX_VIX": np.linspace(10, 20, len(idx))}, index=idx)
    monkeypatch.setattr(yfinance_source, "download_batch", lambda tickers, start: batch.copy())
    monkeypatch.setattr(yfinance_source, "download_target",
                        lambda symbol, start: pd.Series(np.linspace(1, 2, len(idx)), index=idx, name="IDX_GSPC"))
    cpi = pd.Series(np.arange(413, dtype=float), index=pd.date_range(START, periods=413, freq="MS"), name="CPI")
    monkeypatch.setattr(fred_source, "download_fred_universe", lambda series_map, start, **kw: cpi.to_frame())
    store = DataStore(root=str(tmp_path / "store"))
    ingest_module.ingest(ObjectiveConfig(target_symbol="^GSPC"),
                         UniverseConfig(yf_tickers=["GC=F", "^VIX"], fred_series={"CPI": "CPIAUCSL"},
                                        start_date=START),
                         store=store, force=True, data_quality=DataQualityConfig(enabled=False))
    return store


def test_universe_tickers_that_were_never_targets_become_observable(tmp_path, monkeypatch):
    store = _ingest(tmp_path, monkeypatch)
    gold = freshness.compute_freshness("GC=F", "Gold_Futures", "yfinance", store=store,
                                       as_of=pd.Timestamp("2024-07-01"))
    assert gold.cached
    assert pd.Timestamp(gold.date_max) == pd.Timestamp("2024-06-19")
    vix = freshness.compute_freshness("^VIX", "VIX_Price", "yfinance", store=store,
                                      as_of=pd.Timestamp("2024-07-01"))
    assert pd.Timestamp(vix.date_max) == pd.Timestamp("2024-06-28")


def test_fred_series_freshness_uses_its_last_reference_date(tmp_path, monkeypatch):
    store = _ingest(tmp_path, monkeypatch)
    cpi = freshness.compute_freshness("CPIAUCSL", "CPI", "fred", store=store, as_of=pd.Timestamp("2024-07-01"))
    assert cpi.cached
    assert pd.Timestamp(cpi.date_max) == pd.Timestamp("2024-05-01")
    assert cpi.state == "ok"


def test_recorded_observation_never_moves_backwards(tmp_path):
    store = DataStore(root=str(tmp_path / "store"))
    store.record_series_observations({"GC=F": "2024-06-19"}, source="yfinance")
    store.record_series_observations({"GC=F": "2024-05-01"}, source="yfinance")
    assert store.series_observation("GC=F")["date_max"] == "2024-06-19"


def test_fred_series_really_behind_its_release_calendar_is_a_warning(tmp_path):
    store = DataStore(root=str(tmp_path / "store"))
    store.record_series_observations({"CPIAUCSL": "2024-01-01"}, source="fred")
    cpi = freshness.compute_freshness("CPIAUCSL", "CPI", "fred", store=store, as_of=pd.Timestamp("2024-07-01"))
    assert cpi.state == "warning"
