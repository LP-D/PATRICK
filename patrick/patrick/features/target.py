"""4-class direction/amplitude target (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT)
with causal, regime-conditional thresholds -- logic established throughout
the VIX project (`build_target`), generalized: the series is no longer
hardcoded to the VIX.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET_COL = "target_class"


def build_target(series: pd.Series, horizon: int, split_idx: int,
                  flat_thr: float = 0.003) -> tuple[pd.Series, pd.Series, dict]:
    """Returns (target, regime_by_date, thresholds_by_regime). Regime
    thresholds (CALM/NORMAL/STRESS, 33%/67% quantiles of the level) and
    classification thresholds (25%/75% quantiles of the return, per regime)
    are fitted solely on `series[:split_idx]` (the fold's train set) -- no
    future leak.

    Phase 0 (correctness): classification thresholds used to be fitted on
    `ret.loc[ret.index < cut_date]`, but `ret[d] = s[d+horizon]/s[d] - 1` --
    for dates `d` within the `horizon` last points before `cut_date`, this
    window overruns into the test set, so `ret[d]` (and by extension the
    quantiles fitted on it) is partly informed by post-cut values, even when
    excluding `d` itself. This is a leak distinct from the one
    `validation/purge.py` fixes (which only acts downstream, on already-
    built train ROWS, not on the threshold computation itself) -- detected
    by the future-corruption test (`tests/test_leakage.py`). `ret_tr`
    therefore also excludes these last `horizon` points: only label windows
    entirely before `cut_date` contribute to the threshold fit."""
    s = series.ffill().bfill()
    s_tr = s.iloc[:split_idx]
    calm_thr = s_tr.quantile(0.33)
    stress_thr = s_tr.quantile(0.67)
    regime = pd.Series("NORMAL", index=s.index)
    regime[s < calm_thr] = "CALM"
    regime[s >= stress_thr] = "STRESS"

    ret = (s.shift(-horizon) / s) - 1
    flat = ret.abs() < flat_thr
    ret = ret.loc[~flat].dropna()
    reg_r = regime.reindex(ret.index)

    cut_date = s.index[min(split_idx, len(s) - 1)]
    safe_fit_idx = max(split_idx - horizon, 0)
    safe_fit_cut_date = s.index[safe_fit_idx]
    ret_tr = ret.loc[ret.index < safe_fit_cut_date]
    reg_tr = reg_r.loc[ret_tr.index]

    thr = {}
    for reg in ["CALM", "NORMAL", "STRESS"]:
        sub = ret_tr[reg_tr == reg]
        thr[reg] = (
            sub.quantile(0.25) if len(sub) >= 20 else ret_tr.quantile(0.25),
            sub.quantile(0.75) if len(sub) >= 20 else ret_tr.quantile(0.75),
        )
    thr["GLOBAL"] = (ret_tr.quantile(0.25), ret_tr.quantile(0.75))

    def classify(r: float, reg: str) -> int:
        q25, q75 = thr.get(reg, (0, 0))
        if r < q25:
            return 0
        if r < 0:
            return 1
        if r < q75:
            return 2
        return 3

    target = pd.Series(
        [classify(r, reg_r[i]) for i, r in ret.items()], index=ret.index, name=TARGET_COL
    )
    return target, reg_r, thr


def classify_return(r: float, reg: str, thr: dict) -> int:
    q25, q75 = thr.get(reg, (0, 0))
    if r < q25:
        return 0
    if r < 0:
        return 1
    if r < q75:
        return 2
    return 3
