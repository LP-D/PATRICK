"""Generic event study module: point-in-time day 0, abnormal returns,
aggregate tests (size and power checked by simulation)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.research import event_study as es

DAYS = pd.bdate_range("2015-01-01", periods=2000)


def _market(seed=0):
    rng = np.random.default_rng(seed)
    rm = rng.normal(0.0003, 0.01, len(DAYS))
    return pd.Series(100 * np.exp(np.cumsum(rm)), index=DAYS), rm


def _asset(rm, beta=1.2, seed=1, jumps=None):
    rng = np.random.default_rng(seed)
    r = 0.0001 + beta * rm + rng.normal(0, 0.012, len(DAYS))
    for day, size in (jumps or {}).items():
        r[DAYS.get_loc(day)] += size
    return pd.Series(100 * np.exp(np.cumsum(r)), index=DAYS)


def test_event_after_the_close_starts_on_the_next_session():
    d0 = es.event_day_zero("2019-09-10 18:30", DAYS)
    assert d0 == pd.Timestamp("2019-09-11")


def test_event_before_the_close_is_the_same_session():
    assert es.event_day_zero("2019-09-10 13:00", DAYS) == pd.Timestamp("2019-09-10")


def test_weekend_event_moves_to_monday():
    assert es.event_day_zero("2019-09-14", DAYS) == pd.Timestamp("2019-09-16")


def test_timezone_aware_timestamp_is_converted_to_market_time():
    # 22:30 in Paris = 16:30 in New York: after the close.
    assert es.event_day_zero(pd.Timestamp("2019-09-10 22:30", tz="Europe/Paris"), DAYS) == pd.Timestamp("2019-09-11")


def test_known_abnormal_jumps_are_recovered_and_significant():
    market, rm = _market()
    events = list(DAYS[400:1900:75])
    asset = _asset(rm, jumps={d: 0.04 for d in events})
    study = es.run_event_study(asset, events, benchmark=market, event_window=(-2, 2))
    t = study.tests()
    assert t["n_events"] == len(events)
    assert t["caar"] == pytest.approx(0.04, abs=0.01)
    assert t["p_bmp"] < 0.001 and t["p_patell"] < 0.001


def test_no_effect_rejects_at_about_the_nominal_rate():
    rejections = 0
    for seed in range(60):
        market, rm = _market(seed)
        asset = _asset(rm, seed=seed + 100)
        events = list(DAYS[400:1900:75])
        if es.run_event_study(asset, events, benchmark=market, event_window=(-2, 2)).tests()["p_bmp"] < 0.05:
            rejections += 1
    assert rejections <= 8


def test_overlapping_windows_are_flagged():
    market, rm = _market()
    asset = _asset(rm)
    study = es.run_event_study(asset, [DAYS[500], DAYS[505]], benchmark=market, event_window=(-5, 10))
    assert study.overlapping_events


def test_events_without_enough_history_are_skipped_not_crashing():
    market, rm = _market()
    study = es.run_event_study(_asset(rm), [DAYS[10], DAYS[-3]], benchmark=market)
    assert study.n_events == 0 and len(study.skipped) == 2


def test_constant_mean_model_needs_no_benchmark():
    _market_prices, rm = _market()
    study = es.run_event_study(_asset(rm), list(DAYS[400:1900:150]), model="constant_mean")
    assert study.n_events > 5
    assert len(study.caar()) == 26
