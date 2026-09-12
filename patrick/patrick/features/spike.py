""""Spike" features (VIX_SPIKE_SCAN): rolling Hurst exponent, semivariance
(downside risk), rolling skew, and a bootstrap particle filter over a simple
stochastic volatility model (AR(1) in log-volatility). Marginal effect
measured in the VIX project -- kept since it's cheap and sometimes useful
outside the GLOBAL regime.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features._utils import safe_pct_change


def _hurst_of_window(x: np.ndarray) -> float:
    n = len(x)
    if n < 20 or np.std(x) == 0:
        return np.nan
    lags = [lag for lag in (2, 4, 8, 16, 32) if lag < n]
    if len(lags) < 2:
        return np.nan
    tau = []
    for lag in lags:
        diffs = x[lag:] - x[:-lag]
        s = np.std(diffs)
        tau.append(s if s > 0 else np.nan)
    tau = np.array(tau)
    if np.any(~np.isfinite(tau)) or np.any(tau <= 0):
        return np.nan
    slope, _ = np.polyfit(np.log(lags), np.log(tau), 1)
    return float(slope)


def rolling_hurst(series: pd.Series, window: int = 100) -> pd.Series:
    """Approximate estimator of the Hurst exponent (multi-lag differences
    method) over a rolling window -- H≈0.5 random walk, H>0.5 persistent,
    H<0.5 anti-persistent."""
    log_s = np.log(series.clip(lower=1e-8))
    return log_s.rolling(window).apply(_hurst_of_window, raw=True)


def rolling_semivariance(series: pd.Series, window: int = 20) -> pd.Series:
    """Realized volatility counting only negative returns (downside risk),
    annualized."""
    ret = safe_pct_change(series)
    neg = ret.where(ret < 0, 0.0)
    return np.sqrt((neg ** 2).rolling(window).mean()) * np.sqrt(252)


def rolling_skew(series: pd.Series, window: int = 20) -> pd.Series:
    return safe_pct_change(series).rolling(window).skew()


def particle_filter_vol(series: pd.Series, n_particles: int = 200, seed: int = 42,
                         fit_end_idx: int | None = None) -> pd.Series:
    """Bootstrap particle filter over a log-AR(1) stochastic volatility model:
    h_t = mu + phi*(h_{t-1}-mu) + eta_t, r_t | h_t ~ N(0, exp(h_t)).
    (mu, phi, sigma_eta) roughly calibrated via first-order correlation on
    log(r_t^2) -- not a full MLE, but sufficient for a causal filtered
    volatility feature (each h_t uses only r_1..r_t).

    `fit_end_idx`, when provided, restricts the calibration of
    (mu, phi, sigma_eta) to `series.iloc[:fit_end_idx]` (the fold's train
    set) -- otherwise (as before this fix) these three statistics were
    computed over the whole series, so informed by later folds' test set
    even though the particle recursion itself is causal (see vol_models.py,
    same leak class, same fix)."""
    ret = safe_pct_change(series).fillna(0.0).values
    n = len(ret)
    log_r2 = np.log(ret ** 2 + 1e-8)
    valid = np.isfinite(log_r2)
    if valid.sum() < 50:
        return pd.Series(np.nan, index=series.index, name="particle_filtered_vol")

    if fit_end_idx is not None:
        fit_end = min(fit_end_idx, n)
        fit_valid = valid.copy()
        fit_valid[fit_end:] = False
        if fit_valid.sum() < 50:
            fit_valid = valid
    else:
        fit_valid = valid
    y = log_r2[fit_valid]
    mu = float(y.mean())
    y_c = y - mu
    phi = float(np.clip(np.corrcoef(y_c[:-1], y_c[1:])[0, 1], -0.98, 0.98)) if len(y_c) > 2 else 0.9
    resid = y_c[1:] - phi * y_c[:-1]
    sigma_eta = max(float(resid.std()), 1e-3)

    rng = np.random.default_rng(seed)
    init_std = sigma_eta / np.sqrt(max(1 - phi ** 2, 1e-6))
    particles = rng.normal(mu, init_std, n_particles)
    weights = np.ones(n_particles) / n_particles
    filtered = np.full(n, np.nan)

    for t in range(n):
        particles = mu + phi * (particles - mu) + rng.normal(0, sigma_eta, n_particles)
        var_t = np.exp(particles)
        loglik = -0.5 * (np.log(2 * np.pi * var_t) + (ret[t] ** 2) / var_t)
        loglik -= loglik.max()
        w = np.exp(loglik) * weights
        w_sum = w.sum()
        weights = w / w_sum if w_sum > 0 else np.ones(n_particles) / n_particles
        filtered[t] = float(np.average(particles, weights=weights))
        ess = 1.0 / np.sum(weights ** 2)
        if ess < n_particles / 2:
            positions = (rng.random() + np.arange(n_particles)) / n_particles
            cumsum = np.cumsum(weights)
            idx = np.searchsorted(cumsum, positions)
            particles = particles[idx]
            weights = np.ones(n_particles) / n_particles

    return pd.Series(np.exp(filtered / 2), index=series.index, name="particle_filtered_vol")


# Phase 2 (feature/guida-features-full) -- `rolling_hurst`'s `.rolling(w).
# apply(_hurst_of_window, raw=True)` re-runs the O(window) multi-lag-
# difference estimator at EVERY bar, i.e. O(n*window) total; unlike
# semivariance/skew (vectorized pandas rolling ops, cheap at any window),
# computing it at all 14 Guida lookbacks (up to 756d) would multiply the
# per-column cost roughly 15x for a family whose module docstring already
# notes "no clean signal, kept because cheap". A reduced subset (quarter/
# year/two-year) is added instead of the full grid -- deliberately, not a
# technical blocker -- so the family still benefits from a longer-horizon
# Hurst without dominating scan time; measured in
# `tests/test_guida_scan_cost.py`.
HURST_GUIDA_SUBSET: tuple[int, ...] = (66, 252, 504)


def build_spike_features_base(series: pd.Series, prefix: str = "px",
                               guida_windows: list[int] | None = None) -> pd.DataFrame:
    """hurst/semivar/skew -- pure rolling windows, causal by construction,
    computed once for a whole run (shared across all folds).

    `guida_windows` (Phase 2): when provided (typically `config.defaults.
    GUIDA_LOOKBACKS`), semivariance and skew (cheap, vectorized) are computed
    at EVERY extra lookback; Hurst (expensive rolling `.apply`) only at
    `HURST_GUIDA_SUBSET` -- see its docstring. `None` (default): behavior
    strictly unchanged from before this parameter existed."""
    out = {
        f"{prefix}_hurst_100d": rolling_hurst(series, 100),
        f"{prefix}_semivar_20d": rolling_semivariance(series, 20),
        f"{prefix}_skew_20d": rolling_skew(series, 20),
    }
    if guida_windows:
        for w in guida_windows:
            if w != 20:
                out[f"{prefix}_semivar_{w}d"] = rolling_semivariance(series, w)
                out[f"{prefix}_skew_{w}d"] = rolling_skew(series, w)
        for w in HURST_GUIDA_SUBSET:
            if w != 100 and w in guida_windows:
                out[f"{prefix}_hurst_{w}d"] = rolling_hurst(series, w)
    return pd.DataFrame(out, index=series.index)


def build_spike_features_parametric(series: pd.Series, prefix: str = "px",
                                     fit_end_idx: int | None = None) -> pd.DataFrame:
    """particle_filter_vol alone -- parameters (mu/phi/sigma_eta) to be
    recomputed per fold via `fit_end_idx` (see `particle_filter_vol`
    docstring)."""
    return pd.DataFrame({
        f"{prefix}_particle_vol": particle_filter_vol(series, fit_end_idx=fit_end_idx),
    }, index=series.index)


def build_spike_features(series: pd.Series, prefix: str = "px",
                          fit_end_idx: int | None = None) -> pd.DataFrame:
    """Combines `build_spike_features_base` + `_parametric` -- used as-is for
    a one-off computation (tests); the walk-forward engine calls both
    variants separately so only the parametric part is recomputed per
    fold."""
    return pd.concat([
        build_spike_features_base(series, prefix),
        build_spike_features_parametric(series, prefix, fit_end_idx),
    ], axis=1)
