"""Statistiques descriptives d'un fonds sur une fenêtre (port de la section 2 du notebook PEE).

Les rendements quotidiens ne sont retenus que sur des écarts de VL ≤ 5 jours calendaires : les VL hebdomadaires des premières années
d'un fonds fausseraient la volatilité si on les traitait comme des séances. Le Sharpe est l'excès de rendement sur le support monétaire
divisé par la volatilité ; le drawdown maximal est la pire baisse sommet -> creux.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FREQ = 12            # mois par an
TRADING_DAYS = 252
MAX_GAP_DAYS = 5     # un rendement quotidien est « quotidien » si les deux VL sont distantes de 5 jours calendaires au plus


def daily_returns(nav: pd.Series) -> pd.Series:
    nav = nav.dropna()
    gap = nav.index.to_series().diff().dt.days
    return nav.pct_change()[gap <= MAX_GAP_DAYS].dropna()


def monthly_navs(navs: pd.DataFrame, last_common: pd.Timestamp) -> pd.DataFrame:
    """Dernière VL de chaque mois (jusqu'à 5 jours de report), mois complets seulement (jusqu'à la dernière VL commune)."""
    m = navs.ffill(limit=5).resample("ME").last()
    return m[m.index <= last_common]


def monthly_returns(nav: pd.Series, last_common: pd.Timestamp) -> pd.Series:
    m = nav.dropna().resample("ME").last()
    return m[m.index <= last_common].pct_change().dropna()


def drawdown_info(nav: pd.Series) -> tuple[float, pd.Timestamp, pd.Timestamp, pd.Timestamp | None]:
    """`(pire baisse, date du sommet, date du creux, date de récupération ou None)`."""
    nav = nav.dropna()
    dd = nav / nav.cummax() - 1
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    rec = nav.loc[trough:][nav.loc[trough:] >= nav.loc[peak]]
    return float(dd.min()), peak, trough, (rec.index[0] if len(rec) else None)


def window_stats(nav: pd.Series, start: pd.Timestamp, end: pd.Timestamp, cash_nav: pd.Series) -> dict | None:
    """Statistiques d'un fonds entre `start` et `end` ; `None` si la fenêtre contient moins de deux VL."""
    nav = nav.dropna().loc[start:end]
    if len(nav) < 2:
        return None
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    r = daily_returns(nav)
    cash_r = daily_returns(cash_nav.loc[start:end]).reindex(r.index).fillna(0)
    mdd, peak, trough, recovery = drawdown_info(nav)
    roll = nav / nav.shift(TRADING_DAYS) - 1
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    vol = float(r.std() * np.sqrt(TRADING_DAYS)) if len(r) > 1 else float("nan")
    return {
        "start": nav.index[0].date().isoformat(), "years": round(years, 2), "cagr": float(cagr), "vol": vol,
        "sharpe": float((r - cash_r).mean() * TRADING_DAYS / vol) if vol and vol == vol else float("nan"),
        "max_dd": mdd, "peak": peak.date().isoformat(), "trough": trough.date().isoformat(),
        "recovery": recovery.date().isoformat() if recovery is not None else None,
        "worst_day": float(r.min()) if len(r) else float("nan"), "best_day": float(r.max()) if len(r) else float("nan"),
        "worst_12m": float(roll.min()) if years > 1.05 else float("nan"), "best_12m": float(roll.max()) if years > 1.05 else float("nan"),
        "calmar": float(cagr / abs(mdd)) if mdd else float("nan"),
    }
