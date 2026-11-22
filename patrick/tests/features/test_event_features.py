"""Roadmap bloc 3 -- publication-timestamp guard for NLP / alternative data.

A news item, a filing or a sentiment score can enter the feature row of
session t only if it was PUBLISHED before the close of t (plus a processing
latency). Two traps this guard closes:
1. the story/event date a vendor attaches is not the publication time --
   only `published_at` is accepted, and a missing one is an error, never
   inferred;
2. a date-only timestamp is ambiguous (07:00 or 22:00?): for features it
   becomes visible at the NEXT session (conservative), the opposite of the
   event-study convention (same session, to capture the reaction) --
   `event_day_zero` cannot be reused as is for features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features import event_features as ef

DAYS = pd.bdate_range("2024-01-01", periods=60)


def test_visibility_session_rules():
    v = ef.visible_session
    assert v("2024-01-10 15:00", DAYS) == pd.Timestamp("2024-01-10")   # before the close
    assert v("2024-01-10 16:30", DAYS) == pd.Timestamp("2024-01-11")   # after the close
    assert v("2024-01-10 15:58", DAYS, latency="5min") == pd.Timestamp("2024-01-11")
    assert v("2024-01-13 10:00", DAYS) == pd.Timestamp("2024-01-15")   # Saturday -> Monday
    assert v("2024-01-10", DAYS) == pd.Timestamp("2024-01-11")         # date only: next session
    assert v(pd.Timestamp("2024-01-10 14:00", tz="UTC"), DAYS) == pd.Timestamp("2024-01-10")  # 09:00 NY
    assert v(pd.Timestamp("2024-01-10 22:00", tz="UTC"), DAYS) == pd.Timestamp("2024-01-11")  # 17:00 NY
    assert v("2024-01-10 16:00", DAYS) == pd.Timestamp("2024-01-11")   # at the close: not in the close
    assert v("2030-01-01 10:00", DAYS) is None


def test_missing_publication_timestamp_is_an_error_not_a_guess():
    items = pd.DataFrame({"published_at": ["2024-01-10 09:00", None], "score": [0.3, -0.2]})
    with pytest.raises(ValueError, match="published_at"):
        ef.align_items(items, DAYS)
    with pytest.raises(ValueError, match="published_at"):
        ef.align_items(pd.DataFrame({"date": ["2024-01-10"], "score": [0.1]}), DAYS)


def _items(seed=0, n=80):
    rng = np.random.default_rng(seed)
    minutes = rng.integers(0, 60 * 24 * 80, n)
    ts = pd.Timestamp("2024-01-01") + pd.to_timedelta(np.sort(minutes), unit="min")
    return pd.DataFrame({"published_at": ts, "score": rng.normal(0, 1, n)})


def test_features_at_t_ignore_items_published_after_the_close_of_t():
    items = _items()
    full = ef.event_features(items, DAYS, value_col="score", windows=(1, 5))
    for k in (10, 25, 40):
        t = DAYS[k]
        close = pd.Timestamp(f"{t.date()} 16:00")
        known = items[items["published_at"] < close]
        partial = ef.event_features(known, DAYS, value_col="score", windows=(1, 5))
        pd.testing.assert_series_equal(full.loc[t], partial.loc[t], check_names=False)


def test_feature_values_on_a_hand_built_case():
    items = pd.DataFrame({
        "published_at": ["2024-01-10 09:00", "2024-01-10 18:00", "2024-01-11 10:00", "2024-01-15"],
        "score": [1.0, -1.0, 0.5, 2.0],
    })
    f = ef.event_features(items, DAYS, value_col="score", windows=(1, 3))
    assert f.loc["2024-01-10", "evt_count_1d"] == 1
    assert f.loc["2024-01-11", "evt_count_1d"] == 2                 # 18:00 item + 10:00 item
    assert f.loc["2024-01-11", "evt_mean_score_1d"] == pytest.approx(-0.25)
    assert f.loc["2024-01-11", "evt_count_3d"] == 3
    assert f.loc["2024-01-12", "evt_days_since"] == 1
    assert f.loc["2024-01-15", "evt_count_1d"] == 0                 # date-only item -> 16th
    assert f.loc["2024-01-16", "evt_count_1d"] == 1
    assert f.loc["2024-01-09", "evt_count_3d"] == 0
    assert np.isnan(f.loc["2024-01-09", "evt_days_since"])          # nothing known yet
    assert np.isnan(f.loc["2024-01-15", "evt_mean_score_1d"])       # no item in window: missing, not 0
