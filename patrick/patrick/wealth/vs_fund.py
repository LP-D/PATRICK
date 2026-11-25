"""Compte réel contre fonds simulé (FO19 du 25/11) : ce que le fonds aurait fait sur la même période que ce que l'on a vraiment fait.

Le rendement du compte est pondéré dans le temps (TWR : les versements et retraits ne comptent pas comme de la performance), celui du fonds
est sa valeur nette ; les deux partent de 100 à la première date qu'ils ont en commun. L'écart se lit avec prudence : le fonds est simulé
(frais estimés, aucune fiscalité), le compte est réel.
"""
from __future__ import annotations

import pandas as pd


def compare(twr_index: pd.Series | None, fund_points: list[dict]) -> dict | None:
    """`{start, end, account, fund, gap}` (rendements sur la période commune) ; None sans période commune d'au moins 5 séances."""
    if twr_index is None or not len(twr_index) or not fund_points:
        return None
    fund = pd.Series({pd.Timestamp(p["t"]): float(p["nav"]) for p in fund_points if p.get("nav")}).sort_index()
    acc = pd.Series(twr_index).dropna().sort_index()
    acc.index = pd.to_datetime(acc.index)
    start = max(acc.index.min(), fund.index.min())
    acc, fund = acc[acc.index >= start], fund[fund.index >= start]
    common = acc.index.intersection(fund.index)
    if len(common) < 5:
        return None
    a, f = acc.loc[common], fund.loc[common]
    ra, rf = float(a.iloc[-1] / a.iloc[0] - 1), float(f.iloc[-1] / f.iloc[0] - 1)
    return {"start": common[0].date().isoformat(), "end": common[-1].date().isoformat(), "account": ra, "fund": rf, "gap": ra - rf,
            "n": len(common)}
