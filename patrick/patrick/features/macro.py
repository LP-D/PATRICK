"""FRED macro joins + lag features (Granger lead identified in
VIX_VAR_MACRO: EFFR and NFCI Granger-cause VIX, T10Y2Y/T10YIE do not)."""
from __future__ import annotations

import pandas as pd

from patrick.features._utils import safe_pct_change


def build_macro_features(df: pd.DataFrame, macro_cols: list[str],
                          lags: tuple[int, ...] = (1, 5, 10),
                          guida_windows: list[int] | None = None) -> pd.DataFrame:
    """`guida_windows` (Phase 2, feature/guida-features-full): the return
    (`_ret_Xd`) and vol (`_vol_Xd`) windows used to be hardcoded to 5d/20d
    only -- when provided (typically `config.defaults.GUIDA_LOOKBACKS`),
    both are also computed at every extra lookback, merged (deduplicated)
    with the original 5d/20d. `None` (default): behavior strictly unchanged
    from before this parameter existed."""
    ret_windows = sorted({5, *(guida_windows or ())})
    vol_windows = sorted({20, *(guida_windows or ())})
    out = {}
    for col in macro_cols:
        if col not in df.columns:
            continue
        s = df[col]
        ret = safe_pct_change(s)
        out[f"{col}_level"] = s
        for w in ret_windows:
            out[f"{col}_ret_{w}d"] = safe_pct_change(s, w)
        for w in vol_windows:
            out[f"{col}_vol_{w}d"] = ret.rolling(w).std()
        for lag in lags:
            out[f"{col}_lag{lag}"] = s.shift(lag)
    if not out:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame(out, index=df.index)
