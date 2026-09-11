"""Unit tests for `webapp/asset_stats.py::compute_stats` -- the per-asset
stats panel backing `/commodities` and `/macro` (feature/ticker-stats-panel).
No network, no ML pipeline: `compute_stats` takes exactly the dict shape
`market_data.price_history()` returns and computes display stats from it
directly, so these tests build that dict by hand (deterministic synthetic
series) rather than seeding the tracking DB or hitting yfinance/FRED."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.defaults import DEFAULT_HORIZONS
from patrick.webapp import asset_stats


def _series(n: int, start=100.0, daily_growth=0.0, seed=0, noise=0.0) -> dict:
    dates = pd.bdate_range("2020-01-01", periods=n)
    if noise:
        rng = np.random.default_rng(seed)
        vals = start * np.cumprod(1 + daily_growth + rng.normal(0, noise, n))
    else:
        vals = start * np.cumprod(np.full(n, 1 + daily_growth))
    return {"dates": [d.strftime("%Y-%m-%d") for d in dates], "closes": [float(v) for v in vals]}


def test_insufficient_history_flags_and_returns_no_stats():
    series = _series(10)  # < MIN_HISTORY_FOR_STATS (30)
    out = asset_stats.compute_stats(series)
    assert out["insufficient_history"] is True
    assert out["returns"] == {}
    assert out["long_window_returns"] == {}
    assert out["zscore_60d"] is None
    assert out["moving_averages"] == {}
    assert out["volatility"] is None
    assert out["n_obs"] == 10


def test_upstream_error_is_passed_through_without_crashing():
    series = {"dates": [], "closes": [], "error": "boom"}
    out = asset_stats.compute_stats(series)
    assert out["error"] == "boom"
    assert out["insufficient_history"] is True
    assert out["returns"] == {}


def test_empty_series_does_not_crash():
    out = asset_stats.compute_stats({"dates": [], "closes": []})
    assert out["n_obs"] == 0
    assert out["insufficient_history"] is True


def test_returns_use_default_horizons_and_are_zero_on_flat_series():
    series = _series(120, start=50.0, daily_growth=0.0)
    out = asset_stats.compute_stats(series)
    assert set(out["returns"].keys()) == {str(h) for h in DEFAULT_HORIZONS}
    for h in DEFAULT_HORIZONS:
        assert out["returns"][str(h)] == pytest.approx(0.0, abs=1e-9)


def test_returns_positive_on_steadily_rising_series():
    series = _series(120, start=100.0, daily_growth=0.01)  # +1%/bar, no noise
    out = asset_stats.compute_stats(series)
    for h in DEFAULT_HORIZONS:
        expected = (1.01 ** h) - 1
        assert out["returns"][str(h)] == pytest.approx(expected, rel=1e-6)


def test_long_window_returns_present_for_long_enough_series():
    series = _series(300, start=100.0, daily_growth=0.001)
    out = asset_stats.compute_stats(series)
    assert set(out["long_window_returns"].keys()) == {str(w) for w in asset_stats.LONG_WINDOWS_BARS}
    for v in out["long_window_returns"].values():
        assert v is not None


def test_long_window_returns_none_when_series_shorter_than_window():
    # 50 bars: long enough for the 21-bar window (needs >= 22), too short
    # for 63/252.
    series = _series(50, start=100.0, daily_growth=0.001)
    out = asset_stats.compute_stats(series)
    assert out["long_window_returns"]["21"] is not None
    assert out["long_window_returns"]["63"] is None
    assert out["long_window_returns"]["252"] is None


def test_zscore_is_none_on_flat_series_zero_std():
    # Flat series -> rolling std is 0 -> technical.zscore divides by NaN
    # (0 replaced by NaN) -- must surface as None, not NaN/inf leaking into
    # the JSON response.
    series = _series(120, start=42.0, daily_growth=0.0)
    out = asset_stats.compute_stats(series)
    assert out["zscore_60d"] is None


def test_zscore_present_and_finite_on_noisy_series():
    series = _series(150, start=100.0, daily_growth=0.0, noise=0.01, seed=1)
    out = asset_stats.compute_stats(series)
    assert out["zscore_60d"] is not None
    assert np.isfinite(out["zscore_60d"])


def test_moving_averages_use_configured_windows():
    series = _series(250, start=100.0, daily_growth=0.002)
    out = asset_stats.compute_stats(series)
    assert set(out["moving_averages"].keys()) == {str(w) for w in asset_stats.MA_WINDOWS}
    # Rising series: price sits above each of its (lagging) moving averages.
    for v in out["moving_averages"].values():
        assert v is not None
        assert v > 0


def test_moving_average_none_when_series_shorter_than_window():
    series = _series(100, start=100.0, daily_growth=0.001)  # < MA_WINDOWS max (200)
    out = asset_stats.compute_stats(series)
    assert out["moving_averages"]["20"] is not None
    assert out["moving_averages"]["200"] is None


def test_volatility_absent_below_min_history():
    series = _series(50, start=100.0, daily_growth=0.0, noise=0.01, seed=2)
    out = asset_stats.compute_stats(series)
    assert out["volatility"] is None


def test_volatility_present_and_positive_above_min_history():
    series = _series(150, start=100.0, daily_growth=0.0, noise=0.01, seed=3)
    out = asset_stats.compute_stats(series)
    assert out["volatility"] is not None
    assert out["volatility"]["annualized_long_run"] > 0
    assert out["volatility"]["annualized_current"] > 0


# flexibility-gaps Gap 1: ZSCORE_WINDOW/MA_WINDOWS/LONG_WINDOWS_BARS are
# now overridable keyword args on compute_stats, defaults unchanged.

def test_compute_stats_defaults_match_module_constants_when_unspecified():
    series = _series(300, start=100.0, daily_growth=0.001, noise=0.01, seed=4)
    out = asset_stats.compute_stats(series)
    assert set(out["moving_averages"].keys()) == {str(w) for w in asset_stats.MA_WINDOWS}
    assert set(out["long_window_returns"].keys()) == {str(w) for w in asset_stats.LONG_WINDOWS_BARS}


def test_compute_stats_custom_zscore_window_changes_the_value():
    series = _series(150, start=100.0, daily_growth=0.0, noise=0.01, seed=1)
    default_out = asset_stats.compute_stats(series)
    custom_out = asset_stats.compute_stats(series, zscore_window=90)
    assert default_out["zscore_60d"] is not None
    assert custom_out["zscore_60d"] is not None
    assert custom_out["zscore_60d"] != default_out["zscore_60d"]


def test_compute_stats_custom_ma_windows_change_the_keys():
    series = _series(250, start=100.0, daily_growth=0.002)
    out = asset_stats.compute_stats(series, ma_windows=[10, 100])
    assert set(out["moving_averages"].keys()) == {"10", "100"}


def test_compute_stats_custom_long_windows_bars_change_the_keys():
    series = _series(300, start=100.0, daily_growth=0.001)
    out = asset_stats.compute_stats(series, long_windows_bars=[5, 15])
    assert set(out["long_window_returns"].keys()) == {"5", "15"}


def test_validate_window_rejects_non_positive():
    with pytest.raises(asset_stats.InvalidWindowError):
        asset_stats.validate_window(0)
    with pytest.raises(asset_stats.InvalidWindowError):
        asset_stats.validate_window(-5)


def test_validate_window_rejects_above_cap():
    with pytest.raises(asset_stats.InvalidWindowError):
        asset_stats.validate_window(asset_stats.MAX_WINDOW_BARS + 1)


def test_validate_window_accepts_reasonable_value():
    assert asset_stats.validate_window(90) == 90
    assert asset_stats.validate_window(asset_stats.MAX_WINDOW_BARS) == asset_stats.MAX_WINDOW_BARS


def test_parse_window_list_keeps_default_when_unset():
    assert asset_stats.parse_window_list(None, [20, 50, 200]) == [20, 50, 200]
    assert asset_stats.parse_window_list("", [20, 50, 200]) == [20, 50, 200]
    assert asset_stats.parse_window_list("   ", [20, 50, 200]) == [20, 50, 200]


def test_parse_window_list_parses_custom_csv():
    assert asset_stats.parse_window_list("20,50,100", [1, 2, 3]) == [20, 50, 100]
    assert asset_stats.parse_window_list(" 20 , 50 ", [1]) == [20, 50]


def test_parse_window_list_rejects_non_integer_entry():
    with pytest.raises(asset_stats.InvalidWindowError):
        asset_stats.parse_window_list("20,abc", [1])


def test_parse_window_list_rejects_non_positive_entry():
    with pytest.raises(asset_stats.InvalidWindowError):
        asset_stats.parse_window_list("0,50", [1])


def test_parse_window_list_rejects_entry_above_cap():
    with pytest.raises(asset_stats.InvalidWindowError):
        asset_stats.parse_window_list(str(asset_stats.MAX_WINDOW_BARS + 1), [1])
