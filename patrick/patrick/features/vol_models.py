"""Advanced volatility features: EGARCH, filtered Kalman, filtered HMM (causal
forward algorithm, not Viterbi/forward-backward which would use the future),
Heston proxy (spread/theta) and truncated VRP proxy.

These families used to be calibrated on options data in some earlier variants
of the project; this module is limited to yfinance/FRED (a decision made for
this framework), so Heston and VRP are here **proxies built on realized
volatility**, not calibrations on options implied volatility — explicitly
documented rather than presented as equivalent to an options calibration.

`fit_end_idx` (leak fixed, see test 0.2 "future corruption"): EGARCH/Kalman/
HMM/AR/MA/ARMA/ARIMA are not simple rolling windows — they estimate global
PARAMETERS (EGARCH omega/alpha/beta, HMM transition matrices, ARIMA
coefficients...) before producing a causal, point-by-point recursive output.
Estimating these parameters on the whole `series` (as before this fix) means
that even a fold's TRAIN values are informed by a later fold's TEST, since
the feature pool used to be built once for the entire history. `fit_end_idx`,
when provided, restricts parameter estimation to `series.iloc[:fit_end_idx]`
(the fold's train); the parameters are then frozen and applied to the causal
recursion over the whole `series` (train + test), with no re-estimation —
correct walk-forward. Without `fit_end_idx` (None), unchanged behavior (fit
on the whole series): used for the final production model
(`tracking/export.py`), which no longer has a test set to protect.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features._utils import safe_pct_change


def _fit_cutoff_date(series: pd.Series, fit_end_idx: int | None):
    if fit_end_idx is None:
        return None
    return series.index[min(fit_end_idx, len(series) - 1)]


def egarch_conditional_vol(series: pd.Series, p: int = 1, o: int = 1, q: int = 1,
                            fit_end_idx: int | None = None,
                            test_end_idx: int | None = None) -> pd.Series:
    """EGARCH conditional volatility — recursive over past residuals only, but
    whose parameters (omega/alpha/beta) are estimated on
    `series.iloc[:fit_end_idx]` only (walk-forward), then frozen and applied
    to the full series via `.fix()` (no re-estimation using the test set).

    `.fix()` alone is not enough: even with frozen parameters, `arch`
    internally recomputes, from the series passed to `arch_model()`, the
    backcast (recursion initialization value) AND the numeric variance bounds
    (`variance_bounds`, based on `np.var`/`np.max` of the whole series) — two
    leak channels independent of parameter estimation, detected by the future-
    corruption test by making them deliberately huge. Rather than re-patching
    every internal detail of `arch` (fragile, depends on undocumented
    versions), the TRAIN portion is taken directly from the train-only fit
    (`res`, which by construction has never seen the test set); only the TEST
    portion uses the full series via `.fix()`, where these residual numeric
    artifacts have no impact on the train's correction.

    `test_end_idx` (correction report, D2 -> N1): the backcast is confirmed
    non-retrospective (computed on the first observations only), but
    `variance_bounds` remains a real leak channel even though measured inert
    on realistic data (D2: 0.0 gap vs. the causal reference, 0 observations
    clipped, 3 seeds) -- only active under ~100000x out-of-scale corruption.
    Closing it by construction costs nothing (measured free, D2): when
    provided, the series passed to `.fix()` (`ret`) is truncated at the end
    of the current TEST fold rather than extending over the whole remaining
    history (`self.raw` upstream covers the whole dataset, not just this
    fold)."""
    from arch import arch_model

    ret = (safe_pct_change(series).dropna() * 100)
    cutoff = _fit_cutoff_date(series, fit_end_idx)
    fit_ret = ret[ret.index < cutoff] if cutoff is not None else ret
    try:
        am_fit = arch_model(fit_ret, vol="EGARCH", p=p, o=o, q=q, dist="normal")
        res = am_fit.fit(disp="off")
        if cutoff is None:
            cv = res.conditional_volatility / 100
            return cv.reindex(series.index).rename("egarch_vol")

        ret_for_fix = ret
        if test_end_idx is not None:
            test_end_date = series.index[min(test_end_idx, len(series) - 1)]
            ret_for_fix = ret[ret.index <= test_end_date]
        am_full = arch_model(ret_for_fix, vol="EGARCH", p=p, o=o, q=q, dist="normal")
        fixed = am_full.fix(res.params)
        cv = fixed.conditional_volatility.copy()
        cv.loc[res.conditional_volatility.index] = res.conditional_volatility.values
        cv = cv / 100
        return cv.reindex(series.index).rename("egarch_vol")
    except Exception as e:
        print(f"  [WARN] EGARCH: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name="egarch_vol")


def kalman_filtered_level(series: pd.Series, fit_end_idx: int | None = None) -> pd.Series:
    """Level filtered (not smoothed) by a local-level Kalman filter: pykalman's
    `.filter()` is the causal forward pass (unlike `.smooth()`). Both
    covariance hyperparameters (observation/transition) are estimated from
    the variance of the observations/differences on `values[:fit_end_idx]`
    only (the fold's train), not the whole series."""
    from pykalman import KalmanFilter

    values = series.ffill().bfill().values.astype(float)
    if len(values) < 5:
        return pd.Series(np.nan, index=series.index, name="kalman_filtered")
    fit_end = min(fit_end_idx, len(values)) if fit_end_idx is not None else len(values)
    fit_end = max(fit_end, 5)
    fit_values = values[:fit_end]
    diffs = np.diff(fit_values)
    kf = KalmanFilter(
        transition_matrices=[1], observation_matrices=[1],
        initial_state_mean=values[0],
        observation_covariance=max(np.var(fit_values) * 0.1, 1e-6),
        transition_covariance=max(np.var(diffs) * 0.1, 1e-6) if len(diffs) else 1.0,
    )
    state_means, _ = kf.filter(values)
    return pd.Series(state_means.ravel(), index=series.index, name="kalman_filtered")


def hmm_filtered_stress_prob(series: pd.Series, n_states: int = 2, seed: int = 42,
                              fit_end_idx: int | None = None) -> pd.Series:
    """Filtered (causal) probability of being in the highest-variance state of
    an n_states-regime Gaussian HMM. Computes the forward algorithm by hand
    (in log-space) rather than using hmmlearn's `predict_proba`/`decode`,
    which smooth using the future (forward-backward / Viterbi) — non-causal
    here. The model (means/variances/transitions) is estimated on
    `x[:fit_end_idx]` only (the fold's train), then applied forward over the
    whole series with no re-estimation."""
    from hmmlearn.hmm import GaussianHMM
    from scipy.special import logsumexp
    from scipy.stats import norm

    ret = safe_pct_change(series).dropna()
    x = ret.values.reshape(-1, 1)
    if len(x) < 100:
        return pd.Series(np.nan, index=series.index, name="hmm_filtered_stress_prob")

    cutoff = _fit_cutoff_date(series, fit_end_idx)
    if cutoff is not None:
        fit_mask = np.asarray(ret.index < cutoff)
        x_fit = x[fit_mask] if fit_mask.sum() >= 100 else x
    else:
        x_fit = x

    model = GaussianHMM(n_components=n_states, covariance_type="diag",
                         random_state=seed, n_iter=100)
    try:
        model.fit(x_fit)
    except Exception as e:
        # [FIX] safety net on top of safe_pct_change: a still-degenerate series
        # (near-constant, etc.) can make the HMM fit fail for reasons other than
        # inf values — must not crash the whole run.
        print(f"  [WARN] HMM: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name="hmm_filtered_stress_prob")

    n = len(x)
    means = model.means_.ravel()
    vars_ = np.clip(model.covars_.reshape(n_states, -1)[:, 0], 1e-12, None)
    log_start = np.log(model.startprob_ + 1e-300)
    log_trans = np.log(model.transmat_ + 1e-300)

    log_alpha = np.zeros((n, n_states))
    log_alpha[0] = log_start + norm.logpdf(x[0, 0], means, np.sqrt(vars_))
    for t in range(1, n):
        for k in range(n_states):
            log_alpha[t, k] = (logsumexp(log_alpha[t - 1] + log_trans[:, k])
                                + norm.logpdf(x[t, 0], means[k], np.sqrt(vars_[k])))
    log_norm = logsumexp(log_alpha, axis=1, keepdims=True)
    filtered = np.exp(log_alpha - log_norm)
    stress_state = int(np.argmax(vars_))

    out = pd.Series(filtered[:, stress_state], index=ret.index, name="hmm_filtered_stress_prob")
    return out.reindex(series.index)


def heston_proxy_features(series: pd.Series, short_window: int = 20,
                           long_window: int = 252) -> pd.DataFrame:
    """Heston-inspired proxy (variance mean-reversion) built on realized
    variance, in the absence of options implied volatility in this framework:
    `heston_theta` = long-term level, `heston_spread` = gap between current
    realized variance and this level (the mean-reversion gap equivalent).
    Rolling windows only (no global parameter estimated) — causal by
    construction, no `fit_end_idx` needed."""
    ret = safe_pct_change(series)
    rv = (ret ** 2).rolling(short_window).mean() * 252
    theta = rv.rolling(long_window, min_periods=60).mean()
    spread = rv - theta
    return pd.DataFrame({"heston_theta": theta, "heston_spread": spread}, index=series.index)


def vrp_proxy(series: pd.Series, short_window: int = 10, long_window: int = 60,
              clip: tuple[float, float] = (-0.5, 0.5)) -> pd.Series:
    """Truncated variance risk premium (VRP) proxy: relative gap between short
    and long realized vol, in the absence of options implied vol. Rolling
    windows only — causal by construction, no `fit_end_idx`."""
    ret = safe_pct_change(series)
    vol_short = ret.rolling(short_window).std() * np.sqrt(252)
    vol_long = ret.rolling(long_window).std() * np.sqrt(252)
    vrp = (vol_short - vol_long) / vol_long.replace(0, np.nan)
    return vrp.clip(*clip).rename("vrp_proxy_truncated")


def _arima_family_resid(series: pd.Series, order: tuple[int, int, int], name: str,
                         fit_end_idx: int | None = None) -> pd.Series:
    """Residual (surprise) of an AR/MA/ARMA/ARIMA(p,d,q) model — statsmodels'
    `.resid` is one-step-ahead in-sample, hence causal step by step. The
    coefficients are estimated on `ret[:fit_end_idx]` (the fold's train) only,
    then applied (`.apply`, with no re-estimation) to the full return series
    to produce residuals over train AND test."""
    from statsmodels.tsa.arima.model import ARIMA

    ret = safe_pct_change(series).dropna()
    if len(ret) < 30:
        return pd.Series(np.nan, index=series.index, name=name)

    cutoff = _fit_cutoff_date(series, fit_end_idx)
    fit_ret = ret[ret.index < cutoff] if cutoff is not None else ret
    if len(fit_ret) < 30:
        fit_ret = ret
    try:
        res = ARIMA(fit_ret.values, order=order).fit()
        if cutoff is None:
            resid = pd.Series(res.resid, index=ret.index, name=name)
            return resid.reindex(series.index)
        full_res = res.apply(ret.values)
        resid = pd.Series(full_res.resid, index=ret.index, name=name)
        return resid.reindex(series.index)
    except Exception as e:
        print(f"  [WARN] {name}: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name=name)


def ar_resid(series: pd.Series, lags: int = 5, fit_end_idx: int | None = None) -> pd.Series:
    return _arima_family_resid(series, (lags, 0, 0), "ar_resid", fit_end_idx)


def ma_resid(series: pd.Series, lags: int = 5, fit_end_idx: int | None = None) -> pd.Series:
    return _arima_family_resid(series, (0, 0, lags), "ma_resid", fit_end_idx)


def arma_resid(series: pd.Series, p: int = 2, q: int = 2, fit_end_idx: int | None = None) -> pd.Series:
    return _arima_family_resid(series, (p, 0, q), "arma_resid", fit_end_idx)


def arima_resid(series: pd.Series, p: int = 1, d: int = 1, q: int = 1,
                 fit_end_idx: int | None = None) -> pd.Series:
    return _arima_family_resid(series, (p, d, q), "arima_resid", fit_end_idx)


# Models whose parameters are estimated globally and therefore must be
# re-fit per fold (`fit_end_idx`) to stay walk-forward-safe. `test_end_idx`
# is only consumed by EGARCH (see N1, `egarch_conditional_vol` docstring) --
# the others ignore it: their causal recursion (Kalman `.filter()`, HMM
# forward, AR/MA/ARMA/ARIMA residuals applied step by step) is unaffected by
# the portion of `series` after the fold, unlike `arch_model(...).fix()`.
_PARAMETRIC_MODELS = {
    "egarch": lambda s, fit_end_idx, test_end_idx: egarch_conditional_vol(
        s, fit_end_idx=fit_end_idx, test_end_idx=test_end_idx).to_frame(),
    "kalman": lambda s, fit_end_idx, test_end_idx: kalman_filtered_level(s, fit_end_idx=fit_end_idx).to_frame(),
    "hmm": lambda s, fit_end_idx, test_end_idx: hmm_filtered_stress_prob(s, fit_end_idx=fit_end_idx).to_frame(),
    "ar": lambda s, fit_end_idx, test_end_idx: ar_resid(s, fit_end_idx=fit_end_idx).to_frame(),
    "ma": lambda s, fit_end_idx, test_end_idx: ma_resid(s, fit_end_idx=fit_end_idx).to_frame(),
    "arma": lambda s, fit_end_idx, test_end_idx: arma_resid(s, fit_end_idx=fit_end_idx).to_frame(),
    "arima": lambda s, fit_end_idx, test_end_idx: arima_resid(s, fit_end_idx=fit_end_idx).to_frame(),
}
# Pure rolling windows — no global parameter, `fit_end_idx`/`test_end_idx` ignored.
_NONPARAMETRIC_MODELS = {
    "heston_proxy": lambda s, fit_end_idx, test_end_idx: heston_proxy_features(s),
    "vrp_proxy": lambda s, fit_end_idx, test_end_idx: vrp_proxy(s).to_frame(),
}
_VOL_MODEL_BUILDERS = {**_PARAMETRIC_MODELS, **_NONPARAMETRIC_MODELS}

# Original behavior (before per-model selection) — unchanged for any caller
# that doesn't specify `models`.
_DEFAULT_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy"]

PARAMETRIC_VOL_MODELS = frozenset(_PARAMETRIC_MODELS)


def build_vol_model_features_base(series: pd.Series, prefix: str = "px",
                                   models: list[str] | None = None) -> pd.DataFrame:
    """Non-parametric subset of `models` (heston_proxy/vrp_proxy by default)
    — pure rolling windows, causal by construction, computed once for a whole
    run (shared across all folds)."""
    models = models if models is not None else _DEFAULT_MODELS
    selected = [m for m in models if m in _NONPARAMETRIC_MODELS]
    if not selected:
        return pd.DataFrame(index=series.index)
    df = pd.concat([_NONPARAMETRIC_MODELS[m](series, None, None) for m in selected], axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df


def build_vol_model_features_parametric(series: pd.Series, prefix: str = "px",
                                         models: list[str] | None = None,
                                         fit_end_idx: int | None = None,
                                         test_end_idx: int | None = None) -> pd.DataFrame:
    """Parametric subset of `models` (egarch/kalman/hmm/ar/ma/arma/arima by
    default) — to be recomputed per fold via `fit_end_idx` (see module
    docstring): parameters re-estimated only on each fold's train.
    `test_end_idx` (D2 -> N1): end of the current TEST fold, for EGARCH
    only (see `egarch_conditional_vol` docstring)."""
    models = models if models is not None else _DEFAULT_MODELS
    selected = [m for m in models if m in _PARAMETRIC_MODELS]
    if not selected:
        return pd.DataFrame(index=series.index)
    df = pd.concat([_PARAMETRIC_MODELS[m](series, fit_end_idx, test_end_idx) for m in selected], axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df


def build_vol_model_features(series: pd.Series, prefix: str = "px",
                              models: list[str] | None = None,
                              fit_end_idx: int | None = None,
                              test_end_idx: int | None = None) -> pd.DataFrame:
    """`models`: subset of `_VOL_MODEL_BUILDERS` to compute (default: the 5
    historical models of the VIX pipeline). An unknown name is ignored rather
    than crashing the whole run. `fit_end_idx`: estimation cutoff for the
    parametric models (egarch/kalman/hmm/ar/ma/arma/arima) — see module
    docstring. `test_end_idx`: end of the test fold, for EGARCH only
    (D2 -> N1). The Heston/VRP proxies (pure rolling windows) ignore both."""
    models = models if models is not None else _DEFAULT_MODELS
    parts = [_VOL_MODEL_BUILDERS[m](series, fit_end_idx, test_end_idx)
             for m in models if m in _VOL_MODEL_BUILDERS]
    if not parts:
        return pd.DataFrame(index=series.index)
    df = pd.concat(parts, axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df
