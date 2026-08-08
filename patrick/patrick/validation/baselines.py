"""Systematic baselines (Phase 0.6): majority class, persistence, HAR-RV —
computed for every walk-forward (horizon, fold, regime) and added to the
leaderboard alongside real models. Without this, an F1_dir of 0.55 looks good
in isolation; next to a persistence of 0.53, it's worth almost nothing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.validation.metrics import metrics

BASELINE_NAMES = ("BASELINE_majority", "BASELINE_persistence", "BASELINE_har_rv",
                   "BASELINE_majority_by_regime", "BASELINE_momentum_20", "BASELINE_momentum_5",
                   "BASELINE_random_walk_no_drift", "BASELINE_random_walk_drift")


def majority_class_predictions(y_tr: np.ndarray, n: int) -> np.ndarray:
    """Predicts the train's most frequent class everywhere."""
    values, counts = np.unique(y_tr, return_counts=True)
    majority = values[np.argmax(counts)]
    return np.full(n, majority, dtype=int)


def majority_by_regime_predictions(y_tr: np.ndarray, tr_regimes: np.ndarray,
                                    te_regimes: np.ndarray) -> np.ndarray:
    """Train's majority class, computed SEPARATELY per regime (Phase X5) --
    more demanding than the global majority when class imbalance varies with
    the market regime. Falls back to the train's global majority if a test
    regime has no corresponding train observation."""
    global_majority = majority_class_predictions(y_tr, 1)[0]
    per_regime: dict[str, int] = {}
    for reg in np.unique(tr_regimes):
        mask = tr_regimes == reg
        if mask.any():
            values, counts = np.unique(y_tr[mask], return_counts=True)
            per_regime[reg] = int(values[np.argmax(counts)])
    return np.array([per_regime.get(reg, global_majority) for reg in te_regimes], dtype=int)


def persistence_predictions(target_series: pd.Series, idx: pd.DatetimeIndex,
                             te_mask: np.ndarray, horizon: int) -> np.ndarray:
    """Predicts, for every test date, the realized class over the previous
    `horizon`-observation window in `target_series` (already known at
    decision time) — the classic "nothing changes" baseline in time
    series."""
    shifted = target_series.shift(horizon)
    persisted = shifted.reindex(idx).values[te_mask]
    fallback = target_series.mode().iloc[0] if len(target_series) else 0
    persisted = np.where(pd.isna(persisted), fallback, persisted).astype(int)
    return persisted


MOMENTUM_WINDOW_FUTURES = 20  # see Phase X5 -- momentum documented on this class
MOMENTUM_WINDOW_CRYPTO = 5    # extreme volatility regimes, shorter window


def momentum_predictions(price_series: pd.Series, idx: pd.DatetimeIndex,
                          te_mask: np.ndarray, window: int,
                          thr: dict, reg_r: pd.Series) -> np.ndarray:
    """Momentum baseline (Phase X5, futures/crypto): classifies the rolling
    `window`-day return via the SAME causal thresholds (`thr`, per regime)
    as `build_target` -- directly comparable to the real classes."""
    mom = price_series.pct_change(window).reindex(idx).values
    reg_al = reg_r.reindex(idx).fillna("GLOBAL").values
    preds = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        q25, q75 = thr.get(reg_al[i], thr.get("GLOBAL", (0, 0)))
        r = mom[i] if not np.isnan(mom[i]) else 0.0
        preds[i] = _classify_like_target(r, q25, q75)
    return preds[te_mask]


def random_walk_predictions(price_series: pd.Series, idx: pd.DatetimeIndex,
                             tr_mask: np.ndarray, te_mask: np.ndarray, drift: bool,
                             thr: dict, reg_r: pd.Series) -> np.ndarray:
    """Random-walk baseline (Phase X5): the best forecaster for a random
    walk WITHOUT drift (FX, an established reference result in short-horizon
    FX research) is "no change" (forecast return = 0), classified via the
    causal thresholds like any observation. WITH drift (macro series,
    standard convention in macro-econometrics): the train's average return
    is used as the constant forecast instead of 0. A constant forecast by
    construction (no dependency on recent history, unlike persistence)."""
    if drift:
        ret = price_series.pct_change().reindex(idx)
        train_ret = ret.values[tr_mask]
        train_ret = train_ret[~np.isnan(train_ret)]
        r_hat = float(train_ret.mean()) if len(train_ret) else 0.0
    else:
        r_hat = 0.0
    reg_al = reg_r.reindex(idx).fillna("GLOBAL").values
    preds = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        q25, q75 = thr.get(reg_al[i], thr.get("GLOBAL", (0, 0)))
        preds[i] = _classify_like_target(r_hat, q25, q75)
    return preds[te_mask]


def _classify_like_target(r: float, q25: float, q75: float) -> int:
    if r < q25:
        return 0
    if r < 0:
        return 1
    if r < q75:
        return 2
    return 3


