"""Found by the slow web smoke test on 2026-09-26 (real data, start 2015):
two FRED series of the default universe were discontinued -- DTB1 (last
observation 2001-08-24) and OILPRICE (2013-07-01); both removed the same
day. From any start date after their end, FRED returns an EMPTY series,
which `download_fred_universe` kept as an all-NaN column (only `None`
counted as missing on this path, unlike
the ALFRED path which already checked `.empty`). The Kalman feature then
crashed the whole run: `ValueError: array must not contain infs or NaNs`
(pykalman -> scipy.linalg.pinv), phase "features".

Two guards: an empty series is a missing series (quality issue, no column),
and the Kalman feature returns NaN on a series without a finite value,
like EGARCH already does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.data.sources import fred_source
from patrick.features.vol_models import kalman_filtered_level


def test_empty_fred_series_is_missing_not_an_all_nan_column(monkeypatch):
    idx = pd.bdate_range("2015-01-01", periods=30)

    def fake_download(name, sid, start, realtime_date=None):
        if sid == "DTB1":
            return pd.Series(dtype=float, name=name)
        return pd.Series(np.arange(30, dtype=float), index=idx, name=name)

    monkeypatch.setattr(fred_source, "download_series", fake_download)
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)
    issues = []
    frame = fred_source.download_fred_universe({"US1M_Rate": "DTB1", "NFCI": "NFCI"}, "2015-01-01",
                                               issues=issues)
    assert list(frame.columns) == ["NFCI"]
    assert [(i.series, i.reason) for i in issues] == [("US1M_Rate", "fred_absent_ou_discontinue")]


def test_kalman_feature_on_a_series_without_any_finite_value_is_nan_not_a_crash():
    idx = pd.bdate_range("2015-01-01", periods=100)
    out = kalman_filtered_level(pd.Series(np.nan, index=idx), fit_end_idx=60)
    assert out.isna().all() and len(out) == 100
    inf = pd.Series([np.inf] * 100, index=idx)
    assert kalman_filtered_level(inf, fit_end_idx=60).isna().all()


def test_kalman_feature_ignores_isolated_infinite_values():
    idx = pd.bdate_range("2015-01-01", periods=100)
    s = pd.Series(np.linspace(1, 2, 100), index=idx)
    s.iloc[50] = np.inf
    out = kalman_filtered_level(s, fit_end_idx=60)
    assert np.isfinite(out).all()


def test_discontinued_series_are_out_of_the_default_universe():
    """User decision (2026-09-26): DTB1 and OILPRICE removed, DTB4WK (4-week
    T-bill, published daily) replaces DTB1 as the 1-month bill rate."""
    from patrick.config import defaults as D
    from patrick.data import publication_lag

    fred_ids = set(D.DEFAULT_UNIVERSE_FRED_SERIES.values())
    assert not fred_ids & {"DTB1", "OILPRICE"}
    assert D.DEFAULT_UNIVERSE_FRED_SERIES.get("US4W_Rate") == "DTB4WK"
    assert publication_lag.frequency_of("DTB4WK", pd.DatetimeIndex([])) == "daily"
