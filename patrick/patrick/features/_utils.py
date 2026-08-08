"""Utilities shared by the feature modules.

`Series.pct_change()` returns +/-inf (not NaN) when the previous value is
zero or crosses zero — `dropna()` alone does not remove them. Encountered
under real conditions on T10Y2Y (yield curve inversion, crosses zero) and
EFFR (near 0 during the 2020-2021 ZIRP period), which crashed
`GaussianHMM.fit()` (ValueError: Input contains infinity) and polluted other
return-based features. Any function that computes a return must go through
`safe_pct_change` rather than calling `.pct_change()` directly.

Phase 2: a denominator close to zero (not exactly zero) produces a ratio
that isn't infinite but is absurdly large (T10Y2Y at 0.001: a 0.01-point
move gives a "return" of 1000%) — the replacement above doesn't catch it
(it isn't +/-inf), and this huge but finite value can later overflow to inf
after scaling (RobustScaler) further down the pipeline, crashing XGBoost
("Input data contains inf"). Encountered on the Heston/VRP proxies
(`vol_models.py`) applied to T10Y2Y. A return beyond +/-1000% over a single
period is never an exploitable signal here anyway -> clipped rather than
left to explode.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_MAX_ABS_RETURN = 10.0  # +/-1000%: beyond this, a near-zero-denominator artifact


def safe_pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
    pct = series.pct_change(periods).replace([np.inf, -np.inf], np.nan)
    return pct.clip(-_MAX_ABS_RETURN, _MAX_ABS_RETURN)
