"""Features de volatilité avancées : EGARCH, Kalman filtré, HMM filtré (algorithme
forward causal, pas Viterbi/forward-backward qui utiliseraient le futur), proxy
Heston (spread/theta) et proxy VRP tronqué.

Ces familles étaient calibrées sur des données d'options dans certaines variantes
antérieures du projet ; ce module se limite à yfinance/FRED (décision actée pour ce
cadre), donc Heston et VRP sont ici des **proxys construits sur la volatilité
réalisée**, pas des calibrations sur volatilité implicite d'options — documenté
explicitement plutôt que présenté comme équivalent à une calibration d'options.

`fit_end_idx` (fuite corrigée, cf. test 0.2 "corruption du futur") : EGARCH/Kalman/
HMM/AR/MA/ARMA/ARIMA ne sont pas de simples fenêtres glissantes — ils estiment des
PARAMÈTRES globaux (omega/alpha/beta EGARCH, matrices de transition HMM, coefficients
ARIMA...) avant de produire une sortie récursive causale point par point. Estimer ces
paramètres sur `series` en entier (comme avant ce fix) fait que même les valeurs de
TRAIN d'un fold sont informées par du TEST d'un fold ultérieur, puisque le pool de
features était construit une seule fois pour tout l'historique. `fit_end_idx`, quand
fourni, restreint l'estimation des paramètres à `series.iloc[:fit_end_idx]` (train du
fold) ; les paramètres sont ensuite figés et appliqués à la récursion causale sur
`series` en entier (train + test), sans ré-estimation — walk-forward correct. Sans
`fit_end_idx` (None), comportement inchangé (fit sur toute la série) : utilisé pour le
modèle de production final (`tracking/export.py`), qui n'a plus de test à protéger.
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
                            fit_end_idx: int | None = None) -> pd.Series:
    """Volatilité conditionnelle EGARCH — récursive sur les résidus passés
    uniquement, mais dont les paramètres (omega/alpha/beta) sont estimés sur
    `series.iloc[:fit_end_idx]` seulement (walk-forward), puis figés et appliqués
    à la série complète via `.fix()` (pas de ré-estimation avec le test).

    `.fix()` seul ne suffit pas : même à paramètres figés, `arch` recalcule en
    interne, à partir de la série passée à `arch_model()`, le backcast (valeur
    d'initialisation de la récursion) ET les bornes numériques de variance
    (`variance_bounds`, basées sur `np.var`/`np.max` de toute la série) — deux
    canaux de fuite indépendants de l'estimation des paramètres, détectés par le
    test de corruption du futur en les rendant volontairement énormes. Plutôt que
    de re-patcher chaque détail interne d'`arch` (fragile, dépend de versions non
    documentées), la portion TRAIN est prise directement du fit train-only (`res`,
    qui n'a par construction jamais vu le test) ; seule la portion TEST utilise la
    série complète via `.fix()`, où ces artefacts numériques résiduels n'ont pas
    d'impact sur la correction du train."""
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

        am_full = arch_model(ret, vol="EGARCH", p=p, o=o, q=q, dist="normal")
        fixed = am_full.fix(res.params)
        cv = fixed.conditional_volatility.copy()
        cv.loc[res.conditional_volatility.index] = res.conditional_volatility.values
        cv = cv / 100
        return cv.reindex(series.index).rename("egarch_vol")
    except Exception as e:
        print(f"  [WARN] EGARCH: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name="egarch_vol")


def kalman_filtered_level(series: pd.Series, fit_end_idx: int | None = None) -> pd.Series:
    """Niveau filtré (pas lissé) par un filtre de Kalman local-level : `.filter()`
    de pykalman est la passe forward causale (contrairement à `.smooth()`). Les deux
    hyperparamètres de covariance (observation/transition) sont estimés à partir de
    la variance des observations/différences sur `values[:fit_end_idx]` uniquement
    (train du fold), pas sur toute la série."""
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
    """Probabilité filtrée (causale) d'être dans l'état de plus haute variance d'un
    HMM gaussien à n_states régimes. Calcule l'algorithme forward à la main (en
    log-espace) plutôt que d'utiliser `predict_proba`/`decode` de hmmlearn, qui
    lissent avec le futur (forward-backward / Viterbi) — non causal ici. Le modèle
    (moyennes/variances/transitions) est estimé sur `x[:fit_end_idx]` seulement
    (train du fold), puis appliqué en avant sur toute la série sans ré-estimation."""
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
    réalisée courante à ce niveau (l'équivalent du gap de retour à la moyenne).
    Fenêtres glissantes uniquement (pas de paramètre global estimé) — causal par
    construction, pas de `fit_end_idx` nécessaire."""
    ret = safe_pct_change(series)
    rv = (ret ** 2).rolling(short_window).mean() * 252
    theta = rv.rolling(long_window, min_periods=60).mean()
    spread = rv - theta
    return pd.DataFrame({"heston_theta": theta, "heston_spread": spread}, index=series.index)


def vrp_proxy(series: pd.Series, short_window: int = 10, long_window: int = 60,
              clip: tuple[float, float] = (-0.5, 0.5)) -> pd.Series:
    """Proxy de prime de risque de variance (VRP), tronqué : écart relatif entre
    vol réalisée courte et longue, faute de vol implicite d'options. Fenêtres
    glissantes uniquement — causal par construction, pas de `fit_end_idx`."""
    ret = safe_pct_change(series)
    vol_short = ret.rolling(short_window).std() * np.sqrt(252)
    vol_long = ret.rolling(long_window).std() * np.sqrt(252)
    vrp = (vol_short - vol_long) / vol_long.replace(0, np.nan)
    return vrp.clip(*clip).rename("vrp_proxy_truncated")


def _arima_family_resid(series: pd.Series, order: tuple[int, int, int], name: str,
                         fit_end_idx: int | None = None) -> pd.Series:
    """Résidu (surprise) d'un modèle AR/MA/ARMA/ARIMA(p,d,q) — `.resid` de
    statsmodels est one-step-ahead in-sample, donc causal pas à pas. Les
    coefficients sont estimés sur `ret[:fit_end_idx]` (train du fold) uniquement,
    puis appliqués (`.apply`, sans ré-estimation) à la série complète des
    rendements pour produire les résidus sur train ET test."""
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


# Modèles dont les paramètres sont estimés globalement et doivent donc être
# réajustés par fold (`fit_end_idx`) pour rester walk-forward-safe.
_PARAMETRIC_MODELS = {
    "egarch": lambda s, fit_end_idx: egarch_conditional_vol(s, fit_end_idx=fit_end_idx).to_frame(),
    "kalman": lambda s, fit_end_idx: kalman_filtered_level(s, fit_end_idx=fit_end_idx).to_frame(),
    "hmm": lambda s, fit_end_idx: hmm_filtered_stress_prob(s, fit_end_idx=fit_end_idx).to_frame(),
    "ar": lambda s, fit_end_idx: ar_resid(s, fit_end_idx=fit_end_idx).to_frame(),
    "ma": lambda s, fit_end_idx: ma_resid(s, fit_end_idx=fit_end_idx).to_frame(),
    "arma": lambda s, fit_end_idx: arma_resid(s, fit_end_idx=fit_end_idx).to_frame(),
    "arima": lambda s, fit_end_idx: arima_resid(s, fit_end_idx=fit_end_idx).to_frame(),
}
# Fenêtres glissantes pures — aucun paramètre global, `fit_end_idx` ignoré.
_NONPARAMETRIC_MODELS = {
    "heston_proxy": lambda s, fit_end_idx: heston_proxy_features(s),
    "vrp_proxy": lambda s, fit_end_idx: vrp_proxy(s).to_frame(),
}
_VOL_MODEL_BUILDERS = {**_PARAMETRIC_MODELS, **_NONPARAMETRIC_MODELS}

# Comportement d'origine (avant sélection par modèle) — inchangé pour tout appelant
# qui ne précise pas `models`.
_DEFAULT_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy"]

PARAMETRIC_VOL_MODELS = frozenset(_PARAMETRIC_MODELS)


def build_vol_model_features_base(series: pd.Series, prefix: str = "px",
                                   models: list[str] | None = None) -> pd.DataFrame:
    """Sous-ensemble non-paramétrique de `models` (heston_proxy/vrp_proxy par
    défaut) — fenêtres glissantes pures, causal par construction, calculé une
    seule fois pour tout un run (partagé par tous les folds)."""
    models = models if models is not None else _DEFAULT_MODELS
    selected = [m for m in models if m in _NONPARAMETRIC_MODELS]
    if not selected:
        return pd.DataFrame(index=series.index)
    df = pd.concat([_NONPARAMETRIC_MODELS[m](series, None) for m in selected], axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df


def build_vol_model_features_parametric(series: pd.Series, prefix: str = "px",
                                         models: list[str] | None = None,
                                         fit_end_idx: int | None = None) -> pd.DataFrame:
    """Sous-ensemble paramétrique de `models` (egarch/kalman/hmm/ar/ma/arma/arima
    par défaut) — à recalculer par fold via `fit_end_idx` (cf. docstring de
    module) : paramètres réestimés uniquement sur le train de chaque fold."""
    models = models if models is not None else _DEFAULT_MODELS
    selected = [m for m in models if m in _PARAMETRIC_MODELS]
    if not selected:
        return pd.DataFrame(index=series.index)
    df = pd.concat([_PARAMETRIC_MODELS[m](series, fit_end_idx) for m in selected], axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df


def build_vol_model_features(series: pd.Series, prefix: str = "px",
                              models: list[str] | None = None,
                              fit_end_idx: int | None = None) -> pd.DataFrame:
    """`models` : sous-ensemble de `_VOL_MODEL_BUILDERS` à calculer (défaut :
    les 5 modèles historiques du pipeline VIX). Un nom inconnu est ignoré plutôt
    que de faire planter tout le run. `fit_end_idx` : borne d'estimation des
    modèles paramétriques (egarch/kalman/hmm/ar/ma/arma/arima) — cf. docstring
    de module. Les proxys Heston/VRP (fenêtres glissantes pures) l'ignorent."""
    models = models if models is not None else _DEFAULT_MODELS
    parts = [_VOL_MODEL_BUILDERS[m](series, fit_end_idx) for m in models if m in _VOL_MODEL_BUILDERS]
    if not parts:
        return pd.DataFrame(index=series.index)
    df = pd.concat(parts, axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    return df
