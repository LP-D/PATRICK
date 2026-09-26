"""Matrice de covariance point-in-time, partagee (CHANTIER C,
feature/covariance-matrix-utility) : une seule fonction utilitaire generale,
reutilisable par HRP (CHANTIER D) et tout futur besoin de portefeuille --
applicable a n'importe quel sous-ensemble de l'univers (commodites, macro,
VIX, EUR/USD, S&P500, BTC...), pas seulement le sous-ensemble utilise par
HRP.

Placee dans `tracking/` pour suivre la convention deja en place
(`tracking/portfolio.py` porte deja la detection de contradiction cross-
actifs sur `/portfolio`) plutot que de creer un nouveau package top-level
pour une seule fonction.

Design volontairement PURE (voir docstring de test) : prend en entree un
dict {symbole: pd.Series de prix}, jamais d'acces direct a `DataStore` --
la resolution des tickers/colonnes reste la responsabilite de l'appelant.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features._utils import safe_pct_change

COVARIANCE_ESTIMATORS = ("sample", "ledoit_wolf")


def point_in_time_covariance(prices: dict[str, pd.Series], as_of,
                              lookback: int = 252, min_obs: int = 60,
                              estimator: str = "sample") -> pd.DataFrame:
    """Matrice de covariance des rendements, au temps `as_of`, strictement
    point-in-time : chaque serie de `prices` est d'abord tronquee a
    `index <= as_of` -- aucune observation posterieure n'entre jamais dans
    le calcul, quelle que soit la longueur de l'historique fourni au-dela.
    Les `lookback` dernieres observations de rendement (pct_change) de
    chaque actif sont ensuite alignees sur les dates COMMUNES a tous les
    actifs demandes (inner join -- actifs a calendriers differents, ex. BTC
    7j/7 vs actions 5j/7) avant le calcul de covariance. Leve `ValueError`
    si moins de `min_obs` dates communes subsistent apres alignement --
    jamais un resultat silencieusement degrade sur une matrice quasi-vide.

    `estimator` (roadmap bloc 4) : `"sample"` (covariance empirique, sans
    biais mais bruitee quand le nombre d'actifs N approche le nombre
    d'observations T -- singuliere des que N > T) ou `"ledoit_wolf"`
    (Ledoit & Wolf 2004 : combinaison convexe de la covariance empirique et
    d'une cible diagonale a variance moyenne, intensite de retrecissement
    estimee pour minimiser l'erreur quadratique attendue ; toujours definie
    positive). L'intensite est exposee dans `result.attrs["shrinkage"]`."""
    if estimator not in COVARIANCE_ESTIMATORS:
        raise ValueError(f"estimateur de covariance inconnu : {estimator!r} ({COVARIANCE_ESTIMATORS})")
    as_of = pd.Timestamp(as_of)
    returns: dict[str, pd.Series] = {}
    for symbol, series in prices.items():
        truncated = series[series.index <= as_of]
        ret = safe_pct_change(truncated).dropna()
        returns[symbol] = ret.iloc[-lookback:] if lookback else ret

    aligned = pd.DataFrame(returns).dropna(how="any")  # inner join implicite sur l'index
    if len(aligned) < min_obs:
        raise ValueError(
            f"Seulement {len(aligned)} date(s) commune(s) apres alignement "
            f"(min_obs={min_obs}) pour {sorted(prices.keys())} a as_of={as_of.date()}."
        )

    symbols = list(prices.keys())
    if estimator == "ledoit_wolf":
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf().fit(aligned[symbols].values)
        cov = pd.DataFrame(lw.covariance_, index=symbols, columns=symbols)
        cov.attrs["shrinkage"] = float(lw.shrinkage_)
    else:
        cov = aligned.cov().loc[symbols, symbols]
        cov.attrs["shrinkage"] = 0.0
    cov.attrs["estimator"] = estimator
    cov.attrs["n_obs"] = len(aligned)
    return cov


def correlation_from_covariance(cov: pd.DataFrame) -> pd.DataFrame:
    """Matrice de correlation derivee d'une matrice de covariance -- utilise
    par HRP (distance de correlation) sans redemander l'historique de prix.
    Diagonale a exactement 1.0 (pas 0.999999...) par construction."""
    std = np.sqrt(np.diag(cov.values))
    outer = np.outer(std, std)
    outer[outer == 0] = np.nan
    corr = cov.values / outer
    np.fill_diagonal(corr, 1.0)
    return pd.DataFrame(corr, index=cov.index, columns=cov.columns)


def backfill_with_proxy(own: pd.Series | None, proxy: pd.Series, prior_multiplier: float | None = None,
                        min_overlap: int = 20) -> tuple[pd.Series, dict]:
    """Roadmap bloc 4 -- an asset without (enough) price history (D.A.T.E,
    listed 2026-09-25) gets a synthetic past: before its first quote, its
    daily returns are the proxy's returns x `scale`; from its first quote
    on, its own returns are kept untouched. Returns a price series (base
    100) usable by `point_in_time_covariance`, plus how the scale was set.

    `scale`: std(own) / std(proxy) on their common returns when there are
    at least `min_overlap` of them ("estimated"); otherwise the declared
    `prior_multiplier` ("prior", e.g. ~2 for a small cap proxied by a
    large-cap index -- an assumption, to be shown as such); otherwise 1.

    Limits (say them where the result is displayed): the synthetic past
    carries the proxy's correlations (beta x scale, no idiosyncratic
    part), so correlation to the rest of the portfolio is overstated and
    diversification understated -- the conservative side for a risk
    figure."""
    own = own.dropna().sort_index() if own is not None else pd.Series(dtype=float)
    proxy_ret = safe_pct_change(proxy.dropna().sort_index()).dropna()
    own_ret = safe_pct_change(own).dropna() if len(own) > 1 else pd.Series(dtype=float)
    overlap = own_ret.index.intersection(proxy_ret.index)
    if len(overlap) >= min_overlap and float(proxy_ret.loc[overlap].std()) > 0:
        scale, source = float(own_ret.loc[overlap].std() / proxy_ret.loc[overlap].std()), "estimated"
    elif prior_multiplier:
        scale, source = float(prior_multiplier), "prior"
    else:
        scale, source = 1.0, "default"
    first = own.index.min() if len(own) else None
    before = proxy_ret[proxy_ret.index <= first] if first is not None else proxy_ret
    returns = pd.concat([before * scale, own_ret]).sort_index()
    returns = returns[~returns.index.duplicated(keep="last")]
    prices = 100.0 * (1.0 + returns).cumprod()
    if len(proxy_ret):
        # Base-100 anchor on the proxy's first date (its first return is the day after).
        prices = pd.concat([pd.Series([100.0], index=[proxy.dropna().index.min()]), prices])
        prices = prices[~prices.index.duplicated(keep="last")].sort_index()
    return prices, {"own_obs": len(own), "scale": scale, "scale_source": source}
