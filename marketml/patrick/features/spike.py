"""Features de "spike" (VIX_SPIKE_SCAN) : exposant de Hurst glissant, semivariance
(risque baissier), skew glissant, et un filtre particulaire bootstrap sur un modèle
de volatilité stochastique simple (AR(1) en log-volatilité). Effet marginal mesuré
dans le projet VIX — conservé car peu coûteux et parfois utile hors régime GLOBAL.
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
    """Estimateur approché de l'exposant de Hurst (méthode des différences à lags
    multiples) sur une fenêtre glissante — H≈0.5 marche aléatoire, H>0.5 persistant,
    H<0.5 anti-persistant."""
    log_s = np.log(series.clip(lower=1e-8))
    return log_s.rolling(window).apply(_hurst_of_window, raw=True)


def rolling_semivariance(series: pd.Series, window: int = 20) -> pd.Series:
    """Volatilité réalisée ne comptant que les rendements négatifs (risque baissier),
    annualisée."""
    ret = safe_pct_change(series)
    neg = ret.where(ret < 0, 0.0)
    return np.sqrt((neg ** 2).rolling(window).mean()) * np.sqrt(252)


def rolling_skew(series: pd.Series, window: int = 20) -> pd.Series:
    return safe_pct_change(series).rolling(window).skew()


def particle_filter_vol(series: pd.Series, n_particles: int = 200, seed: int = 42) -> pd.Series:
    """Filtre particulaire bootstrap sur un modèle de volatilité stochastique
    log-AR(1) : h_t = mu + phi*(h_{t-1}-mu) + eta_t, r_t | h_t ~ N(0, exp(h_t)).
    (mu, phi, sigma_eta) calibrés grossièrement par corrélation d'ordre 1 sur
    log(r_t^2) — ce n'est pas une MLE complète, mais suffisant pour une feature de
    volatilité filtrée causale (chaque h_t n'utilise que r_1..r_t)."""
    ret = safe_pct_change(series).fillna(0.0).values
    n = len(ret)
    log_r2 = np.log(ret ** 2 + 1e-8)
    valid = np.isfinite(log_r2)
    if valid.sum() < 50:
        return pd.Series(np.nan, index=series.index, name="particle_filtered_vol")

    y = log_r2[valid]
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


def build_spike_features(series: pd.Series, prefix: str = "px") -> pd.DataFrame:
    df = pd.DataFrame({
        f"{prefix}_hurst_100d": rolling_hurst(series, 100),
        f"{prefix}_semivar_20d": rolling_semivariance(series, 20),
        f"{prefix}_skew_20d": rolling_skew(series, 20),
        f"{prefix}_particle_vol": particle_filter_vol(series),
    }, index=series.index)
    return df
