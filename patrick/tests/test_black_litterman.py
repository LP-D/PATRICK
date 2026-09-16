"""CHANTIER E (feature/black-litterman-v1) : Black-Litterman v1 pragmatique
-- vue = direction predite (signe) ; magnitude = proxy calibre sur le
mouvement realise moyen historique, conditionne au niveau de confiance du
modele (y_proba) sur ce ticker/horizon ; incertitude = fonction DECROISSANTE
de y_proba combinee au hit rate glissant deja existant (mapping Idzorek
2005 : confiance -> Omega_ii, continu entre "vue ignoree" et "vue imposee
exactement").

Documente explicitement comme interimaire (v1), destinee a etre remplacee
quand des modeles a sortie calibree existeront -- voir docstring du module
d'implementation, pas seulement ce fichier de test.

Depend de CHANTIER C (feature/covariance-matrix-utility, prior d'equilibre)
: branche creee directement depuis sa pointe (meme methode que CHANTIER D),
pas une reimportation independante."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.tracking.black_litterman import (
    black_litterman_posterior,
    equilibrium_prior_returns,
    view_magnitude_proxy,
    view_uncertainty,
)


def _small_cov(n=3, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    symbols = [f"A{i}" for i in range(n)]
    m = rng.uniform(0.3, 0.8, (n, n))
    cov = m @ m.T + np.eye(n) * 0.5  # SDP garanti
    return pd.DataFrame(cov, index=symbols, columns=symbols)


def test_equilibrium_prior_defaults_to_equal_weights_reverse_optimization():
    cov = _small_cov()
    prior = equilibrium_prior_returns(cov, risk_aversion=2.5)
    expected = 2.5 * cov.values @ (np.ones(3) / 3)
    np.testing.assert_allclose(prior.values, expected)
    assert list(prior.index) == list(cov.index)


def test_equilibrium_prior_respects_custom_market_weights():
    cov = _small_cov()
    w = pd.Series([0.6, 0.3, 0.1], index=cov.index)
    prior = equilibrium_prior_returns(cov, market_weights=w, risk_aversion=2.5)
    expected = 2.5 * cov.values @ w.values
    np.testing.assert_allclose(prior.values, expected)


def test_view_uncertainty_decreases_as_confidence_increases():
    prior_var = 0.01
    u_low = view_uncertainty(prior_var, y_proba=0.55, hit_rate=0.50)
    u_mid = view_uncertainty(prior_var, y_proba=0.70, hit_rate=0.65)
    u_high = view_uncertainty(prior_var, y_proba=0.95, hit_rate=0.90)
    assert u_low > u_mid > u_high > 0


def test_view_magnitude_proxy_conditions_on_the_matching_confidence_bucket():
    """Donnees historiques ou un mouvement plus large est clairement associe
    aux fortes confiances -- le proxy doit refleter le bucket de la
    confiance COURANTE, pas la moyenne globale (qui melangerait les deux)."""
    n = 400
    rng = np.random.default_rng(2)
    low_conf = pd.Series(rng.uniform(0.5, 0.6, n // 2))
    high_conf = pd.Series(rng.uniform(0.9, 1.0, n // 2))
    historical_confidence = pd.concat([low_conf, high_conf], ignore_index=True)
    # Mouvement realise clairement plus grand quand la confiance historique etait forte.
    move_low = rng.normal(0.005, 0.001, n // 2)
    move_high = rng.normal(0.05, 0.001, n // 2)
    historical_move = pd.Series(np.concatenate([move_low, move_high]))

    proxy_for_high_conf = view_magnitude_proxy(historical_confidence, historical_move,
                                                current_y_proba=0.95, n_buckets=5)
    proxy_for_low_conf = view_magnitude_proxy(historical_confidence, historical_move,
                                               current_y_proba=0.55, n_buckets=5)
    assert proxy_for_high_conf > proxy_for_low_conf
    assert proxy_for_high_conf == pytest.approx(0.05, abs=0.01)
    assert proxy_for_low_conf == pytest.approx(0.005, abs=0.01)


def test_view_magnitude_proxy_falls_back_to_overall_mean_when_bucket_too_sparse():
    historical_confidence = pd.Series([0.9, 0.91, 0.92])
    historical_move = pd.Series([0.02, 0.021, 0.019])
    # current_y_proba tombe dans un bucket vide (aucune observation historique la) :
    # doit retomber sur la moyenne globale (min_bucket_obs non atteint), pas planter/NaN.
    proxy = view_magnitude_proxy(historical_confidence, historical_move,
                                  current_y_proba=0.10, n_buckets=10, min_bucket_obs=5)
    assert proxy == pytest.approx(historical_move.abs().mean())


def test_posterior_converges_to_prior_alone_as_confidence_approaches_zero():
    cov = _small_cov()
    prior = equilibrium_prior_returns(cov)
    views = [{"asset": "A0", "direction": 1, "magnitude": 0.10, "y_proba": 1e-6, "hit_rate": 1e-6}]

    posterior, _ = black_litterman_posterior(cov, prior, views, tau=0.05)
    np.testing.assert_allclose(posterior.values, prior.values, atol=1e-3)


def test_posterior_converges_to_the_view_alone_as_confidence_approaches_one():
    cov = _small_cov()
    prior = equilibrium_prior_returns(cov)
    views = [{"asset": "A0", "direction": 1, "magnitude": 0.10, "y_proba": 1 - 1e-9, "hit_rate": 1 - 1e-9}]

    posterior, _ = black_litterman_posterior(cov, prior, views, tau=0.05)
    assert posterior["A0"] == pytest.approx(0.10, abs=1e-3)


def test_posterior_direction_minus_one_pulls_the_view_asset_down():
    """A l'echelle de `_small_cov()` (variances ~O(1), pensee pour les
    autres tests ou seule la FORMULE compte, pas l'echelle), le prior
    d'equilibre ecrase totalement une vue de magnitude realiste (0.08,
    8%) : il faut une covariance a l'echelle d'un vrai rendement journalier
    (variance ~1e-4) pour que le SIGNE de la vue soit visible sans etre
    noye par un prior surdimensionne -- sinon ce test ne verifierait rien."""
    cov = _small_cov() * 1e-4
    prior = equilibrium_prior_returns(cov)
    views_up = [{"asset": "A0", "direction": 1, "magnitude": 0.08, "y_proba": 0.85, "hit_rate": 0.70}]
    views_down = [{"asset": "A0", "direction": -1, "magnitude": 0.08, "y_proba": 0.85, "hit_rate": 0.70}]

    posterior_up, _ = black_litterman_posterior(cov, prior, views_up, tau=0.05)
    posterior_down, _ = black_litterman_posterior(cov, prior, views_down, tau=0.05)
    assert posterior_up["A0"] > prior["A0"] > posterior_down["A0"]


def test_posterior_covariance_is_never_smaller_than_the_prior_covariance_diag():
    """Black-Litterman ne peut jamais reduire l'incertitude sous celle du
    prior (Sigma_posterior = Sigma + terme positif semi-defini) -- verifie
    sur la diagonale, plus simple qu'une comparaison matricielle complete."""
    cov = _small_cov()
    prior = equilibrium_prior_returns(cov)
    views = [{"asset": "A0", "direction": 1, "magnitude": 0.05, "y_proba": 0.8, "hit_rate": 0.6}]

    _, posterior_cov = black_litterman_posterior(cov, prior, views, tau=0.05)
    assert (np.diag(posterior_cov.values) >= np.diag(cov.values) - 1e-9).all()
