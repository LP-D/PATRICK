"""KPI d'une stratégie à partir du résultat du moteur (spec §10).

Performance avant frais (ADR 0030) : la valeur qu'aurait la stratégie sans ses coûts de mise en œuvre, frais de transaction (commission, spread,
change) et financement des CFD. Elle sépare deux échecs qui se ressemblent en net : un signal qui gagne mais dont les frais mangent le gain, et un
signal qui ne gagne rien même gratuit. Les dividendes restent dedans : ils font partie du rendement de l'actif. Approximation assumée : les tailles
des positions sont celles qui ont été réellement prises (frais déduits du montant investi), pas celles d'un compte sans frais.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from patrick.fund.engine import SimResult
from patrick.simulate import metrics as simmetrics


def _num(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


EDGE_VERDICTS = ("none", "no_edge", "eaten", "kept")


def gross_nav(daily: pd.DataFrame) -> pd.Series:
    """Valeur avant frais, jour par jour : la valeur nette plus les frais et le financement cumulés (le financement payé est positif)."""
    if daily.empty:
        return pd.Series(dtype=float)
    costs = [daily[c] for c in ("fees_cum", "financing_cum") if c in daily]   # une série sans frais (tests, anciennes sorties) : la valeur nette
    return daily["nav"] + sum(costs) if costs else daily["nav"].copy()


def edge_verdict(gross_pnl: float, net_pnl: float, has_orders: bool) -> str:
    """`none` (aucun ordre : rien à dire), `no_edge` (même sans frais la stratégie perd ou fait zéro), `eaten` (gain avant frais, perte ou rien
    après : les frais mangent l'avantage), `kept` (gain après frais)."""
    if not has_orders:
        return "none"
    if gross_pnl <= 0:
        return "no_edge"
    return "kept" if net_pnl > 0 else "eaten"


def _weekday_returns(nav: pd.Series) -> pd.Series:
    nav = nav[nav.index.dayofweek < 5] if len(nav) else nav
    return nav.pct_change().dropna() if len(nav) > 1 else pd.Series(dtype=float)


TAIL_LEVEL = 0.99
TAIL_THRESHOLD_Q = 0.90          # pertes au-delà de leur 90e centile : la queue ajustée par la loi de Pareto généralisée
TAIL_MIN_RETURNS = 250


def tail_risk(returns: pd.Series, level: float = TAIL_LEVEL) -> dict | None:
    """A19 (24/11) : VaR et perte moyenne au-delà (ES) d'une journée, à `level`, par la théorie des valeurs extrêmes (pics au-delà d'un seuil,
    loi de Pareto généralisée sur les pertes au-delà de leur 90e centile, McNeil et Frey 2000), à côté de la VaR historique. La VaR historique
    à 99 % sur 250 jours repose sur 2 ou 3 observations ; la GPD extrapole la queue. Pertes en fraction de la valeur (positives). None sous
    `TAIL_MIN_RETURNS` rendements ou si la queue est vide."""
    from scipy import stats

    losses = -pd.Series(returns, dtype=float).dropna()
    n = len(losses)
    if n < TAIL_MIN_RETURNS:
        return None
    u = float(losses.quantile(TAIL_THRESHOLD_Q))
    excess = (losses[losses > u] - u).to_numpy()
    if len(excess) < 15 or not np.isfinite(excess).all() or excess.max() <= 0:
        return None
    xi, _loc, beta = stats.genpareto.fit(excess, floc=0.0)
    p_u = len(excess) / n
    var = u + beta / xi * (((1 - level) / p_u) ** (-xi) - 1) if abs(xi) > 1e-6 else u - beta * np.log((1 - level) / p_u)
    es = (var + beta - xi * u) / (1 - xi) if xi < 1 else float("nan")
    return {"level": level, "var_hist": float(losses.quantile(level)), "var_evt": float(var), "es_evt": float(es) if np.isfinite(es) else None,
            "xi": float(xi), "n": n, "n_tail": len(excess)}


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
    # Volatilité et Sharpe sont annualisés sur 252 jours : on mesure sur les clôtures de jours ouvrés, même quand la
    # série contient des samedis et dimanches (stratégie détenant un cryptoactif).
    weekday_nav = daily["nav"][daily.index.dayofweek < 5] if len(daily) else daily["nav"]
    returns = weekday_nav.pct_change().dropna() if len(weekday_nav) > 1 else pd.Series(dtype=float)
    max_dd = simmetrics.max_drawdown(daily["nav"])[0] if len(daily) > 1 else float("nan")
    gross = float(last.get("gross_exposure", 0.0))
    net = float(last.get("net_exposure", 0.0))
    fees, financing = float(last.get("fees_cum", 0.0)), float(last.get("financing_cum", 0.0))
    costs = fees + financing
    gross_pnl = pnl + costs
    gross_returns = _weekday_returns(gross_nav(daily))
    before_fees = {
        "gross_pnl": gross_pnl, "gross_pnl_pct": gross_pnl / capital, "costs": costs,
        "gross_sharpe": _num(simmetrics.sharpe_ratio(gross_returns)) if len(gross_returns) else None,
        # part du gain avant frais que les frais emportent (None sans gain avant frais : il n'y a rien à manger)
        "costs_share": costs / gross_pnl if gross_pnl > 0 else None,
        "edge_verdict": edge_verdict(gross_pnl, pnl, bool(positions)),
        "n_sessions": int((daily.index.dayofweek < 5).sum()) if len(daily) else 0,
    }
    return {**before_fees,
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
        "tail": tail_risk(returns),
    }


def deflation_trials(n_strategies: int, n_classes_compared: int = 0) -> int:
    """Essais à déflater pour le Sharpe d'une stratégie : les stratégies du fonds (archivées comprises) et, au moins, les classes d'actifs entre lesquelles on a pu
    choisir. La Synthèse et les cartes de lots classent les classes par AUC regroupée (`tracking/pooled_signal.py`) : choisir la meilleure est un essai par classe
    comparée, même si une seule a donné une stratégie (ADR 0014, reste du point 1.5 de l'ADR 0011). Un plancher, pas un produit : les modèles retenus dans chaque
    stratégie sont déjà comptés dans le registre d'essais (`fund_selection:<stratégie>`)."""
    return max(int(n_strategies), int(n_classes_compared), 1)


def deflated(daily: pd.DataFrame, n_trials: int) -> dict | None:
    """Sharpe déflaté d'une stratégie (ADR 0011, point 1.5) : le meilleur de `n_trials` stratégies comparées sur leur P&L fictif a un Sharpe gonflé par le seul fait
    d'avoir été choisi. `n_trials` = nombre de stratégies du fonds (archivées comprises : une stratégie abandonnée a bien été essayée). `None` sous 20 rendements
    quotidiens (la statistique n'a pas de sens). Mêmes rendements de jours ouvrés que le Sharpe affiché."""
    from patrick.validation.dsr import deflated_sharpe_ratio

    if daily.empty:
        return None
    nav = daily["nav"][daily.index.dayofweek < 5]
    returns = nav.pct_change().dropna().to_numpy(dtype=float)
    out = deflated_sharpe_ratio(returns, max(int(n_trials), 1))
    if out["n_obs"] < 20:
        return None
    return {"dsr": _num(out["dsr"]), "benchmark_sr": _num(out["benchmark_sr"]), "sr": _num(out["sr"]), "n_trials": out["n_trials"], "n_obs": out["n_obs"]}


def series_points(daily: pd.DataFrame, columns=("nav", "cash", "gross")) -> list[dict]:
    """Points du graphique d'une stratégie : valeur nette, liquidités et valeur avant frais (`gross`)."""
    if daily.empty:
        return []
    frame = daily.assign(gross=gross_nav(daily)) if "gross" in columns else daily
    out = []
    for day, row in frame.iterrows():
        out.append({"t": day.date().isoformat(), **{c: round(float(row[c]), 4) for c in columns if c in frame}})
    return out
