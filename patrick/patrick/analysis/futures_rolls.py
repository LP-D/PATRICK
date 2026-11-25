"""Sauts de changement d'échéance des contrats à terme continus (CO26 du 25/11) : diagnostic, sans toucher à l'entraînement.

Yahoo sert les contrats continus (`ES=F`, `CL=F`…) NON ajustés : au passage d'une échéance à la suivante, le cours saute de l'écart entre les
deux contrats (le « roll »), un mouvement que personne n'a gagné ni perdu. Un modèle qui apprend la direction du lendemain prend ces sauts
pour de vrais mouvements. Les ajuster exigerait les contrats échus, que Yahoo ne sert pas (B18 du 24/11).

Ici, on REPÈRE les jours suspects : un rendement au-delà de `k` écarts robustes (médiane des écarts absolus, sur 60 séances passées), à
moins de `window` séances d'une date d'échéance probable (troisième vendredi du mois pour les contrats trimestriels et mensuels, fin de
mois pour l'énergie). Retirer ces jours des étiquettes changerait les résultats de tous les runs de contrats à terme : c'est une décision
(suivi du 25/11), ce module en donne la mesure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ENERGY = {"CL=F", "BZ=F", "NG=F", "HO=F", "RB=F"}


def _third_fridays(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    months = pd.period_range(index.min().to_period("M"), index.max().to_period("M"), freq="M")
    out = []
    for m in months:
        first = m.to_timestamp()
        offset = (4 - first.weekday()) % 7                  # vendredi = 4
        out.append(first + pd.Timedelta(days=offset + 14))
    return pd.DatetimeIndex(out)


def expiry_dates(symbol: str, index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if symbol in ENERGY:
        return pd.DatetimeIndex(sorted({(d + pd.offsets.MonthEnd(0)).normalize() for d in index}))
    return _third_fridays(index)


def suspected_rolls(symbol: str, close: pd.Series, k: float = 5.0, window: int = 3, lookback: int = 60) -> pd.DataFrame:
    """Jours suspects : `date`, `return`, `z` (en écarts robustes), `nearest_expiry`. Vide si la série est trop courte."""
    close = close.dropna().astype(float)
    close = close[close > 0]
    if len(close) <= lookback + 5:
        return pd.DataFrame(columns=["date", "return", "z", "nearest_expiry"])
    idx = pd.DatetimeIndex(close.index)
    r = np.log(close).diff()
    mad = r.abs().rolling(lookback, min_periods=lookback // 2).median().shift(1) * 1.4826
    z = (r / mad).replace([np.inf, -np.inf], np.nan)
    expiries = expiry_dates(symbol, idx)
    pos = np.searchsorted(idx.values, expiries.values)
    near = np.zeros(len(idx), dtype=bool)
    nearest = pd.Series(pd.NaT, index=idx)
    for p, e in zip(pos, expiries, strict=True):
        lo, hi = max(0, p - window), min(len(idx), p + window + 1)
        near[lo:hi] = True
        nearest.iloc[lo:hi] = e
    flag = (z.abs() > k) & near
    rows = pd.DataFrame({"date": idx[flag.to_numpy()], "return": r[flag].to_numpy(), "z": z[flag].to_numpy(),
                         "nearest_expiry": nearest[flag.to_numpy()].to_numpy()})
    return rows.reset_index(drop=True)


def summary(symbol: str, close: pd.Series, **kw) -> dict:
    rows = suspected_rolls(symbol, close, **kw)
    n = len(close.dropna())
    return {"symbol": symbol, "n_days": n, "n_suspect": len(rows), "share": (len(rows) / n) if n else None,
            "largest": rows.reindex(rows["z"].abs().sort_values(ascending=False).index).head(5).to_dict("records") if len(rows) else []}
