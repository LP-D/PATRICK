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

from patrick.features._utils import safe_pct_change


def egarch_conditional_vol(series: pd.Series, p: int = 1, o: int = 1, q: int = 1) -> pd.Series:
    """Volatilité conditionnelle EGARCH — intrinsèquement causale (récursive sur les
    résidus passés uniquement)."""
    from arch import arch_model

    ret = (safe_pct_change(series).dropna() * 100)
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

    ret = safe_pct_change(series).dropna()
    x = ret.values.reshape(-1, 1)
    if len(x) < 100:
        return pd.Series(np.nan, index=series.index, name="hmm_filtered_stress_prob")

    model = GaussianHMM(n_components=n_states, covariance_type="diag",
                         random_state=seed, n_iter=100)
    try:
        model.fit(x)
    except Exception as e:
        # [FIX] filet de sécurité en plus du safe_pct_change : une série encore
        # dégénérée (quasi constante, etc.) peut faire échouer l'ajustement HMM
        # pour d'autres raisons que des inf — ne doit pas planter tout le run.
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
    """Proxy inspiré de Heston (mean-reversion de la variance) construit sur la
    variance réalisée, faute de volatilité implicite d'options dans ce cadre :
    `heston_theta` = niveau long terme, `heston_spread` = écart de la variance
    réalisée courante à ce niveau (l'équivalent du gap de retour à la moyenne)."""
    ret = safe_pct_change(series)
    rv = (ret ** 2).rolling(short_window).mean() * 252
    theta = rv.rolling(long_window, min_periods=60).mean()
    spread = rv - theta
    return pd.DataFrame({"heston_theta": theta, "heston_spread": spread}, index=series.index)


def vrp_proxy(series: pd.Series, short_window: int = 10, long_window: int = 60,
              clip: tuple[float, float] = (-0.5, 0.5)) -> pd.Series:
    """Proxy de prime de risque de variance (VRP), tronqué : écart relatif entre
    vol réalisée courte et longue, faute de vol implicite d'options."""
    ret = safe_pct_change(series)
    vol_short = ret.rolling(short_window).std() * np.sqrt(252)
    vol_long = ret.rolling(long_window).std() * np.sqrt(252)
    vrp = (vol_short - vol_long) / vol_long.replace(0, np.nan)
    return vrp.clip(*clip).rename("vrp_proxy_truncated")


def _arima_family_resid(series: pd.Series, order: tuple[int, int, int], name: str) -> pd.Series:
    """Résidu (surprise) d'un modèle AR/MA/ARMA/ARIMA(p,d,q) ajusté une fois sur
    tout l'historique des rendements — `.resid` de statsmodels est one-step-ahead
    in-sample, donc causal pas à pas comme les autres features de ce module, même
    si les paramètres eux-mêmes sont estimés sur la série complète (même limite
    déjà acceptée pour EGARCH/HMM ci-dessus)."""
    from statsmodels.tsa.arima.model import ARIMA

    ret = safe_pct_change(series).dropna()
    if len(ret) < 30:
        return pd.Series(np.nan, index=series.index, name=name)
    try:
        res = ARIMA(ret.values, order=order).fit()
        resid = pd.Series(res.resid, index=ret.index, name=name)
        return resid.reindex(series.index)
    except Exception as e:
        print(f"  [WARN] {name}: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name=name)


def ar_resid(series: pd.Series, lags: int = 5) -> pd.Series:
    return _arima_family_resid(series, (lags, 0, 0), "ar_resid")


def ma_resid(series: pd.Series, lags: int = 5) -> pd.Series:
    return _arima_family_resid(series, (0, 0, lags), "ma_resid")


def arma_resid(series: pd.Series, p: int = 2, q: int = 2) -> pd.Series:
    return _arima_family_resid(series, (p, 0, q), "arma_resid")


def arima_resid(series: pd.Series, p: int = 1, d: int = 1, q: int = 1) -> pd.Series:
    return _arima_family_resid(series, (p, d, q), "arima_resid")


_VOL_MODEL_BUILDERS = {
    "egarch": lambda s: egarch_conditional_vol(s).to_frame(),
    "kalman": lambda s: kalman_filtered_level(s).to_frame(),
    "hmm": lambda s: hmm_filtered_stress_prob(s).to_frame(),
    "heston_proxy": lambda s: heston_proxy_features(s),
    "vrp_proxy": lambda s: vrp_proxy(s).to_frame(),
    "ar": lambda s: ar_resid(s).to_frame(),
    "ma": lambda s: ma_resid(s).to_frame(),
    "arma": lambda s: arma_resid(s).to_frame(),
    "arima": lambda s: arima_resid(s).to_frame(),
}

# Comportement d'origine (avant sélection par modèle) — inchangé pour tout appelant
# qui ne précise pas `models`.
_DEFAULT_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy"]


def build_vol_model_features(series: pd.Series, prefix: str = "px",
                              models: list[str] | None = None) -> pd.DataFrame:
    """`models` : sous-ensemble de `_VOL_MODEL_BUILDERS` à calculer (défaut :
    les 5 modèles historiques du pipeline VIX). Un nom inconnu est ignoré plutôt
    que de faire planter tout le run."""
    models = models if models is not None else _DEFAULT_MODELS
    parts = [_VOL_MODEL_BUILDERS[m](series) for m in models if m in _VOL_MODEL_BUILDERS]
    if not parts:
        return pd.DataFrame(index=series.index)
    df = pd.concat(parts, axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df
