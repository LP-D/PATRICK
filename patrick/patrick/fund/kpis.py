"""KPI d'une stratégie à partir du résultat du moteur (spec §10)."""
from __future__ import annotations

import math

import pandas as pd

from patrick.fund.engine import SimResult
from patrick.simulate import metrics as simmetrics


def _num(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def compute(strategy: dict, result: SimResult) -> dict:
    capital = float(strategy["initial_capital"])
    daily = result.daily
    positions = result.positions
    open_positions = [p for p in positions if p["status"] == "open"]
    if daily.empty:
        nav = capital
        last: dict = {}
    else:
        nav = float(daily["nav"].iloc[-1])
        last = daily.iloc[-1].to_dict()
    pnl = nav - capital
    returns = daily["nav"].pct_change().dropna() if len(daily) > 1 else pd.Series(dtype=float)
    max_dd = simmetrics.max_drawdown(daily["nav"])[0] if len(daily) > 1 else float("nan")
    gross = float(last.get("gross_exposure", 0.0))
    net = float(last.get("net_exposure", 0.0))
    return {
        "nav": nav, "capital": capital, "pnl": pnl, "pnl_pct": pnl / capital,
        "realized": sum(p["realized"] for p in positions),
        "latent": sum(p["latent"] for p in open_positions),
        "fees": float(last.get("fees_cum", 0.0)), "dividends": float(last.get("dividends_cum", 0.0)),
        "financing": float(last.get("financing_cum", 0.0)),
        "twr": pnl / capital,    # aucun flux externe au chantier 1 : le TWR égale le rendement sur capital
        "volatility": _num(simmetrics.annualized_vol(returns)),
        "sharpe": _num(simmetrics.sharpe_ratio(returns)),
        "max_drawdown": _num(max_dd),
        "gross_exposure_pct": gross / nav if nav > 0 else None,
        "net_exposure_pct": net / nav if nav > 0 else None,
        "leverage": gross / nav if nav > 0 else None,
        "margin_used": float(last.get("margin_used", 0.0)),
        "buying_power": float(last.get("buying_power", capital)),
        "cash": float(last.get("cash", capital)),
        "n_open_positions": len(open_positions),
    }


def series_points(daily: pd.DataFrame, columns=("nav", "cash")) -> list[dict]:
    if daily.empty:
        return []
    out = []
    for day, row in daily.iterrows():
        out.append({"t": day.date().isoformat(), **{c: round(float(row[c]), 4) for c in columns}})
    return out
