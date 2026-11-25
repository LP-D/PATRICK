"""Indicateurs de performance d'une courbe de capital quotidienne, de ses opérations et face à un indice de référence.

Conventions : rendements quotidiens nets de frais ; Sharpe et Sortino sur l'EXCÉDENT de rendement par rapport au taux des liquidités ;
annualisation sur 252 séances ; le rendement annualisé (CAGR) se calcule sur la durée calendaire réelle. Les durées de drawdown sont en
séances et en jours calendaires.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from patrick.core.perf import TRADING_DAYS as TD


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return float("nan")
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / TD)
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def drawdown_periods(equity: pd.Series, top: int = 5) -> list[dict]:
    """Les `top` pires baisses : début (sommet), creux, retour au sommet (ou None), profondeur, durées."""
    dd = drawdown(equity)
    out = []
    in_dd, start = False, None
    prev_ts = equity.index[0] if len(equity) else None
    for ts, v in dd.items():
        if v < 0 and not in_dd:
            in_dd, start = True, prev_ts
        elif v >= 0 and in_dd:
            seg = dd.loc[start:ts]
            out.append((start, seg.idxmin(), ts, float(seg.min())))
            in_dd = False
        prev_ts = ts
    if in_dd:
        seg = dd.loc[start:]
        out.append((start, seg.idxmin(), None, float(seg.min())))
    out.sort(key=lambda x: x[3])
    rows = []
    for s, trough, end, depth in out[:top]:
        rows.append({"start": s.date().isoformat(), "trough": trough.date().isoformat(), "end": end.date().isoformat() if end is not None else None,
                     "depth": depth, "days_down": int((trough - s).days), "days_total": int(((end or equity.index[-1]) - s).days),
                     "recovered": end is not None})
    return rows


def core(ret: pd.Series, equity: pd.Series, cash_rate: float = 0.0) -> dict:
    ret = ret.fillna(0.0)
    ex = ret - cash_rate / TD
    sd = ret.std()
    downside = np.sqrt(np.mean(np.minimum(ex, 0) ** 2))
    dd = drawdown(equity)
    mdd = float(dd.min()) if len(dd) else float("nan")
    c = cagr(equity)
    q05 = ret.quantile(0.05)
    under = (dd < 0).astype(int)
    longest = int(under.groupby((under == 0).cumsum()).sum().max()) if len(under) else 0
    return {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) > 1 else 0.0,
        "cagr": c, "vol": float(sd * np.sqrt(TD)),
        "sharpe": float(ex.mean() / sd * np.sqrt(TD)) if sd > 0 else float("nan"),
        "sortino": float(ex.mean() / downside * np.sqrt(TD)) if downside > 0 else float("nan"),
        "max_dd": mdd, "calmar": float(c / abs(mdd)) if mdd < 0 else float("nan"),
        "longest_dd_days": longest, "current_dd": float(dd.iloc[-1]) if len(dd) else 0.0,
        "best_day": float(ret.max()), "worst_day": float(ret.min()), "hit_days": float((ret > 0).sum() / max((ret != 0).sum(), 1)),
        "skew": float(ret.skew()), "kurtosis": float(ret.kurt()), "var95": float(q05), "cvar95": float(ret[ret <= q05].mean()) if (ret <= q05).any() else float("nan"),
        "years": float((equity.index[-1] - equity.index[0]).days / 365.25) if len(equity) > 1 else 0.0,
    }


def periodic(equity: pd.Series) -> dict:
    """Rendements mensuels (année x mois) et annuels."""
    m = equity.resample("ME").last()
    first = equity.iloc[0]
    mret = m.pct_change()
    mret.iloc[0] = m.iloc[0] / first - 1
    table: dict[str, list] = {}
    for ts, v in mret.items():
        table.setdefault(str(ts.year), [None] * 12)[ts.month - 1] = _f(v)
    y = equity.resample("YE").last()
    yret = y.pct_change()
    yret.iloc[0] = y.iloc[0] / first - 1
    return {"monthly": table, "annual": {str(ts.year): _f(v) for ts, v in yret.items()},
            "best_month": _f(mret.max()), "worst_month": _f(mret.min()), "positive_months": _f((mret > 0).mean()),
            "positive_years": _f((yret > 0).mean())}


def trade_stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("return") is not None]
    if not closed:
        return {"count": 0}
    r = np.array([t["return"] for t in closed])
    pnl = np.array([t.get("pnl", 0.0) or 0.0 for t in closed])
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    streak = best = 0
    for p in pnl:
        streak = streak + 1 if p < 0 else 0
        best = max(best, streak)
    return {"count": len(closed), "win_rate": float((pnl > 0).mean()), "avg_return": float(r.mean()), "median_return": float(np.median(r)),
            "avg_win": float(wins.mean()) if len(wins) else None, "avg_loss": float(losses.mean()) if len(losses) else None,
            "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else None,
            "expectancy": float(pnl.mean()), "avg_days": float(np.mean([t.get("days", 0) for t in closed])),
            "best": float(r.max()), "worst": float(r.min()), "max_losing_streak": int(best),
            "long_share": float(np.mean([t["side"] > 0 for t in closed]))}


def versus(ret: pd.Series, bench: pd.Series, cash_rate: float = 0.0) -> dict:
    """Bêta, alpha annualisé (Jensen), corrélation, erreur de suivi, ratio d'information, captures de hausse et de baisse."""
    both = pd.concat([ret.rename("s"), bench.rename("b")], axis=1).dropna()
    if len(both) < 30 or both["b"].std() == 0:
        return {}
    rf = cash_rate / TD
    s, b = both["s"] - rf, both["b"] - rf
    beta = float(np.cov(s, b, ddof=1)[0, 1] / b.var())
    alpha = float((s.mean() - beta * b.mean()) * TD)
    active = both["s"] - both["b"]
    te = float(active.std() * np.sqrt(TD))
    up, down = both[both["b"] > 0], both[both["b"] < 0]
    return {"beta": beta, "alpha": alpha, "correlation": float(both["s"].corr(both["b"])), "tracking_error": te,
            "information_ratio": float(active.mean() * TD / te) if te > 0 else None,
            "up_capture": float(up["s"].mean() / up["b"].mean()) if len(up) and up["b"].mean() else None,
            "down_capture": float(down["s"].mean() / down["b"].mean()) if len(down) and down["b"].mean() else None}


