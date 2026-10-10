"""Indicateurs d'une stratégie de positions (sortie du RL ou ligne de base) et tests contre une référence.

Tout part d'une série de rendements NETS par période (coûts déduits) et des positions tenues. Les ratios sont annualisés sur 252 périodes
(l'échantillon RL est quotidien). Aucun de ces nombres ne vaut preuve à lui seul : `bootstrap_sharpe_diff` donne l'incertitude sur l'écart
de Sharpe avec une référence, `probabilistic_sharpe` la probabilité que le vrai Sharpe soit positif, et le Sharpe déflaté
(`validation/dsr.py`) retire l'avantage d'avoir essayé plusieurs configurations.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from patrick.simulate import metrics as sim_metrics

PERIODS = 252


def equity_curve(net_returns: np.ndarray) -> np.ndarray:
    return np.cumprod(1.0 + np.asarray(net_returns, dtype=float))


def _sharpe(r: np.ndarray) -> float:
    s = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    return float(np.mean(r) / s * math.sqrt(PERIODS)) if s > 0 else float("nan")


def summarize(net_returns: np.ndarray, positions: np.ndarray, costs: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    """Résumé d'une trajectoire : rendement, risque, ratios, coûts, rotation, exposition."""
    r = pd.Series(np.asarray(net_returns, dtype=float), index=dates)
    pos = np.asarray(positions, dtype=float)
    eq = pd.Series(equity_curve(r.to_numpy()), index=dates)
    max_dd, dd_days = sim_metrics.max_drawdown(eq)
    changes = np.abs(np.diff(np.concatenate([[0.0], pos])))
    active = pos != 0
    return {
        "n": len(r),
        "total_return": float(eq.iloc[-1] - 1.0) if len(eq) else float("nan"),
        "cagr": sim_metrics.cagr(eq),
        "vol": sim_metrics.annualized_vol(r),
        "sharpe": sim_metrics.sharpe_ratio(r),
        "sortino": sim_metrics.sortino_ratio(r),
        "max_drawdown": max_dd,
        "max_drawdown_days": int(dd_days),
        "turnover": float(changes.mean() * PERIODS) if len(changes) else float("nan"),     # fraction du capital échangée par an
        "cost_drag": float(np.sum(costs)) if len(costs) else 0.0,                           # somme des coûts (fraction du capital)
        "exposure": float(np.abs(pos).mean()) if len(pos) else float("nan"),
        "net_long_share": float((pos > 0).mean()) if len(pos) else float("nan"),
        "short_share": float((pos < 0).mean()) if len(pos) else float("nan"),
        "hit_rate": float((r[active] > 0).mean()) if active.any() else float("nan"),
        "n_trades": int((changes > 1e-9).sum()),
    }


def bootstrap_sharpe_diff(a: np.ndarray, b: np.ndarray, n_boot: int = 1000, block: int | None = None, seed: int = 0) -> dict:
    """Écart de Sharpe annualisé entre a et b, avec son incertitude par rééchantillonnage en blocs circulaires (les deux séries sont
    tirées aux MÊMES dates : l'écart apparié est ce qui compte). `p_one_sided` = part des tirages où a ne bat pas b."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = min(len(a), len(b))
    if n < 40:
        return {"diff": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "p_one_sided": float("nan"), "n": int(n), "block": 0}
    a, b = a[-n:], b[-n:]
    block = int(block or max(5, round(n ** (1 / 3) * 2)))
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    idx = idx.reshape(n_boot, -1)[:, :n]
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        diffs[i] = _sharpe(a[idx[i]]) - _sharpe(b[idx[i]])
    diffs = diffs[np.isfinite(diffs)]
    observed = _sharpe(a) - _sharpe(b)
    if len(diffs) < 20:
        return {"diff": float(observed), "ci_low": float("nan"), "ci_high": float("nan"), "p_one_sided": float("nan"), "n": int(n), "block": block}
    return {"diff": float(observed), "ci_low": float(np.percentile(diffs, 5)), "ci_high": float(np.percentile(diffs, 95)),
            "p_one_sided": float((diffs <= 0).mean()), "n": int(n), "block": block}


def probabilistic_sharpe(returns: np.ndarray, benchmark_sr: float = 0.0) -> float:
    """PSR (Bailey & López de Prado) : probabilité que le Sharpe PÉRIODIQUE vrai dépasse `benchmark_sr`, compte tenu de l'asymétrie et
    du kurtosis des rendements."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 20 or np.std(r, ddof=1) == 0:
        return float("nan")
    sr = float(np.mean(r) / np.std(r, ddof=1))
    skew, kurt = float(stats.skew(r)), float(stats.kurtosis(r, fisher=False))
    var = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1)
    return float(stats.norm.cdf((sr - benchmark_sr) / math.sqrt(max(var, 1e-18))))
