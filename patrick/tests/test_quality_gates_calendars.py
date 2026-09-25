"""Quality gates on REAL calendars -- measured on the real ^GSPC universe
(2026-09-25, default web config): 52 of 66 series excluded, the macro family
nearly emptied. Three calendar defects, none of them a data problem:

1. yfinance coverage was measured on the UNION of the batch's calendars:
   BTC-USD trades on weekends, so every exchange-traded ticker "missed" 2/7
   of the rows since 2014 -- ^VIX excluded at 81.9% "of business days
   populated" while it has no missing business day.
2. FRED gap / stale-tail gates used DAILY thresholds on monthly, weekly and
   quarterly series: GDP was excluded for a "gap of ~66 business days"
   (its quarterly spacing), every monthly series for ~22 days, and the
   October 2025 CPI that was never published (US government shutdown)
   removed CPI entirely.
3. The frozen-price gate (calibrated on quoted prices ~100 with 1.5% daily
   vol) excluded FRED rates that are legitimately flat: DFF for 420 days
   (zero-interest-rate policy), Treasury yields quoted to 0.01. FRED does
   not forward-fill: a stale FRED feed shows up as a stale tail, already
   gated. And percentage returns on series crossing zero (STLFSI4,
   spreads) produced "-46950%" aberrant returns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import ingest as ingest_module
from patrick.data import quality
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore

START = "1990-01-01"


def test_exchange_ticker_is_not_penalised_by_a_weekend_trading_ticker_in_the_batch(monkeypatch):
    days = pd.date_range("2000-01-03", "2020-12-31", freq="D")
    bdays = days[days.dayofweek < 5]
    stock = pd.Series(np.linspace(10, 20, len(bdays)), index=bdays)
    crypto = pd.Series(np.linspace(1, 2, len(days)), index=days)
    batch = pd.DataFrame({"STOCK": stock, "CRYPTO": crypto})
    monkeypatch.setattr(yfinance_source, "download_batch", lambda tickers, start: batch.copy())
    issues: list = []
    out = yfinance_source.download_universe(["STOCK", "CRYPTO"], "2000-01-01", 0.85, issues=issues)
    assert "STOCK" in out.columns
    assert "STOCK" not in {i.series for i in issues}


def _monthly(n=430, first="1990-01-01", missing=()):
    idx = pd.date_range(first, periods=n, freq="MS")
    s = pd.Series(100 + np.cumsum(np.random.default_rng(0).normal(0.2, 0.3, n)), index=idx)
    return s.drop(pd.DatetimeIndex(missing), errors="ignore")


def test_monthly_series_with_one_unpublished_release_passes_the_gap_gate():
    s = _monthly(missing=["2025-10-01"]).rename("CPI")
    assert quality.check_fred_series(s, "CPIAUCSL", requested_end=pd.Timestamp("2025-12-31")) is None


def test_quarterly_gdp_passes_the_gap_and_stale_tail_gates():
    idx = pd.date_range("1990-01-01", "2026-04-01", freq="QS")
    s = pd.Series(np.linspace(5000, 30000, len(idx)), index=idx, name="GDP")
    assert quality.check_fred_series(s, "GDP", requested_end=pd.Timestamp("2026-09-25")) is None


def test_flat_policy_rate_is_not_a_frozen_price():
    idx = pd.bdate_range("2009-01-01", "2015-12-31")
    s = pd.Series(0.12, index=idx, name="DFF")
    s.iloc[::97] = 0.13
    assert quality.check_fred_series(s, "DFF", requested_end=idx[-1]) is None


def test_zero_crossing_index_is_screened_on_differences_not_percent_changes():
    idx = pd.date_range("1994-01-07", periods=1500, freq="W-FRI")
    rng = np.random.default_rng(1)
    s = pd.Series(np.cumsum(rng.normal(0, 0.1, 1500)), index=idx, name="STLFSI4")
    s.iloc[700] = 0.0001
    assert quality.check_fred_series(s, "STLFSI4", requested_end=idx[-1]) is None


def test_a_really_discontinued_monthly_series_is_still_caught():
    s = _monthly(n=200).rename("OLD")
    issue = quality.check_fred_series(s, "OLD_MONTHLY", requested_end=pd.Timestamp("2026-09-25"))
    assert issue is not None and issue.reason == "fin_de_serie_precoce"


def test_a_real_multi_release_gap_is_still_caught():
    missing = pd.date_range("2010-01-01", "2010-08-01", freq="MS")
    s = _monthly(missing=missing).rename("CPI")
    issue = quality.check_fred_series(s, "CPIAUCSL", requested_end=pd.Timestamp("2025-10-31"))
    assert issue is not None and issue.reason == "trou_de_cotation"


def test_ingest_keeps_monthly_and_quarterly_fred_series(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    bidx = pd.bdate_range(START, "2026-09-25")
    monkeypatch.setattr(yfinance_source, "download_target",
                        lambda symbol, start: pd.Series(np.linspace(100, 200, len(bidx)), index=bidx, name="IDX_TGT"))
    gdp_idx = pd.date_range(START, "2026-04-01", freq="QS")
    frames = {"CPI": _monthly(n=441, missing=["2025-10-01"]).rename("CPI"),
              "GDP": pd.Series(np.linspace(5000, 30000, len(gdp_idx)), index=gdp_idx, name="GDP")}
    monkeypatch.setattr(fred_source, "download_fred_universe",
                        lambda series_map, start, **kw: pd.concat([frames[n] for n in series_map], axis=1))
    issues_seen = []
    real = ingest_module._run_extra_quality_checks

    def spy(*a, **k):
        out = real(*a, **k)
        issues_seen.extend(a[3])
        return out

    monkeypatch.setattr(ingest_module, "_run_extra_quality_checks", spy)
    df = ingest_module.ingest(ObjectiveConfig(target_symbol="^TGT"),
                              UniverseConfig(fred_series={"CPI": "CPIAUCSL", "GDP": "GDP"}, start_date=START),
                              store=DataStore(root=str(tmp_path / "store")), force=True,
                              data_quality=DataQualityConfig())
    assert {"CPI", "GDP"} <= set(df.columns), [i.to_dict() for i in issues_seen]


def _yf_batch(values_by_col, idx):
    return pd.DataFrame(values_by_col, index=idx)


def test_holiday_bridge_is_not_frozen_but_a_repeated_reported_close_is(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    idx = pd.bdate_range(START, "2026-09-25")
    rng = np.random.default_rng(3)
    liquid = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx).round(2)
    liquid.iloc[5000:5003] = np.nan
    liquid.iloc[5003] = liquid.iloc[4999]
    frozen = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx).round(2)
    frozen.iloc[3000:3006] = frozen.iloc[2999]
    batch = _yf_batch({"LIQUID": liquid, "FROZEN": frozen}, idx)
    monkeypatch.setattr(yfinance_source, "download_batch", lambda tickers, start: batch.copy())
    monkeypatch.setattr(yfinance_source, "download_target",
                        lambda symbol, start: pd.Series(np.linspace(1, 2, len(idx)), index=idx, name="IDX_TGT"))
    df = ingest_module.ingest(ObjectiveConfig(target_symbol="^TGT"),
                              UniverseConfig(yf_tickers=["LIQUID", "FROZEN"], start_date=START),
                              store=DataStore(root=str(tmp_path / "store")), force=True,
                              data_quality=DataQualityConfig())
    assert "LIQUID" in df.columns
    assert "FROZEN" not in df.columns


def test_rate_near_the_zero_bound_is_screened_on_differences():
    idx = pd.bdate_range("2005-01-03", "2023-12-29")
    rng = np.random.default_rng(5)
    trend = np.interp(np.arange(len(idx)), [0, idx.get_loc(pd.Timestamp("2020-02-28"))], [2.0, 0.1])
    s = pd.Series(np.clip(trend + rng.normal(0, 0.01, len(idx)), 0.01, None), index=idx, name="DTB6")
    s.loc["2020-03-02":"2020-03-27"] = 0.01
    after = s.loc["2020-03-30":].index
    s.loc[after] = np.clip(0.06 + np.cumsum(rng.normal(0, 0.005, len(after))), 0.01, None)
    assert quality.check_fred_series(s, "DTB6", requested_end=idx[-1]) is None
