"""Hierarchical Risk Parity (CHANTIER D, feature/hrp-portfolio) -- Lopez de
Prado, "Building Diversified Portfolios that Outperform Out-of-Sample"
(2016) : clustering hierarchique par distance de correlation,
quasi-diagonalisation, bissection recursive ponderee par variance inverse.
Aucun rendement espere requis (contrairement a Markowitz) ; par construction,
n'inverse jamais la matrice de covariance globale (seulement des IVP locaux
par sous-cluster), d'ou sa robustesse au bruit d'estimation sur une matrice
quasi-singuliere (cluster fortement correle) -- voir
`tests/test_hrp.py::test_hrp_does_not_concentrate_extremely_on_a_near_singular_covariance`
pour la comparaison directe avec un Markowitz min-variance classique sur la
meme matrice.

Consomme `tracking/covariance.py::point_in_time_covariance` (CHANTIER C) --
cette branche a ete creee directement depuis la pointe de
feature/covariance-matrix-utility (voir docstring de test), pas re-importee
independamment.

S'ajoute a la detection de contradiction cross-actifs deja existante sur
`/portfolio` (`tracking/portfolio.py`) -- ne la remplace pas, ce module ne
touche pas `portfolio.py`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.tracking.covariance import correlation_from_covariance


def _quasi_diag_order(link: np.ndarray) -> list[int]:
    """Ordonne les feuilles du dendrogramme (linkage `scipy`) de sorte que
    les actifs similaires soient adjacents -- implementation standard Lopez
    de Prado, reecrite ici sans la dependance a l'indexation mutable de
    `pd.Series` de la version originale (plus lisible, meme resultat)."""
    link = link.astype(int)
    num_items = link[-1, 3]
    clusters: list[int] = [link[-1, 0], link[-1, 1]]
    while any(c >= num_items for c in clusters):
        new_clusters: list[int] = []
        for c in clusters:
            if c >= num_items:
                left, right = link[c - num_items, 0], link[c - num_items, 1]
                new_clusters.extend([left, right])
            else:
                new_clusters.append(c)
        clusters = new_clusters
    return clusters


def _cluster_variance(cov: pd.DataFrame, items: list[str]) -> float:
    """Variance d'un (sous-)cluster sous ponderation inverse-variance (IVP)
    LOCALE a ce cluster -- jamais une inversion de la matrice de covariance
    globale, c'est precisement ce qui rend HRP robuste sur une matrice
    quasi-singuliere."""
    sub = cov.loc[items, items]
    ivp = 1.0 / np.diag(sub.values)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub.values @ ivp)


def _recursive_bisection(cov: pd.DataFrame, ordered_symbols: list[str]) -> pd.Series:
    weights = pd.Series(1.0, index=ordered_symbols)
    clusters = [ordered_symbols]
    while clusters:
        next_clusters = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            mid = len(cluster) // 2
            left, right = cluster[:mid], cluster[mid:]
            var_left = _cluster_variance(cov, left)
            var_right = _cluster_variance(cov, right)
            alpha = 1.0 - var_left / (var_left + var_right)
            weights[left] *= alpha
            weights[right] *= (1.0 - alpha)
            next_clusters.extend([left, right])
        clusters = next_clusters
    return weights


def hrp_weights(cov: pd.DataFrame) -> pd.Series:
    """Poids HRP a partir d'une matrice de covariance (typiquement
    `tracking/covariance.py::point_in_time_covariance`). Retourne une
    `pd.Series` indexee par symbole, poids positifs sommant a 1 (pas de
    vente a decouvert -- HRP de base, pas une variante avec contraintes de
    levier)."""
    if cov.shape[0] != cov.shape[1] or list(cov.index) != list(cov.columns):
        raise ValueError("hrp_weights attend une matrice de covariance carree, "
                          "index et colonnes identiques.")

    symbols = list(cov.index)
    if len(symbols) == 1:
        return pd.Series([1.0], index=symbols)

    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform

    corr = correlation_from_covariance(cov)
    dist = np.sqrt(np.clip((1.0 - corr.values) / 2.0, 0.0, None))
    np.fill_diagonal(dist, 0.0)
    dist = (dist + dist.T) / 2.0  # force la symetrie exacte (bruit flottant)

    link = linkage(squareform(dist, checks=False), method="single")
    order = _quasi_diag_order(link)
    ordered_symbols = [symbols[i] for i in order]

    weights = _recursive_bisection(cov, ordered_symbols)
    return weights.reindex(symbols)


def hrp_overview(as_of=None, lookback: int = 252, min_obs: int = 60, store=None,
                 estimator: str = "ledoit_wolf") -> dict:
    """Poids HRP sur l'univers complet (`config.defaults.DEFAULT_UNIVERSE_
    YF_TICKERS`) a partir des prix DEJA en cache localement (`DataStore`) --
    lit uniquement ce qui existe, ne telecharge jamais depuis cette page en
    lecture seule (meme philosophie que `validation/feasibility.py` :
    exposer avec un avertissement plutot que bloquer). Les symboles absents
    du cache ou avec trop peu d'historique sont listes dans `"skipped"`,
    jamais silencieusement ignores -- consomme par `/portfolio`
    (`webapp/app.py::portfolio_page`).

    `estimator` (roadmap bloc 4) : Ledoit-Wolf par defaut -- ~40 actifs sur
    252 rendements (T/N ~ 6), la covariance empirique y est bruitee et HRP
    en tire directement ses variances inverses et ses distances de
    correlation. `covariance`/`shrinkage` sont renvoyes pour affichage."""
    from patrick.config import defaults as D
    from patrick.data.sources.yfinance_source import clean_symbol
    from patrick.data.store import DataStore

    store = store or DataStore()
    prices: dict[str, pd.Series] = {}
    skipped: list[str] = []
    for symbol in D.DEFAULT_UNIVERSE_YF_TICKERS:
        cache_key = f"raw_{symbol}"
        if not store.exists(cache_key):
            skipped.append(symbol)
            continue
        df = store.load(cache_key)
        col = clean_symbol(symbol)
        if col not in df.columns:
            col = "Close" if "Close" in df.columns else df.columns[0]
        prices[symbol] = df[col].dropna()

    if not prices:
        return {"weights": pd.Series(dtype=float), "skipped": sorted(skipped), "as_of": as_of, "n_assets": 0}

    as_of_ts = pd.Timestamp(as_of) if as_of is not None else max(s.index.max() for s in prices.values())

    usable = {}
    for sym, s in prices.items():
        trunc = s[s.index <= as_of_ts]
        if len(trunc) >= min_obs + 1:  # +1 : pct_change perd la 1ere observation
            usable[sym] = trunc
        else:
            skipped.append(sym)

    if len(usable) < 2:
        return {"weights": pd.Series(dtype=float), "skipped": sorted(set(skipped)),
                "as_of": as_of_ts, "n_assets": len(usable)}

    from patrick.tracking.covariance import point_in_time_covariance
    try:
        cov = point_in_time_covariance(usable, as_of=as_of_ts, lookback=lookback, min_obs=min_obs,
                                       estimator=estimator)
    except ValueError:
        return {"weights": pd.Series(dtype=float), "skipped": sorted(set(skipped) | set(usable)),
                "as_of": as_of_ts, "n_assets": 0}

    weights = hrp_weights(cov).sort_values(ascending=False)
    return {"weights": weights, "skipped": sorted(set(skipped)), "as_of": as_of_ts, "n_assets": len(weights),
            "covariance": estimator, "shrinkage": cov.attrs.get("shrinkage"), "n_obs": cov.attrs.get("n_obs")}
