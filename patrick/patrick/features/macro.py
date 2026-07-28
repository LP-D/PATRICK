"""Jointures macro FRED + features de lag (piste Granger identifiée dans
VIX_VAR_MACRO : EFFR et NFCI causent le VIX au sens de Granger, T10Y2Y/T10YIE non)."""
from __future__ import annotations

import pandas as pd

from patrick.features._utils import safe_pct_change


def build_macro_features(df: pd.DataFrame, macro_cols: list[str],
                          lags: tuple[int, ...] = (1, 5, 10)) -> pd.DataFrame:
    out = {}
    for col in macro_cols:
        if col not in df.columns:
            continue
        s = df[col]
        out[f"{col}_level"] = s
        out[f"{col}_ret_5d"] = safe_pct_change(s, 5)
        out[f"{col}_vol_20d"] = safe_pct_change(s).rolling(20).std()
        for lag in lags:
            out[f"{col}_lag{lag}"] = s.shift(lag)
    if not out:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame(out, index=df.index)
