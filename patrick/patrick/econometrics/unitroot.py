"""Stationnarité et ruptures : ADF, KPSS, Phillips-Perron, DF-GLS (via `arch.unitroot`), Zivot-Andrews (rupture endogène, statsmodels), et
lecture croisée ADF x KPSS.

Les deux familles de tests ont des hypothèses nulles OPPOSÉES : ADF/PP/DF-GLS supposent une racine unitaire (rejeter = stationnaire) ; KPSS
suppose la stationnarité (rejeter = non stationnaire). Ne conclure que lorsqu'elles s'accordent."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

MIN_OBS = 30
ALPHA = 0.05
NULL_UNIT_ROOT = "unit_root"
NULL_STATIONARY = "stationary"


def cross_verdict(adf_p: float | None, kpss_p: float | None, alpha: float = ALPHA) -> str:
    """Lecture croisée : `stationary`, `unit_root`, `contradictory` (les deux rejettent : typiquement une rupture, une tendance ou une variance
    qui change), `inconclusive` (aucun ne rejette : pas assez de puissance pour trancher)."""
    if adf_p is None or kpss_p is None or not (np.isfinite(adf_p) and np.isfinite(kpss_p)):
        return "inconclusive"
    adf_rejects, kpss_rejects = adf_p < alpha, kpss_p < alpha
    if adf_rejects and not kpss_rejects:
        return "stationary"
    if not adf_rejects and kpss_rejects:
        return "unit_root"
    return "contradictory" if adf_rejects and kpss_rejects else "inconclusive"


def _summary(res, null: str, alpha: float) -> dict:
    try:
        crit = {str(k): float(v) for k, v in res.critical_values.items()}
    except Exception:  # noqa: BLE001 -- certaines versions n'exposent pas les valeurs critiques : on les omet, jamais le test
        crit = {}
    return {"stat": float(res.stat), "pvalue": float(res.pvalue), "lags": int(res.lags), "nobs": int(res.nobs), "null": null,
            "reject": bool(res.pvalue < alpha), "critical_values": crit}


def unit_root_tests(x: pd.Series, *, trend: str = "c", alpha: float = ALPHA) -> dict:
    """ADF, KPSS, PP, DF-GLS sur `x` (constante `c` ou constante + tendance `ct`) et verdict croisé ADF x KPSS.
    Un test qui échoue est renvoyé avec `error` au lieu d'être omis."""
    from arch.unitroot import ADF, DFGLS, KPSS, PhillipsPerron

    v = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if len(v) < MIN_OBS:
        raise ValueError(f"Pas assez d'observations pour un test de racine unitaire (minimum {MIN_OBS}, reçu {len(v)}).")
    if trend not in ("c", "ct"):
        raise ValueError("tendance inconnue : 'c' ou 'ct'")
    specs = {"adf": (lambda: ADF(v, trend=trend, method="aic"), NULL_UNIT_ROOT),
             "kpss": (lambda: KPSS(v, trend=trend), NULL_STATIONARY),
             "pp": (lambda: PhillipsPerron(v, trend=trend), NULL_UNIT_ROOT),
             "dfgls": (lambda: DFGLS(v, trend=trend, method="aic"), NULL_UNIT_ROOT)}
    tests: dict[str, dict] = {}
    for name, (build, null) in specs.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tests[name] = _summary(build(), null, alpha)
        except Exception as exc:  # noqa: BLE001 -- série dégénérée ou version d'`arch` différente : on le dit à l'écran
            tests[name] = {"error": str(exc).strip().splitlines()[0][:120] if str(exc).strip() else exc.__class__.__name__, "null": null}
    verdict = cross_verdict(tests.get("adf", {}).get("pvalue"), tests.get("kpss", {}).get("pvalue"), alpha)
    return {"n_obs": len(v), "trend": trend, "alpha": alpha, "tests": tests, "verdict": verdict}


def zivot_andrews(x: pd.Series, *, regression: str = "c", trim: float = 0.15, alpha: float = ALPHA) -> dict:
    """Zivot-Andrews (1992) : test de racine unitaire avec UNE rupture dont la date est choisie par les données (celle qui rend la
    racine unitaire la moins plausible). H0 : racine unitaire sans rupture. Rejeter = stationnaire avec rupture à la date `break_date`.
    `regression` : `c` (rupture de niveau), `t` (de pente), `ct` (les deux)."""
    from statsmodels.tsa.stattools import zivot_andrews as za

    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < 50:
        raise ValueError("Pas assez d'observations pour Zivot-Andrews (minimum 50).")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, pvalue, crit, baselag, bp = za(s.to_numpy(dtype=float), trim=trim, regression=regression, autolag="AIC")
    bp = int(bp)
    return {"stat": float(stat), "pvalue": float(pvalue), "lags": int(baselag), "break_index": bp,
            "break_date": s.index[bp].strftime("%Y-%m-%d") if isinstance(s.index, pd.DatetimeIndex) else None,
            "break_fraction": bp / len(s), "reject": bool(pvalue < alpha), "null": NULL_UNIT_ROOT,
            "critical_values": {str(k): float(v) for k, v in crit.items()}, "regression": regression, "n_obs": len(s)}
