"""Carry trade de change : signal par écart de taux courts et rejeu mensuel net de frais.

Le carry classique achète les devises qui rendent plus que le dollar et vend celles qui rendent moins ; il gagne l'écart de taux tant que le change ne se déprécie pas autant. Le
cours seul (Yahoo) ne contient pas ce gain : il faut les taux. Source : taux interbancaires à 3 mois de l'OCDE sur FRED (`IR3TIB01<pays>M156N`), mensuels, publiés avec retard.

Honnêteté sur le temps : la valeur d'un mois n'est utilisée qu'après `PUBLICATION_LAG_MONTHS` mois (la première publication ALFRED ne remonte qu'à 2013 pour ces séries ; les taux
interbancaires sont peu révisés, un retard prudent remplace la vraie date), jamais la valeur du mois en cours. Aucun contrat à terme n'est nécessaire pour le carry de change (il en
faudrait pour un carry de matières premières : courbe des échéances, absente des sources, voir `docs/modelisation/chantiers-lointains.md` §3).

Deux stratégies, une règle fixée avant la mesure, jamais réglée :
- `time_series` : pour chaque devise, long si son taux dépasse celui du dollar, short sinon ; poids égaux ;
- `cross_section` : long les `N_TAIL` devises au plus fort écart, short les `N_TAIL` au plus faible (neutre au dollar).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PUBLICATION_LAG_MONTHS = 2
N_TAIL = 3
COST_BPS = 2.0                          # par unité de rotation, par jambe (majeures de change)
TRADING_MONTHS = 12
# devise -> (identifiant FRED du taux à 3 mois, paire Yahoo, True si la paire est cotée « devise en dollars » : EURUSD=X ; False si « dollars en devise » : USDJPY=X)
CURRENCIES = {
    "EUR": ("IR3TIB01EZM156N", "EURUSD=X", True),
    "GBP": ("IR3TIB01GBM156N", "GBPUSD=X", True),
    "AUD": ("IR3TIB01AUM156N", "AUDUSD=X", True),
    "NZD": ("IR3TIB01NZM156N", "NZDUSD=X", True),
    "JPY": ("IR3TIB01JPM156N", "USDJPY=X", False),
    "CAD": ("IR3TIB01CAM156N", "USDCAD=X", False),
    "CHF": ("IR3TIB01CHM156N", "USDCHF=X", False),
}
USD_RATE = "IR3TIB01USM156N"


def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Dernier jour de cotation de chaque mois."""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).max().to_numpy())


def known_rates(rates: pd.DataFrame, at: pd.DatetimeIndex, lag_months: int = PUBLICATION_LAG_MONTHS) -> pd.DataFrame:
    """Dernier taux connu à chaque date `at` : la valeur du mois M n'est disponible qu'à la fin du mois M + `lag_months`. `rates` : index = premier jour du mois d'observation."""
    available = rates.copy()
    available.index = (available.index + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(lag_months))
    return available.sort_index().reindex(available.index.union(at)).ffill().reindex(at)


def carry_signals(differential: pd.DataFrame, strategy: str, n_tail: int = N_TAIL) -> pd.DataFrame:
    """Position (-1, 0, +1, avant mise à l'échelle) de chaque devise contre le dollar, à chaque date, d'après l'écart de taux connu (devise moins dollar)."""
    if strategy == "time_series":
        return np.sign(differential).where(differential.notna(), 0.0)
    if strategy == "cross_section":
        ranks = differential.rank(axis=1, ascending=True, method="first")
        n = differential.notna().sum(axis=1)
        pos = pd.DataFrame(0.0, index=differential.index, columns=differential.columns)
        pos[ranks.le(n_tail, axis=0) & differential.notna()] = -1.0
        pos[ranks.gt((n - n_tail), axis=0) & differential.notna()] = 1.0
        return pos
    raise ValueError(f"stratégie inconnue : {strategy!r}")


def usd_per_currency(spot: pd.DataFrame) -> pd.DataFrame:
    """Cours de chaque devise EN dollars (une hausse = la devise s'apprécie), quelle que soit la cotation Yahoo de la paire."""
    out = {}
    for ccy, (_sid, pair, direct) in CURRENCIES.items():
        if pair in spot:
            out[ccy] = spot[pair] if direct else 1.0 / spot[pair]
    return pd.DataFrame(out)


def backtest(spot: pd.DataFrame, rates: pd.DataFrame, strategy: str, *, cost_bps: float = COST_BPS, lag_months: int = PUBLICATION_LAG_MONTHS,
             start: str | None = None, end: str | None = None) -> dict:
    """Rejeu mensuel. `spot` : cours Yahoo journaliers des paires (colonnes = symboles de `CURRENCIES`) ; `rates` : taux à 3 mois, une colonne par devise plus `USD`.
    Au dernier jour de cotation de chaque mois : signal d'après les taux connus ce jour-là, position tenue jusqu'au mois suivant, rendement = variation de la devise en dollars
    (change) + écart de taux connu / 12 (portage) − frais sur la rotation. Poids : 1 / nombre de devises à signal (séries chronologiques) ou 1 / N_TAIL par jambe."""
    usd = usd_per_currency(spot)
    ends = month_ends(usd.dropna(how="all").index)
    if start:
        ends = ends[ends >= pd.Timestamp(start)]
    if end:
        ends = ends[ends <= pd.Timestamp(end)]
    px = usd.reindex(ends).ffill()
    known = known_rates(rates, ends, lag_months)
    diff = known[[c for c in usd.columns]].sub(known["USD"], axis=0)
    pos = carry_signals(diff, strategy)
    weight = pos.abs().sum(axis=1).replace(0, np.nan)
    pos = pos.div(weight, axis=0).fillna(0.0) if strategy == "time_series" else pos / N_TAIL
    fx_ret = px.pct_change().shift(-1)                                   # rendement de la devise du mois qui suit la décision
    carry_ret = diff / 100.0 / TRADING_MONTHS
    gross_fx = (pos * fx_ret).sum(axis=1, min_count=1)
    gross_carry = (pos * carry_ret).sum(axis=1, min_count=1)
    turnover = pos.diff().abs().sum(axis=1).fillna(pos.abs().sum(axis=1))
    cost = turnover * cost_bps / 1e4
    valid = fx_ret.notna().any(axis=1) & diff.notna().any(axis=1)
    net = (gross_fx + gross_carry - cost)[valid].dropna()
    spot_only = (gross_fx - cost)[valid].dropna()
    return {"net": net, "spot_only": spot_only, "carry_part": gross_carry[valid].dropna(), "positions": pos[valid], "turnover": turnover[valid]}


def stats(returns: pd.Series) -> dict:
    """Rendement annualisé, volatilité, Sharpe, pire perte cumulée, asymétrie, t de Student de la moyenne, sur des rendements mensuels."""
    r = returns.dropna()
    if len(r) < 12:
        return {"n": len(r)}
    equity = (1 + r).cumprod()
    sd = float(r.std(ddof=1))
    return {"n": len(r), "ann_return": float((1 + r).prod() ** (TRADING_MONTHS / len(r)) - 1), "ann_vol": sd * np.sqrt(TRADING_MONTHS),
            "sharpe": float(r.mean() / sd * np.sqrt(TRADING_MONTHS)) if sd > 0 else float("nan"), "max_drawdown": float((equity / equity.cummax() - 1).min()),
            "skew": float(r.skew()), "t_mean": float(r.mean() / (sd / np.sqrt(len(r)))) if sd > 0 else float("nan")}
