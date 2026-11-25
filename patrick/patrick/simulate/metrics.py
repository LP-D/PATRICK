"""Performance metrics (Phase 4.4), pure functions on daily-return series --
no dependency on SQLite or on `prediction` (see `simulate/engine.py` for the
assembly from the database).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.core.perf import TRADING_DAYS, downside_deviation, periods_per_year

TRADING_DAYS_PER_YEAR = TRADING_DAYS      # nom historique, gardé pour les appelants


def _periods(returns, periods: int | None) -> int:
    """`periods` donné, sinon déduit de l'index (CO5 : 365 pour une série qui contient les week-ends, 252 sinon)."""
    return int(periods) if periods else periods_per_year(getattr(returns, "index", None))


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return float("nan")
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    if n_years <= 0:
        return float("nan")
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1)


def annualized_vol(returns: pd.Series, periods: int | None = None) -> float:
    if len(returns) < 2:
        return float("nan")
    return float(returns.std(ddof=1) * np.sqrt(_periods(returns, periods)))


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0, periods: int | None = None) -> float:
    n = _periods(returns, periods)
    excess = returns - risk_free / n
    if len(excess) < 2 or excess.std(ddof=1) == 0:
        return float("nan")
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(n))


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0, periods: int | None = None) -> float:
    """Rendement excédentaire moyen / écart à la baisse sur TOUTES les séances (CO4 : l'ancien calcul prenait l'écart-type des
    seules séances négatives autour de leur propre moyenne, ce qui surévaluait le ratio ; voir `core/perf.downside_deviation`)."""
    n = _periods(returns, periods)
    excess = returns - risk_free / n
    if len(excess) < 2 or int((excess < 0).sum()) < 1:
        return float("nan")
    dd = downside_deviation(excess)
    if not dd > 1e-12:
        return float("nan")
    return float(excess.mean() / dd * np.sqrt(n))


def max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """(max depth as a negative fraction, duration in days of the longest
    trough -- from the previous peak until the return above that peak, not
    just to the lowest point)."""
    if len(equity) < 2:
        return float("nan"), 0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_dd = float(drawdown.min())

    underwater = drawdown < -1e-12
    max_duration = 0
    current_start = None
    for date, is_under in underwater.items():
        if is_under and current_start is None:
            current_start = date
        elif not is_under and current_start is not None:
            max_duration = max(max_duration, (date - current_start).days)
            current_start = None
    if current_start is not None:
        max_duration = max(max_duration, (equity.index[-1] - current_start).days)
    return max_dd, max_duration


def hit_rate(trade_returns: pd.Series) -> float:
    if len(trade_returns) == 0:
        return float("nan")
    return float((trade_returns > 0).mean())


def profit_factor(trade_returns: pd.Series) -> float:
    if len(trade_returns) == 0:
        return float("nan")
    gains = float(trade_returns[trade_returns > 0].sum())
    losses = float(-trade_returns[trade_returns < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def performance_summary(equity: pd.Series, returns: pd.Series, exposure: pd.Series) -> dict:
    """Groups all Phase 4.4 metrics for a given leg (strategy or
    buy-and-hold) -- `exposure` is only used for the average exposure
    (constant 1.0 for buy-and-hold)."""
    max_dd, max_dd_days = max_drawdown(equity)
    return {
        "cagr": cagr(equity),
        "annualized_vol": annualized_vol(returns),
        "sharpe": sharpe_ratio(returns),
        "sortino": sortino_ratio(returns),
        "max_drawdown": max_dd,
        "max_drawdown_days": max_dd_days,
        "avg_exposure": float(exposure.abs().mean()) if len(exposure) else float("nan"),
    }
