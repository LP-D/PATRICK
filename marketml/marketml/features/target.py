"""Cible directionnelle/amplitude 4 classes (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT)
avec seuils causaux conditionnels au régime — logique établie dans tout le projet
VIX (`build_target`), généralisée : la série n'est plus câblée en dur sur le VIX.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET_COL = "target_class"


def build_target(series: pd.Series, horizon: int, split_idx: int,
                  flat_thr: float = 0.003) -> tuple[pd.Series, pd.Series, dict]:
    """Retourne (target, regime_par_date, seuils_par_regime). Les seuils de régime
    (CALM/NORMAL/STRESS, quantiles 33%/67% du niveau) et de classification (quantiles
    25%/75% du rendement, par régime) sont fittés uniquement sur `series[:split_idx]`
    (train du fold) — aucune fuite du futur."""
    s = series.ffill().bfill()
    s_tr = s.iloc[:split_idx]
    calm_thr = s_tr.quantile(0.33)
    stress_thr = s_tr.quantile(0.67)
    regime = pd.Series("NORMAL", index=s.index)
    regime[s < calm_thr] = "CALM"
    regime[s >= stress_thr] = "STRESS"

    ret = (s.shift(-horizon) / s) - 1
    flat = ret.abs() < flat_thr
    ret = ret.loc[~flat].dropna()
    reg_r = regime.reindex(ret.index)

    cut_date = s.index[min(split_idx, len(s) - 1)]
    ret_tr = ret.loc[ret.index < cut_date]
    reg_tr = reg_r.loc[ret_tr.index]

    thr = {}
    for reg in ["CALM", "NORMAL", "STRESS"]:
        sub = ret_tr[reg_tr == reg]
        thr[reg] = (
            sub.quantile(0.25) if len(sub) >= 20 else ret_tr.quantile(0.25),
            sub.quantile(0.75) if len(sub) >= 20 else ret_tr.quantile(0.75),
        )
    thr["GLOBAL"] = (ret_tr.quantile(0.25), ret_tr.quantile(0.75))

    def classify(r: float, reg: str) -> int:
        q25, q75 = thr.get(reg, (0, 0))
        if r < q25:
            return 0
        if r < 0:
            return 1
        if r < q75:
            return 2
        return 3

    target = pd.Series(
        [classify(r, reg_r[i]) for i, r in ret.items()], index=ret.index, name=TARGET_COL
    )
    return target, reg_r, thr


def classify_return(r: float, reg: str, thr: dict) -> int:
    q25, q75 = thr.get(reg, (0, 0))
    if r < q25:
        return 0
    if r < 0:
        return 1
    if r < q75:
        return 2
    return 3