def rolling(ret: pd.Series, window: int = TD, step: int = 5, cash_rate: float = 0.0) -> dict:
    if len(ret) <= window:
        return {"dates": [], "ret": [], "sharpe": [], "vol": []}
    growth = (1 + ret).rolling(window).apply(np.prod, raw=True) - 1
    ex = ret - cash_rate / TD
    sharpe = ex.rolling(window).mean() / ret.rolling(window).std() * np.sqrt(TD)
    vol = ret.rolling(window).std() * np.sqrt(TD)
    sl = slice(window - 1, None, step)
    return {"dates": [d.date().isoformat() for d in ret.index[sl]], "ret": [_f(v) for v in growth.iloc[sl]],
            "sharpe": [_f(v) for v in sharpe.iloc[sl]], "vol": [_f(v) for v in vol.iloc[sl]]}


def sample(series: pd.Series, max_points: int = 1500) -> tuple[list[str], list]:
    """Sous-échantillonne une série quotidienne pour l'affichage (au plus `max_points`, la dernière séance toujours gardée)."""
    n = len(series)
    step = max(1, math.ceil(n / max_points))
    idx = list(range(0, n, step))
    if idx and idx[-1] != n - 1:
        idx.append(n - 1)
    sub = series.iloc[idx]
    return [d.date().isoformat() for d in sub.index], [_f(v) for v in sub]
