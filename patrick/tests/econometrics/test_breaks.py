"""A18 : ruptures multiples de Bai-Perron (moyenne) et d de Whittle local."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.econometrics import breaks
from patrick.econometrics.simulate import arfima


def _series(values):
    return pd.Series(values, index=pd.bdate_range("2015-01-01", periods=len(values)))


def test_two_mean_shifts_are_found_at_the_right_dates():
    rng = np.random.default_rng(0)
    y = np.concatenate([rng.normal(0, 1, 300), rng.normal(2, 1, 300), rng.normal(-1, 1, 300)])
    out = breaks.bai_perron(_series(y))
    assert out["n_breaks"] == 2
    idx = _series(y).index
    found = [idx.get_loc(pd.Timestamp(d)) for d in out["breaks"]]
    assert abs(found[0] - 300) < 15 and abs(found[1] - 600) < 15
    assert [round(s["mean"]) for s in out["segments"]] == [0, 2, -1]


def test_a_stable_series_has_no_break():
    out = breaks.bai_perron(_series(np.random.default_rng(1).normal(0, 1, 600)))
    assert out["n_breaks"] == 0 and len(out["segments"]) == 1


def test_whittle_recovers_the_memory_of_a_fractional_process():
    for d in (0.0, 0.3):
        est = breaks.local_whittle_d(arfima(4000, d, seed=3))
        assert est["d"] == pytest.approx(d, abs=0.1) and est["se"] < 0.05


def test_an_anti_persistent_process_is_labelled_as_such():
    est = breaks.local_whittle_d(arfima(4000, -0.3, seed=5))
    assert est["d"] < -0.15 and est["label"].startswith("antipersistance")


def test_short_series_are_refused():
    with pytest.raises(ValueError):
        breaks.bai_perron(_series(np.zeros(5)))
    with pytest.raises(ValueError):
        breaks.local_whittle_d(_series(np.zeros(50)))
