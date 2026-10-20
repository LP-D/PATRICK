"""Régimes de volatilité par HMM causal (`features/regime_detection.py`) : frise des régimes sur la période évaluée et performance du modèle
dans chacun.

Le HMM est ajusté sur l'historique AVANT le premier jour de test uniquement (`fit_end_idx`), puis filtré jour après jour : le régime d'une
date ne connaît que le passé. Le calcul prend 4 à 6 s : la section se charge à la demande et son résultat est gardé (clé : snapshot, cible,
nombre d'états, premier jour de test)."""
from __future__ import annotations

import logging
import threading
import warnings

import numpy as np
import pandas as pd

from patrick.analysis import sec_perf
from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx, iso

_cache: dict[tuple, dict] = {}
_lock = threading.Lock()
REGIME_ORDER = ["calme", "normal", "stress"]
CODE = {"calme": 0, "normal": 1, "stress": 2}


def _detect(levels: pd.Series, n_states: int, fit_end_idx: int):
    from patrick.features.regime_detection import detect_regime
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logging.getLogger("hmmlearn").setLevel(logging.ERROR)
        return detect_regime(levels.ffill(), n_states=n_states, fit_end_idx=fit_end_idx)


def regimes(ctx: Ctx) -> dict:
    fr = ctx.fr
    if fr.levels is None:
        return {"available": False, "reason": "no_returns"}
    d = ctx.evaluated(("test", "holdout"))
    if len(d) < 60:
        return {"available": False, "reason": "not_enough"}
    n_states = ctx.int_param("n_states", 3, lo=2, hi=4)
    first = d["ts"].min()
    fit_end = max(1, int(fr.levels.index.searchsorted(first)) - 1)      # dernier rendement ajusté : celui de la veille du premier jour de test
    key = (fr.run.get("snapshot_id"), fr.run["target"], n_states, fit_end)
    with _lock:
        res = _cache.get(key)
    if res is None:
        try:
            res = _detect(fr.levels, n_states, fit_end)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            return {"available": False, "reason": "regime_failed"}
        with _lock:
            _cache[key] = res
            if len(_cache) > 8:
                _cache.pop(next(iter(_cache)))
    reg = res.regime
    if reg.isna().all():
        return {"available": False, "reason": "regime_failed"}
    span = reg.loc[first:d["ts"].max()].dropna()
    idx = sc.thin_indices(len(span), 900)
    d = d.copy()
    d["regime"] = d["ts"].map(reg)
    d = d[d["regime"].notna()]
    d["code"] = d["regime"].map(CODE)
    table = sec_perf._group_table(d, "regime", REGIME_ORDER)
    share = {r: float((span == r).mean()) for r in REGIME_ORDER}
    stress = res.stress_prob.loc[span.index]
    runs = []                                                 # séjours consécutifs dans un régime (début, fin, régime)
    start = 0
    vals = span.to_numpy()
    for i in range(1, len(vals) + 1):
        if i == len(vals) or vals[i] != vals[start]:
            runs.append({"start": iso(span.index[start]), "end": iso(span.index[i - 1]), "regime": str(vals[start]), "days": i - start})
            start = i
    changes = len(runs) - 1
    return {"available": True, "n_states": int(res.n_states_selected), "cutoffs": [float(c) for c in res.threshold_cutoffs], "share": share,
            "t": [iso(span.index[i]) for i in idx], "stress": stress.to_numpy()[idx], "code": span.map(CODE).to_numpy()[idx], "table": table,
            "n_changes": int(changes), "mean_stay": float(np.mean([r["days"] for r in runs])) if runs else None,
            "longest": sorted(runs, key=lambda r: -r["days"])[:5], "fit_end": iso(fr.levels.index[min(fit_end, len(fr.levels) - 1)]),
            "folds": [{"fold": int(f), "split": s, "start": iso(g["ts"].min()), "end": iso(g["ts"].max())}
                      for (s, f), g in d.groupby(["split_name", "fold"])]}
