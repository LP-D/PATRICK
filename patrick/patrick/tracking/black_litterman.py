"""Black-Litterman v1 (CHANTIER E, feature/black-litterman-v1) -- melange
bayesien entre un prior d'equilibre (derive de la matrice de covariance
partagee, CHANTIER C) et des "vues" issues des predictions du modele.

*** V1 INTERIMAIRE, documentee comme telle *** : ce framework ne produit pas
(encore) de sortie de modele calibree (une vraie probabilite de rendement).
La magnitude de chaque vue est donc un PROXY -- le mouvement realise moyen
HISTORIQUE, conditionne au bucket de confiance du modele sur ce ticker/
horizon (pas la prediction elle-meme) -- et l'incertitude de la vue combine
y_proba au hit rate glissant deja suivi ailleurs dans le projet
(`tracking.history.LIVE_HIT_RATE_WINDOW`). Destinee a etre remplacee quand
des modeles a sortie calibree existeront (probabilite/magnitude reellement
estimees, pas un proxy historique) -- cette limite n'est pas cachee, elle
conditionne directement la qualite du posterior produit ici.

Prior d'equilibre : sans donnees de capitalisation de marche pour cet
univers (VIX, FX, commodites, macro n'ont pas de "market cap"), le prior
utilise par defaut des poids EGAUX en reverse-optimization (pi = delta *
Sigma * w) -- egalement documente comme substitut pragmatique, pas une
vraie ponderation de marche.

v1 : une seule vue par actif (matrice P a lignes one-hot), pas de vues
relatives multi-actifs (extension possible d'une v2 hors scope ici).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def equilibrium_prior_returns(cov: pd.DataFrame, market_weights: pd.Series | None = None,
                               risk_aversion: float = 2.5) -> pd.Series:
    """Prior d'equilibre par reverse-optimization : pi = delta * Sigma * w.
    `market_weights=None` -> poids egaux (voir limite documentee en tete de
    module : pas de vraie ponderation de capitalisation disponible ici)."""
    assets = list(cov.index)
    if market_weights is None:
        w = pd.Series(1.0 / len(assets), index=assets)
    else:
        w = market_weights.reindex(assets)
        if w.isna().any():
            raise ValueError("market_weights doit couvrir tous les actifs de `cov`.")
    pi = risk_aversion * (cov.values @ w.values)
    return pd.Series(pi, index=assets)


def view_uncertainty(prior_view_variance: float, y_proba: float, hit_rate: float,
                      eps: float = 1e-6) -> float:
    """Incertitude (Omega diagonal) d'une vue -- mapping Idzorek (2005) :
    confiance effective = moyenne de y_proba (confiance du modele sur cette
    prediction) et du hit rate glissant deja suivi ailleurs dans le projet,
    bornee dans (eps, 1-eps) pour eviter une matrice Omega singuliere aux
    limites exactes. Omega_ii -> 0 quand confiance -> 1 (vue quasi imposee
    telle quelle au posterior) ; Omega_ii -> +inf quand confiance -> 0 (vue
    quasi ignoree, le posterior retombe sur le prior seul) -- comportement
    verifie directement dans `tests/test_black_litterman.py` (cas limites)."""
    confidence = np.clip((y_proba + hit_rate) / 2.0, eps, 1.0 - eps)
    return prior_view_variance * (1.0 - confidence) / confidence


def view_magnitude_proxy(historical_confidence: pd.Series, historical_move: pd.Series,
                          current_y_proba: float, n_buckets: int = 5,
                          min_bucket_obs: int = 5) -> float:
    """Magnitude d'une vue : mouvement realise moyen (valeur absolue)
    HISTORIQUEMENT observe quand le modele affichait un niveau de confiance
    similaire a `current_y_proba` -- PAS la prediction courante elle-meme
    (v1, voir limite documentee en tete de module). Les deux series doivent
    etre alignees (meme longueur, meme ordre -- une observation historique
    par ligne). Bucket a largeur fixe sur [0, 1] ; si le bucket correspondant
    a `current_y_proba` a moins de `min_bucket_obs` observations, repli sur
    la moyenne globale (jamais un NaN silencieux)."""
    if len(historical_confidence) != len(historical_move):
        raise ValueError("historical_confidence et historical_move doivent avoir la meme longueur.")

    edges = np.linspace(0.0, 1.0, n_buckets + 1)
    bucket_idx = np.clip(np.digitize(historical_confidence.values, edges) - 1, 0, n_buckets - 1)
    current_bucket = np.clip(np.digitize([current_y_proba], edges)[0] - 1, 0, n_buckets - 1)

    mask = bucket_idx == current_bucket
    if mask.sum() < min_bucket_obs:
        return float(historical_move.abs().mean())
    return float(historical_move.values[mask].__abs__().mean())


def black_litterman_posterior(cov: pd.DataFrame, prior_returns: pd.Series, views: list[dict],
                               tau: float = 0.05) -> tuple[pd.Series, pd.DataFrame]:
    """Melange bayesien standard (He-Litterman) : chaque entree de `views`
    est un dict {"asset", "direction" (+1/-1), "magnitude" (>=0, proxy
    calibre -- voir `view_magnitude_proxy`), "y_proba", "hit_rate"} portant
    sur UN SEUL actif (v1). Retourne (rendements posterior, covariance
    posterior) -- `Sigma_posterior = Sigma + [(tau*Sigma)^-1 + P'Omega^-1P]^-1`
    (l'incertitude posterior ne peut jamais etre inferieure a celle du
    prior, verifie dans les tests)."""
    assets = list(cov.index)
    tau_cov = tau * cov.values
    tau_cov_inv = np.linalg.inv(tau_cov)

    n_views = len(views)
    P = np.zeros((n_views, len(assets)))
    Q = np.zeros(n_views)
    omega_diag = np.zeros(n_views)
    for i, v in enumerate(views):
        j = assets.index(v["asset"])
        P[i, j] = 1.0
        Q[i] = v["direction"] * v["magnitude"]
        prior_view_var = float(P[i] @ tau_cov @ P[i])
        omega_diag[i] = view_uncertainty(prior_view_var, v["y_proba"], v["hit_rate"])
    omega_inv = np.diag(1.0 / omega_diag)

    posterior_precision = tau_cov_inv + P.T @ omega_inv @ P
    posterior_cov_term = np.linalg.inv(posterior_precision)
    posterior_mean = posterior_cov_term @ (tau_cov_inv @ prior_returns.values + P.T @ omega_inv @ Q)

    posterior_returns = pd.Series(posterior_mean, index=assets)
    posterior_cov = pd.DataFrame(cov.values + posterior_cov_term, index=assets, columns=assets)
    return posterior_returns, posterior_cov
