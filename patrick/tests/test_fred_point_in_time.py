"""F01 -- FRED series must enter the feature frame on the date they were
PUBLISHED, not on their reference date.

FRED indexes an observation by the start of the period it describes: the
January 2020 CPI is dated 2020-01-01 but was released by the BLS mid-February.
`ingest` joined FRED series with `reindex(..., method="ffill")` on that
reference date: every walk-forward row between Jan 1 and mid-February "knew"
a CPI print that did not exist yet -- a look-ahead of ~6 weeks on every
monthly series, ~4 months on GDP, one business day on daily series (which
also breaks backtest/live parity: live scoring only ever sees yesterday's
FRED value).

Fix: every observation is re-indexed to its availability date
(`data/publication_lag.py`): end of the reference period + a conservative
publication delay per series; through the ALFRED API (FRED_API_KEY set,
`fred_point_in_time="alfred"`), the first-release value indexed on its real
`realtime_start` instead (removes the revision look-ahead as well).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import ingest as ingest_module
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore

START = "1990-01-01"


def _monthly(first="1990-01-01", n=400, name="CPI"):
    idx = pd.date_range(first, periods=n, freq="MS")
    return pd.Series(np.arange(n, dtype=float) + 100.0, index=idx, name=name)


@pytest.fixture
def fake_sources(monkeypatch):
    def fake_target(symbol, start):
        idx = pd.bdate_range(START, "2023-06-30")
        return pd.Series(np.linspace(100, 200, len(idx)), index=idx, name="IDX_TGT")

    def fake_fred_universe(series_map, start, realtime_date=None, issues=None, **kwargs):
        return pd.concat([series_map_series[name] for name in series_map], axis=1)

    series_map_series = {}
    monkeypatch.setattr(yfinance_source, "download_target", fake_target)
    monkeypatch.setattr(fred_source, "download_fred_universe", fake_fred_universe)
    return series_map_series


def _ingest(tmp_path, fred_series):
    return ingest_module.ingest(
        ObjectiveConfig(target_symbol="^TGT"),
        UniverseConfig(yf_tickers=[], fred_series=fred_series, start_date=START),
        store=DataStore(root=str(tmp_path / "store")), force=True,
        data_quality=DataQualityConfig(enabled=False))


def test_monthly_cpi_is_not_visible_before_its_release(tmp_path, fake_sources, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    fake_sources["CPI"] = _monthly(name="CPI")
    df = _ingest(tmp_path, {"CPI": "CPIAUCSL"})
    jan_2020 = float(fake_sources["CPI"].loc["2020-01-01"])
    first_seen = df.index[df["CPI"] == jan_2020].min()
    assert first_seen >= pd.Timestamp("2020-02-10"), f"January 2020 CPI visible on {first_seen.date()}"
    assert first_seen <= pd.Timestamp("2020-03-06")


def test_quarterly_gdp_waits_for_the_advance_estimate(tmp_path, fake_sources, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    idx = pd.date_range("1990-01-01", periods=140, freq="QS")
    fake_sources["GDP"] = pd.Series(np.arange(140, dtype=float), index=idx, name="GDP")
    df = _ingest(tmp_path, {"GDP": "GDP"})
    q1_2020 = float(fake_sources["GDP"].loc["2020-01-01"])
    first_seen = df.index[df["GDP"] == q1_2020].min()
    assert first_seen >= pd.Timestamp("2020-04-28")


def test_daily_series_is_shifted_by_one_business_day(tmp_path, fake_sources, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    idx = pd.bdate_range(START, "2023-06-30")
    fake_sources["US10Y_Rate"] = pd.Series(np.arange(len(idx), dtype=float), index=idx, name="US10Y_Rate")
    df = _ingest(tmp_path, {"US10Y_Rate": "DGS10"})
    value_dated = float(fake_sources["US10Y_Rate"].loc["2020-03-02"])
    first_seen = df.index[df["US10Y_Rate"] == value_dated].min()
    assert first_seen == pd.Timestamp("2020-03-03")


@pytest.mark.parametrize("series_id, obs, earliest", [
    ("CPIAUCSL", "2020-01-01", "2020-02-10"),
    ("PAYEMS", "2020-01-01", "2020-02-07"),
    ("PCE", "2020-01-01", "2020-02-28"),
    ("GDP", "2020-01-01", "2020-04-28"),
    ("NFCI", "2020-01-03", "2020-01-08"),
    ("DGS10", "2020-01-02", "2020-01-03"),
])
def test_availability_dates_are_never_before_the_real_release(series_id, obs, earliest):
    from patrick.data import publication_lag

    s = pd.Series([1.0], index=pd.DatetimeIndex([obs]))
    out = publication_lag.to_availability_index(s, series_id)
    assert out.index[0] >= pd.Timestamp(earliest)


def test_unknown_series_frequency_is_inferred_and_lagged_conservatively():
    from patrick.data import publication_lag

    s = _monthly(n=24)
    out = publication_lag.to_availability_index(s, "SOME_UNKNOWN_ID")
    assert (out.index > s.index + pd.offsets.MonthEnd(0)).all()


def test_alfred_first_release_is_indexed_on_its_realtime_start(monkeypatch):
    """ALFRED `output_type=4` (initial release only): each observation's
    first published value, with `realtime_start` = its release date."""
    payload = {"observations": [
        {"date": "2020-01-01", "realtime_start": "2020-02-13", "value": "258.8"},
        {"date": "2020-02-01", "realtime_start": "2020-03-11", "value": "259.1"},
        {"date": "2020-03-01", "realtime_start": "2020-04-10", "value": "."},
    ]}
    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return _Resp()

    monkeypatch.setattr(fred_source.requests, "get", fake_get)
    s = fred_source.download_first_release("CPIAUCSL", "2020-01-01", api_key="k")
    assert seen["output_type"] == 4
    assert list(s.index) == [pd.Timestamp("2020-02-13"), pd.Timestamp("2020-03-11")]
    assert list(s.values) == [258.8, 259.1]


def test_reference_date_mode_reproduces_the_pre_f01_leak_for_the_audit_only(tmp_path, fake_sources, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    fake_sources["CPI"] = _monthly(name="CPI")
    df = ingest_module.ingest(
        ObjectiveConfig(target_symbol="^TGT"),
        UniverseConfig(fred_series={"CPI": "CPIAUCSL"}, start_date=START, fred_point_in_time="reference_date"),
        store=DataStore(root=str(tmp_path / "store")), force=True, data_quality=DataQualityConfig(enabled=False))
    jan_2020 = float(fake_sources["CPI"].loc["2020-01-01"])
    assert df.index[df["CPI"] == jan_2020].min() == pd.Timestamp("2020-01-01")


def test_a_cache_built_under_another_point_in_time_rule_is_never_served(tmp_path, fake_sources, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    fake_sources["CPI"] = _monthly(name="CPI")
    store = DataStore(root=str(tmp_path / "store"))
    legacy = pd.DataFrame({"IDX_TGT": [1.0, 2.0]}, index=pd.bdate_range("2020-01-01", periods=2))
    store.save("raw_^TGT", legacy)
    df = ingest_module.ingest(ObjectiveConfig(target_symbol="^TGT"),
                              UniverseConfig(fred_series={"CPI": "CPIAUCSL"}, start_date=START),
                              store=store, data_quality=DataQualityConfig(enabled=False))
    assert len(df) > 2
    again = ingest_module.ingest(ObjectiveConfig(target_symbol="^TGT"),
                                 UniverseConfig(fred_series={"CPI": "CPIAUCSL"}, start_date=START),
                                 store=store, data_quality=DataQualityConfig(enabled=False))
    assert again.attrs["snapshot_id"] == df.attrs["snapshot_id"]


def test_local_cache_hit_is_registered_in_the_data_lake(tmp_path, fake_sources, monkeypatch):
    """The CACHE_LOCAL path used to return a frame the data lake never saw:
    the run then recorded an ad hoc snapshot_id that `/simulate` and
    `explain` could not reload."""
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    fake_sources["CPI"] = _monthly(name="CPI")
    universe = UniverseConfig(fred_series={"CPI": "CPIAUCSL"}, start_date=START)
    ingest_module.ingest(ObjectiveConfig(target_symbol="^TGT"), universe,
                         store=DataStore(root=str(tmp_path / "store_a")), force=True,
                         data_quality=DataQualityConfig(enabled=False))
    fresh_store = DataStore(root=str(tmp_path / "store_b"))
    df = ingest_module.ingest(ObjectiveConfig(target_symbol="^TGT"), universe, store=fresh_store,
                              data_quality=DataQualityConfig(enabled=False))
    reloaded = fresh_store.load("raw_^TGT", snapshot_id=df.attrs["snapshot_id"])
    assert len(reloaded) == len(df)
