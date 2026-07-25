"""Régression : une série qui traverse ou touche zéro (pente des taux T10Y2Y lors
d'une inversion, EFFR quasi nul pendant le ZIRP) faisait planter le pipeline en
conditions réelles — `pct_change()` renvoie +/-inf (pas NaN) dans ce cas, non
retiré par `dropna()`, ce qui faisait échouer `GaussianHMM.fit()` avec
'Input contains infinity'. Voir marketml/features/_utils.py::safe_pct_change.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketml.features._utils import safe_pct_change
from marketml.features.spike import build_spike_features
from marketml.features.technical import build_technical_features
from marketml.features.vol_models import build_vol_model_features


def _series_crossing_zero(n=400, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    # imite T10Y2Y : oscille autour de 0, touche/traverse zéro plusieurs fois
    values = np.cumsum(rng.normal(0, 0.02, n)) - 0.3
    return pd.Series(values, index=idx, name="T10Y2Y_LIKE")


def test_safe_pct_change_has_no_inf_when_series_touches_zero():
    s = pd.Series([1.0, 0.0, 1.0, -1.0, 0.0, 2.0])
    ret = safe_pct_change(s)
    assert not np.isinf(ret.dropna()).any()


def test_vol_model_features_do_not_crash_on_zero_crossing_series():
    s = _series_crossing_zero()
    df = build_vol_model_features(s, prefix="test")
    assert len(df) == len(s)
    numeric = df.select_dtypes(include=[np.number])
    assert not np.isinf(numeric.to_numpy(dtype=float)).any()


def test_spike_features_do_not_crash_on_zero_crossing_series():
    s = _series_crossing_zero()
    df = build_spike_features(s, prefix="test")
    assert len(df) == len(s)
    numeric = df.select_dtypes(include=[np.number])
    assert not np.isinf(numeric.to_numpy(dtype=float)).any()


def test_technical_features_do_not_crash_on_zero_crossing_series():
    s = _series_crossing_zero()
    df = build_technical_features(s, prefix="test")
    assert len(df) == len(s)
    numeric = df.select_dtypes(include=[np.number])
    assert not np.isinf(numeric.to_numpy(dtype=float)).any()
