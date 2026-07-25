"""Features de volatilité avancées : EGARCH, Kalman filtré, HMM filtré (algorithme
forward causal, pas Viterbi/forward-backward qui utiliseraient le futur), proxy
Heston (spread/theta) et proxy VRP tronqué.

Ces familles étaient calibrées sur des données d'options dans certaines variantes
antérieures du projet ; ce module se limite à yfinance/FRED (décision actée pour ce
cadre), donc Heston et VRP sont ici des **proxys construits sur la volatilité
réalisée**, pas des calibrations sur volatilité implicite d'options — documenté
explicitement plutôt que présenté comme équivalent à une calibration d'options.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def egarch_conditional_vol(series: pd.Series, p: int = 1, o: int = 1, q: int = 1) -> pd.Series:
    """Volatilité conditionnelle EGARCH — intrinsèquement causale (récursive sur les
    résidus passés uniquement)."""
    from arch import arch_model

    ret = (series.pct_change().dropna() * 100)
    try:
        am = arch_model(ret, vol="EGARCH", p=p, o=o, q=q, dist="normal")
        res = am.fit(disp="off")
        cv = res.conditional_volatility / 100
        return cv.reindex(series.index).rename("egarch_vol")
    except Exception as e:
        print(f"  [WARN] EGARCH: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name="egarch_vol")


def kalman_filtered_level(series: pd.Series) -> pd.Series:
    """Niveau filtré (pas lissé) par un filtre de Kalman local-level : `.filter()`
    de pykalman est la passe forward causale (contrairement à `.smooth()`)."""
    from pykalman import KalmanFilter

    values = series.ffill().bfill().values.astype(float)
    if len(values) < 5:
        return pd.Series(np.nan, index=series.index, name="kalman_filtered")
    diffs = np.diff(values)
    kf = KalmanFilter(
        transition_matrices=[1], observation_matrices=[1],
        initial_state_mean=values[0],
        observation_covariance=max(np.var(values) * 0.1, 1e-6),
        transition_covariance=max(np.var(diffs) * 0.1, 1e-6) if len(diffs) else 1.0,
    )
    state_means, _ = kf.filter(values)
    return pd.Series(state_means.ravel(), index=series.index, name="kalman_filtered")


def hmm_filtered_stress_prob(series: pd.Series, n_states: int = 2, seed: int = 42) -> pd.Series:
    """Probabilité filtrée (causale) d'être dans l'état de plus haute variance d'un
    HMM gaussien à n_states régimes. Calcule l'algorithme forward à la main (en
    log-espace) plutôt que d'utiliser `predict_proba`/`decode` de hmmlearn, qui
    lissent avec le futur (forward-backward / Viterbi) — non causal ici."""
    from hmmlearn.hmm import GaussianHMM
    from scipy.special import logsumexp
    from scipy.stats import norm

    ret = series.pct_change().dropna()
    x = ret.values.reshape(-1, 1)
    if len(x) < 100:
        return pd.Series(np.nan, index=series.index, name="hmm_filtered_stress_prob")

    model = GaussianHMM(n_components=n_states, covariance_type="diag",
                         random_state=seed, n_iter=100)
    model.fit(x)

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
    """Proxy inspiré de Heston (mean-reversion de la variance) construit sur la
    variance réalisée, faute de volatilité implicite d'options dans ce cadre :
    `heston_theta` = niveau long terme, `heston_spread` = écart de la variance
    réalisée courante à ce niveau (l'équivalent du gap de retour à la moyenne)."""
    ret = series.pct_change()
    rv = (ret ** 2).rolling(short_window).mean() * 252
    theta = rv.rolling(long_window, min_periods=60).mean()
    spread = rv - theta
    return pd.DataFrame({"heston_theta": theta, "heston_spread": spread}, index=series.index)


def vrp_proxy(series: pd.Series, short_window: int = 10, long_window: int = 60,
              clip: tuple[float, float] = (-0.5, 0.5)) -> pd.Series:
    """Proxy de prime de risque de variance (VRP), tronqué : écart relatif entre
    vol réalisée courte et longue, faute de vol implicite d'options."""
    ret = series.pct_change()
    vol_short = ret.rolling(short_window).std() * np.sqrt(252)
    vol_long = ret.rolling(long_window).std() * np.sqrt(252)
    vrp = (vol_short - vol_long) / vol_long.replace(0, np.nan)
    return vrp.clip(*clip).rename("vrp_proxy_truncated")


def build_vol_model_features(series: pd.Series, prefix: str = "px") -> pd.DataFrame:
    parts = [
        egarch_conditional_vol(series).to_frame(),
        kalman_filtered_level(series).to_frame(),
        hmm_filtered_stress_prob(series).to_frame(),
        heston_proxy_features(series),
        vrp_proxy(series).to_frame(),
    ]
    df = pd.concat(parts, axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df
