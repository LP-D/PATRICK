"""Régime de marché du jour (A11) : la classification de `research/phase9.py` branchée sur la page des fonds.

Entrées (Yahoo, cinq ans d'historique) : niveau du VIX et son centile sur 252 séances, rendement du S&P 500 sur 20 séances, volatilité
réalisée annualisée du S&P 500 sur 20 séances. Seuils par défaut de phase9 (`RegimeThresholds` : VIX 15 / 25 / 35 / 50, centiles 25 / 50 /
75 / 90, rendement 0 / -2 % / -8 %, volatilité 12 / 20 / 35 %). Un régime OBSERVÉ, jamais prédit.

Affiché à titre de contexte : le pilote ne module PAS l'exposition selon le régime. Une telle modulation n'a pas été mesurée ; le jour où
elle l'est (Sharpe des fonds avec et sans, sur le même historique), elle passera par une option du pilote, comme `vol_model`.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from patrick.research import phase9

VIX, MARKET = "^VIX", "^GSPC"
PCT_WINDOW, RET_WINDOW = 252, 20
ORDER = phase9.REGIME_LABELS                      # du plus calme au plus agité


def _series(payload: dict) -> pd.Series:
    dates, closes = payload.get("dates") or [], payload.get("closes") or []
    s = pd.Series(closes, index=pd.to_datetime(dates), dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def classify(vix: pd.Series, market: pd.Series) -> dict | None:
    """Régime du dernier jour commun aux deux séries, ou None si l'historique est trop court."""
    df = pd.concat({"vix": vix, "px": market}, axis=1).dropna()
    if len(df) < PCT_WINDOW + 1:
        return None
    rets = np.log(df["px"]).diff()
    vix_pct = df["vix"].rolling(PCT_WINDOW).apply(lambda w: 100.0 * (w <= w[-1]).mean(), raw=True)
    ret20 = df["px"].pct_change(RET_WINDOW)
    vol20 = rets.rolling(RET_WINDOW).std() * math.sqrt(252)
    last = pd.concat({"vix": df["vix"], "pct": vix_pct, "ret": ret20, "vol": vol20}, axis=1).dropna()
    if last.empty:
        return None
    labels, confidence = phase9.classify_regime_daily(last["vix"], last["pct"], last["ret"], last["vol"])
    row = last.iloc[-1]
    recent = list(labels[-RET_WINDOW:])
    label = str(labels[-1])
    return {"day": last.index[-1].strftime("%Y-%m-%d"), "label": label, "confidence": float(confidence[-1]),
            "vix": float(row["vix"]), "vix_pct": float(row["pct"]), "ret20": float(row["ret"]), "vol20": float(row["vol"]),
            "triggers": _triggers(label, row), "days_in_regime": _run_length(list(labels)),
            "recent": {lab: recent.count(lab) for lab in ORDER}}


def _triggers(label: str, row: pd.Series, th: phase9.RegimeThresholds = phase9.DEFAULT_REGIME_THRESHOLDS) -> list[str]:
    """Critères qui placent le jour dans son régime (`vix`, `vix_pct`, `ret20`, `vol20`) ; vide pour CALM."""
    level = {"CRASH": "crash", "STRESS": "stress", "NORMAL": "normal"}.get(label)
    if level is None:
        return []
    ret_cut = {"crash": th.market_return_crash, "stress": th.market_return_stress, "normal": th.market_return_calm}[level]
    vol_cut = {"crash": th.realized_vol_crash, "stress": th.realized_vol_stress, "normal": th.realized_vol_calm}[level]
    hits = [("vix", row["vix"] >= getattr(th, f"{level}_vix")), ("vix_pct", row["pct"] >= getattr(th, f"{level}_vix_percentile")),
            ("ret20", row["ret"] <= ret_cut), ("vol20", row["vol"] >= vol_cut)]
    return [name for name, hit in hits if hit]


def _run_length(labels: list[str]) -> int:
    n = 0
    for lab in reversed(labels):
        if lab != labels[-1]:
            break
        n += 1
    return n


def current(loader=None) -> dict | None:
    """Régime du jour à partir des cours Yahoo (cache de l'application) ; None si une série manque."""
    if loader is None:
        from patrick.webapp import market_data

        def loader(symbol: str) -> dict:
            return market_data.price_history(symbol, "yfinance", "5y")
    vix, market = _series(loader(VIX)), _series(loader(MARKET))
    if vix.empty or market.empty:
        return None
    return classify(vix, market)