def har_rv_predictions(price_series: pd.Series, idx: pd.DatetimeIndex,
                        tr_mask: np.ndarray, te_mask: np.ndarray,
                        thr: dict, reg_r: pd.Series) -> np.ndarray | None:
    """HAR-RV baseline (Corsi): linear regression (least squares, fit on
    train only) of next-day realized vol on its 1d/5d/22d rolling averages.

    Documented approximation: HAR-RV natively predicts a volatility
    MAGNITUDE, not a direction — this project's target is direction+
    amplitude (4 classes). So the two are combined: direction = sign of the
    last known return (sign persistence, the most directionally neutral
    prior possible); amplitude = the RV level predicted by HAR-RV,
    reclassified STRONG/WEAK via the SAME causal thresholds (`thr`, per
    regime) as `build_target` — hence directly comparable to the real
    classes rather than a scale invented for the occasion.

    Returns None if the train is too short to fit HAR-RV (baseline omitted
    from the leaderboard rather than polluted with NaN).
    """
    ret = price_series.pct_change()
    rv = ret.pow(2)
    feat = pd.DataFrame({
        "rv_1d": rv,
        "rv_5d": rv.rolling(5).mean(),
        "rv_22d": rv.rolling(22).mean(),
    })
    target_rv = rv.shift(-1)  # next day's RV, to be predicted from today
    data = pd.concat([feat, target_rv.rename("y")], axis=1).dropna()
    tr_dates = set(idx[tr_mask])
    fit_data = data.loc[data.index.isin(tr_dates)]
    if len(fit_data) < 60:
        return None

    X_fit = fit_data[["rv_1d", "rv_5d", "rv_22d"]].values
    y_fit = fit_data["y"].values
    X_fit_design = np.column_stack([np.ones(len(X_fit)), X_fit])
    coef, *_ = np.linalg.lstsq(X_fit_design, y_fit, rcond=None)

    feat_at_idx = feat.reindex(idx).values
    valid = ~np.isnan(feat_at_idx).any(axis=1)
    design = np.column_stack([np.ones(len(feat_at_idx)), np.nan_to_num(feat_at_idx)])
    rv_pred = np.where(valid, design @ coef, np.nan)

    sign_persist = np.sign(ret.reindex(idx).shift(1).values)
    sign_persist = np.where(sign_persist == 0, 1.0, sign_persist)

    reg_al = reg_r.reindex(idx).fillna("NORMAL").values
    preds = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        reg = reg_al[i]
        q25, q75 = thr.get(reg, thr.get("GLOBAL", (0, 0)))
        rv_i = rv_pred[i]
        s = sign_persist[i] if not np.isnan(sign_persist[i]) else 1.0
        amplitude_proxy = s * np.sqrt(max(rv_i, 0.0)) if not np.isnan(rv_i) else 0.0
        preds[i] = _classify_like_target(amplitude_proxy, q25, q75)
    return preds[te_mask]


def compute_baselines(price_series: pd.Series, target_series: pd.Series,
                       idx: pd.DatetimeIndex, tr_mask: np.ndarray, te_mask: np.ndarray,
                       y_tr: np.ndarray, y_te: np.ndarray, horizon: int,
                       thr: dict, reg_r: pd.Series,
                       return_predictions: bool = False) -> dict[str, dict] | dict[str, np.ndarray]:
    """Returns {baseline_name: metrics(...)} for all baselines computable on
    this fold (historical behavior, `return_predictions=False`). HAR-RV is
    absent from the dict (no key) if the train history is too short, rather
    than polluting the leaderboard with NaNs.

    `return_predictions=True` (Phase 2.5, Diebold-Mariano): returns
    {baseline_name: y_pred} instead — the raw predictions, aligned with
    `y_te`, needed to compare the winning model's loss to a baseline's
    observation by observation (a metric average cannot do this). A single
    underlying computation in both cases, no duplication."""
    reg_al = reg_r.reindex(idx).values
    preds: dict[str, np.ndarray] = {
        "BASELINE_majority": majority_class_predictions(y_tr, len(y_te)),
        "BASELINE_persistence": persistence_predictions(target_series, idx, te_mask, horizon),
        "BASELINE_majority_by_regime": majority_by_regime_predictions(
            y_tr, reg_al[tr_mask], reg_al[te_mask]),
        "BASELINE_momentum_20": momentum_predictions(
            price_series, idx, te_mask, MOMENTUM_WINDOW_FUTURES, thr, reg_r),
        "BASELINE_momentum_5": momentum_predictions(
            price_series, idx, te_mask, MOMENTUM_WINDOW_CRYPTO, thr, reg_r),
        "BASELINE_random_walk_no_drift": random_walk_predictions(
            price_series, idx, tr_mask, te_mask, drift=False, thr=thr, reg_r=reg_r),
        "BASELINE_random_walk_drift": random_walk_predictions(
            price_series, idx, tr_mask, te_mask, drift=True, thr=thr, reg_r=reg_r),
    }
    har_pred = har_rv_predictions(price_series, idx, tr_mask, te_mask, thr, reg_r)
    if har_pred is not None:
        preds["BASELINE_har_rv"] = har_pred
    if return_predictions:
        return preds
    return {name: metrics(y_te, pred) for name, pred in preds.items()}
