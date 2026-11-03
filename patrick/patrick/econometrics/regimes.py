"""Régimes : Markov-switching (statsmodels, moyenne et/ou variance qui changent d'état) et lecture du HMM filtré déjà présent dans le projet
(`features/regime_detection.py`, pas de second HMM).

Deux lectures des probabilités d'état, à ne pas confondre :
- FILTRÉE : P(état à t | rendements jusqu'à t). Ce qu'on aurait su ce jour-là. La seule utilisable pour décider ou comme variable d'un modèle ;
- LISSÉE : P(état à t | tout l'échantillon). Plus nette, mais elle regarde l'avenir : pour décrire le passé uniquement.
Les paramètres du modèle sont, dans les deux cas, estimés sur tout l'échantillon : la lecture est descriptive. Les rendements sont mis en pourcent en interne.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from patrick.exploration.studies import clean
from patrick.features import regime_detection as RD

MIN_OBS = 100
MAX_OBS = 3000
BIC_MARGIN = 2.0


def _prepare(x: pd.Series, max_obs: int) -> pd.Series:
    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < MIN_OBS:
        raise ValueError(f"Pas assez d'observations pour des régimes (minimum {MIN_OBS}, reçu {len(s)}).")
    return s.iloc[-max_obs:] * 100.0


def markov_switching(x: pd.Series, k_regimes: int = 2, *, switching_mean: bool = True, switching_variance: bool = True,
                     max_obs: int = MAX_OBS) -> dict:
    """Régression de Markov (Hamilton 1989, Kim-Nelson) à `k_regimes` états sur `x` (rendements décimaux). Compare au modèle à un seul régime par le BIC :
    sur un bruit sans régime, un modèle à deux états trouve souvent des états « imaginaires », et le BIC sert à le dire."""
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    if k_regimes < 2:
        raise ValueError("Il faut au moins 2 régimes.")
    y = _prepare(x, max_obs)
    vals = y.to_numpy()
    model = MarkovRegression(vals, k_regimes=k_regimes, trend="c", switching_trend=switching_mean, switching_variance=switching_variance)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = model.fit(disp=False)
    names = list(model.param_names)
    p = dict(zip(names, np.asarray(res.params, dtype=float), strict=True))

    def pick(prefix: str, i: int) -> float:
        return p[f"{prefix}[{i}]"] if f"{prefix}[{i}]" in p else p[prefix]

    trans = np.asarray(res.regime_transition)[:, :, 0]                  # trans[i, j] = P(S_t = i | S_{t-1} = j)
    filtered = np.clip(np.asarray(res.filtered_marginal_probabilities, dtype=float), 0.0, 1.0)        # écarte les 1,0000000000000004 d'arrondi
    smoothed = np.clip(np.asarray(res.smoothed_marginal_probabilities, dtype=float), 0.0, 1.0)
    durations = np.asarray(res.expected_durations, dtype=float)
    regimes = []
    for i in range(k_regimes):
        var = pick("sigma2", i)
        regimes.append({"regime": i, "mean_pct": pick("const", i), "var_pct2": var, "vol_daily_pct": float(np.sqrt(var)), "vol_annual_pct": float(np.sqrt(var * 252)),
                        "p_stay": float(trans[i, i]), "expected_duration": float(durations[i]), "share": float(smoothed[:, i].mean())})
    stress = int(np.argmax([r["var_pct2"] for r in regimes])) if switching_variance else int(np.argmin([r["mean_pct"] for r in regimes]))
    n = len(vals)
    llf1 = -0.5 * n * (np.log(2 * np.pi * vals.var()) + 1.0)
    bic1 = -2.0 * llf1 + 2.0 * np.log(n)
    converged = bool((getattr(res, "mle_retvals", None) or {}).get("converged", True))
    verdict = ("not_converged" if not converged else "regimes_supported" if res.bic < bic1 - BIC_MARGIN else "single_regime_enough")
    return clean({"k_regimes": k_regimes, "switching_mean": switching_mean, "switching_variance": switching_variance, "converged": converged, "n_obs": n,
                  "regimes": regimes, "stress_regime": stress, "transition": trans, "loglik": float(res.llf), "aic": float(res.aic), "bic": float(res.bic),
                  "bic_single_regime": float(bic1), "delta_bic": float(res.bic - bic1), "verdict": verdict, "bic_margin": BIC_MARGIN,
                  "dates": [d.strftime("%Y-%m-%d") for d in y.index], "filtered_stress": filtered[:, stress], "smoothed_stress": smoothed[:, stress],
                  "scale": "percent"})


def hmm_reading(x: pd.Series, candidates: tuple[int, ...] = (2, 3, 4), *, seed: int = 42, n_init: int = 3, max_obs: int = MAX_OBS) -> dict:
    """Lecture du HMM gaussien du projet : nombre d'états choisi par le BIC (`select_n_states_bic`), probabilités FILTRÉES (`filtered_state_probs`,
    algorithme avant écrit à la main, jamais `predict_proba`). État de stress = celui de plus forte variance."""
    y = _prepare(x, max_obs)
    obs = y.to_numpy().reshape(-1, 1)                                   # en pourcent : le plancher de covariance de hmmlearn (1e-3) écraserait des variances décimales (1e-4)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sel = RD.select_n_states_bic(obs, tuple(candidates), seed=seed, n_init=n_init)
        k = min(sel, key=lambda c: sel[c]["bic"])
        # l'EM de hmmlearn s'arrête parfois sur un optimum local (deux états quasi identiques) : on garde le meilleur de `n_init` départs,
        # comme `select_n_states_bic` le fait pour le BIC
        best = None
        for i in range(max(1, n_init)):
            cand = RD.filtered_state_probs(obs, k, seed=seed + i)
            score = float(cand[1].score(obs))
            if best is None or score > best[0]:
                best = (score, cand)
        probs, model = best[1]
    means = np.asarray(model.means_).ravel()
    var = np.clip(np.asarray(model.covars_).reshape(k, -1)[:, 0], 1e-12, None)
    trans = np.asarray(model.transmat_)
    stress = int(np.argmax(var))
    states = [{"state": i, "mean_pct": float(means[i]), "vol_daily_pct": float(np.sqrt(var[i])), "vol_annual_pct": float(np.sqrt(var[i] * 252)),
               "p_stay": float(trans[i, i]), "share": float(probs[:, i].mean())} for i in range(k)]
    bic = [{"n_states": int(c), "bic": sel[c]["bic"], "aic": sel[c]["aic"], "loglik": sel[c]["log_likelihood"], "n_params": sel[c]["n_params"]} for c in sorted(sel)]
    return clean({"n_states": k, "states": states, "stress_state": stress, "bic": bic, "causal": True, "n_obs": len(y),
                  "dates": [d.strftime("%Y-%m-%d") for d in y.index], "stress_prob": probs[:, stress], "scale": "percent"})
