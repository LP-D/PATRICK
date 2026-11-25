"""Détecteur de paires cointégrées (FO25 du 25/11)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.analysis import pairs_scan


def _world(n=1200, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    base = np.cumsum(rng.normal(0, 0.01, n))
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = 0.9 * spread[t - 1] + rng.normal(0, 0.005)
    return {"A": pd.Series(np.exp(base + spread), index=idx), "B": pd.Series(np.exp(base), index=idx),
            "C": pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx), "D": pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)}


def test_the_cointegrated_pair_is_found_and_random_walks_are_not():
    pairs = pairs_scan.scan(_world())
    assert [(r["a"], r["b"]) for r in pairs] == [("A", "B")]
    assert 3 < pairs[0]["half_life"] < 15 and abs(pairs[0]["hedge"] - 1) < 0.1


def test_short_series_are_left_out():
    w = {k: v.iloc[:100] for k, v in _world().items()}
    assert pairs_scan.scan(w) == []
