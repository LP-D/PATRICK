"""Long-cycle features for the 252/504/756-day horizons (roadmap bloc 3).

The technical family stops at 60-day lookbacks: a model asked about the
direction over one to three years otherwise only sees month-scale
information. Documented long-horizon predictors, one block per raw column:

- `lc_ret_{252,504,756}d`: 1-, 2- and 3-year returns (long-term reversal,
  De Bondt & Thaler 1985);
- `lc_mom_12_1`: return from t-252 to t-21 (Jegadeesh & Titman 1993 -- the
  last month is skipped, it carries short-term reversal instead);
- `lc_zscore_{252,756}d`: level z-score over 1 and 3 years;
- `lc_rangepos_{252,756}d`: position inside the 1-/3-year [min, max] range,
  in [-0.5, 0.5] (52-week-high anchoring, George & Hwang 2004). Centred so
  the NaN -> 0 imputation of `features/sanitize.finite_features` reads
  "middle of the range" during warm-up, not "at the low";
- `lc_dd_ath`: drawdown from the running maximum (>= 252 observations),
  missing where the series is <= 0 (a spread crossing zero has no ratio);
- `lc_volratio_21_252`: 21-day over 252-day realised volatility.

Every value at t uses prices up to t only (rolling/expanding windows,
backward shifts) -- `tests/test_long_cycle.py` perturbs the future and checks
the past is unchanged.

Caveat the family does not fix: at a 756-day horizon, overlapping labels
leave about n/756 independent observations (~8 on 25 years of data); these
features give the model the right information set, not a larger sample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features._utils import safe_pct_change

RETURN_WINDOWS = (252, 504, 756)
LEVEL_WINDOWS = (252, 756)
MOMENTUM_SKIP = 21
ATH_MIN_PERIODS = 252


def build_long_cycle_features(series: pd.Series, prefix: str = "px") -> pd.DataFrame:
    s = series.astype(float)
    out: dict[str, pd.Series] = {}
    for w in RETURN_WINDOWS:
        out[f"{prefix}_lc_ret_{w}d"] = safe_pct_change(s, w)
    out[f"{prefix}_lc_mom_12_1"] = safe_pct_change(s.shift(MOMENTUM_SKIP), 252 - MOMENTUM_SKIP)
    for w in LEVEL_WINDOWS:
        roll = s.rolling(w)
        std = roll.std().replace(0, np.nan)
        out[f"{prefix}_lc_zscore_{w}d"] = (s - roll.mean()) / std
        lo, hi = roll.min(), roll.max()
        span = (hi - lo).replace(0, np.nan)
        out[f"{prefix}_lc_rangepos_{w}d"] = (s - lo) / span - 0.5
    running_max = s.expanding(min_periods=ATH_MIN_PERIODS).max()
    positive = (s > 0) & (running_max > 0)
    out[f"{prefix}_lc_dd_ath"] = (s / running_max - 1).where(positive)
    ret = safe_pct_change(s)
    vol_long = ret.rolling(252).std().replace(0, np.nan)
    out[f"{prefix}_lc_volratio_21_252"] = ret.rolling(21).std() / vol_long
    frame = pd.DataFrame(out, index=s.index)
    return frame.replace([np.inf, -np.inf], np.nan)
