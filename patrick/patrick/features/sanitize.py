"""Correction report, N2 -- "a ±inf in the feature pool never reaches a
model", enforced on EVERY path that turns a feature pool into a model input:
the scan (walk-forward, holdout, CPCV -- `pipeline/engine.py`) and the three
post-scan paths (`tracking/export.py::export_best_model`,
`predict.py::predict_live`, `explain.py::explain_last_prediction`), which
used bare `np.nan_to_num` until `tests/test_inf_export_predict.py` showed
that (export crashed XGBoost; live scoring silently fed `inf` to the model).

Shared module (not `pipeline/engine.py`) because `tracking/export.py` is
imported BY the engine -- importing the engine back from there would be
circular.
"""
from __future__ import annotations

import numpy as np

# XGBoost (et LightGBM/CatBoost via leurs conversions) travaille en float32 : une valeur finie en float64 mais au-delà de
# 3.4e38 y devient `inf` et la matrice est refusée (« Input data contains `inf` or a value too large »). Marge de 8
# ordres de grandeur : aucune feature réelle (rendement, z-score, ratio borné) n'approche cette échelle.
FLOAT32_SAFE_MAX = 1e30


def finite_features(values: np.ndarray, where: str) -> np.ndarray:
    """Correction report, N2 -- replaces `np.nan_to_num(...)` at the three
    places where the feature matrix is built (walk-forward, holdout, CPCV).

    `np.nan_to_num` alone is NOT enough, and gave a false sense of safety: it
    maps ±inf to ±1.797e308 (the float64 maximum), a value that's finite at
    that instant but astronomical, which the `RobustScaler` applied right
    after divides by the column's IQR. As soon as this IQR is < 1 -- a
    common case among thousands of columns (returns, z-scores, bounded
    indicators) -- the division PRODUCES ±inf again, and XGBoost rejects the
    matrix ("Input data contains `inf` or a value too large, while `missing`
    is not set to `inf`"). Measured: a single infinite cell in a column with
    IQR 0.025 is enough to reproduce the error; since the scaler is fit on
    train only, an inf present only in TEST also goes through this path.

    An upstream ±inf always comes from a degenerate computation (division by
    a ~0 denominator in a ratio/interaction, log of a value <= 0): it carries
    no exploitable numeric information, so it is treated as a MISSING value
    -- exactly the same path as NaN, already converted to 0.0 here -- and
    never as "a very large number". Counted and reported, never silent (same
    discipline as the D3 guard on excluded folds)."""
    n_inf = int(np.isinf(values).sum())
    if n_inf:
        print(f"  [WARN] {where}: {n_inf} infinite value(s) in the feature pool "
              f"(degenerate computation: denominator ~0, log of a value <= 0) — "
              f"treated as missing.")
    with np.errstate(invalid="ignore"):
        too_big = np.isfinite(values) & (np.abs(values) > FLOAT32_SAFE_MAX)
    n_big = int(too_big.sum())
    if n_big:
        print(f"  [WARN] {where}: {n_big} value(s) out of float32 range (> {FLOAT32_SAFE_MAX:g}: ratio on a ~0 "
              f"denominator, diverged fit) — treated as missing.")
        values = np.where(too_big, np.nan, values)
    return np.nan_to_num(np.where(np.isfinite(values), values, np.nan))


def finite_scaled(scaled: np.ndarray, where: str) -> np.ndarray:
    """Correction report, N2 -- guarantees after scaling the invariant
    XGBoost needs (a fully finite matrix), which `_finite_features` alone
    cannot guarantee: an input value that is simply VERY LARGE but finite
    (never an inf, hence invisible upstream) can still overflow when divided
    by a tiny IQR. A safety net on the way out, not a replacement for the
    upstream cleanup -- both are necessary."""
    with np.errstate(invalid="ignore"):
        bad = ~np.isfinite(scaled) | (np.abs(scaled) > FLOAT32_SAFE_MAX)
    if bad.any():
        n_bad = int(bad.sum())
        print(f"  [WARN] {where}: {n_bad} non-finite or float32-overflowing value(s) AFTER scaling "
              f"(overflow from an extreme value divided by a tiny IQR) — "
              f"reset to the median (0 after RobustScaler).")
        scaled = np.nan_to_num(np.where(bad, np.nan, scaled))
    return scaled
