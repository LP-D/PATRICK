"""CHANTIER C (feature/covariance-matrix-utility) : matrice de covariance
point-in-time strict, partagee (reutilisable par HRP -- CHANTIER D -- et tout
futur besoin), applicable a n'importe quel sous-ensemble de l'univers
(commodites, macro, VIX, EUR/USD, S&P500, BTC...), pas seulement les actifs
utilises par HRP.

Decision de conception (a signaler) : la fonction est volontairement PURE --
elle prend en entree un dict {symbole: pd.Series de prix}, jamais un acces
direct a `DataStore`/aux tickers de l'univers. Les classes d'actifs de
l'univers (VIX, EUR/USD, BTC...) tradent sur des calendriers differents
(BTC 7j/7, FX 5j/7, actions avec jours feries locaux) ; aligner les
rendements sur les dates COMMUNES a tous les actifs demandes (inner join) est
le choix le plus simple et le plus defendable pour un calcul general -- documente
ici plutot que cache dans le code."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.tracking.covariance import (
    correlation_from_covariance,
    point_in_time_covariance,
)


def _price_series(seed: int, n: int, start: str = "2018-01-01", drift: float = 0.0,
                   vol: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(100 * np.cumprod(1 + rets), index=idx)


def test_covariance_matches_numpy_cov_on_a_known_subset():
    """Sous-ensemble connu (2 actifs, memes dates), verifie main via
    numpy.cov -- pas seulement une auto-coherence interne."""
    n = 500
    idx = pd.bdate_range("2019-01-01", periods=n)
    rng = np.random.default_rng(3)
    rets_a = rng.normal(0, 0.01, n)
    rets_b = 0.5 * rets_a + rng.normal(0, 0.01, n)  # correle a A par construction
    price_a = pd.Series(100 * np.cumprod(1 + rets_a), index=idx)
    price_b = pd.Series(50 * np.cumprod(1 + rets_b), index=idx)

    cov = point_in_time_covariance({"A": price_a, "B": price_b}, as_of=idx[-1], lookback=n - 1)

    # Reference manuelle : memes rendements (pct_change) que la fonction testee.
    ret_a = price_a.pct_change().dropna()
    ret_b = price_b.pct_change().dropna()
    expected = np.cov(np.vstack([ret_a.values, ret_b.values]))

    assert cov.loc["A", "A"] == pytest.approx(expected[0, 0], rel=1e-6)
    assert cov.loc["B", "B"] == pytest.approx(expected[1, 1], rel=1e-6)
    assert cov.loc["A", "B"] == pytest.approx(expected[0, 1], rel=1e-6)
    assert cov.loc["A", "B"] == cov.loc["B", "A"]  # symetrique


def test_covariance_is_strictly_point_in_time():
    """Meme garantie que les autres chantiers : ce qui se passe APRES
    `as_of` ne doit jamais influencer la matrice calculee A `as_of`."""
    n = 800
    prices = {
        "X": _price_series(1, n),
        "Y": _price_series(2, n),
        "Z": _price_series(3, n),
    }
    as_of = prices["X"].index[500]

    cov_full_history = point_in_time_covariance(prices, as_of=as_of, lookback=252)

    truncated = {k: v.iloc[:520] for k, v in prices.items()}  # un peu de marge apres as_of
    cov_truncated = point_in_time_covariance(truncated, as_of=as_of, lookback=252)

    pd.testing.assert_frame_equal(cov_full_history, cov_truncated)


def test_covariance_works_across_mismatched_calendars():
    """Actifs a calendriers differents (ex. BTC 7j/7 vs actions 5j/7) --
    doit s'aligner sur les dates COMMUNES sans lever, pas seulement sur un
    sous-ensemble deja aligne comme HRP."""
    n = 400
    equity_idx = pd.bdate_range("2020-01-01", periods=n)  # 5j/7
    crypto_idx = pd.date_range("2020-01-01", periods=int(n * 1.4))  # 7j/7, plus dense
    rng = np.random.default_rng(9)
    equity = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=equity_idx)
    crypto = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.03, len(crypto_idx))), index=crypto_idx)

    cov = point_in_time_covariance({"EQUITY": equity, "CRYPTO": crypto},
                                    as_of=equity_idx[-1], lookback=252, min_obs=60)
    assert cov.shape == (2, 2)
    assert np.isfinite(cov.values).all()


def test_covariance_raises_when_not_enough_common_observations():
    idx_a = pd.bdate_range("2020-01-01", periods=300)
    idx_b = pd.bdate_range("2025-01-01", periods=300)  # aucun recouvrement avec A
    price_a = pd.Series(100.0, index=idx_a)
    price_b = pd.Series(50.0, index=idx_b)

    with pytest.raises(ValueError):
        point_in_time_covariance({"A": price_a, "B": price_b}, as_of=idx_b[-1],
                                  lookback=252, min_obs=60)


def test_correlation_from_covariance_has_unit_diagonal_and_bounded_offdiag():
    n = 500
    idx = pd.bdate_range("2019-01-01", periods=n)
    rng = np.random.default_rng(5)
    rets_a = rng.normal(0, 0.01, n)
    rets_b = 0.7 * rets_a + rng.normal(0, 0.005, n)
    price_a = pd.Series(100 * np.cumprod(1 + rets_a), index=idx)
    price_b = pd.Series(50 * np.cumprod(1 + rets_b), index=idx)

    cov = point_in_time_covariance({"A": price_a, "B": price_b}, as_of=idx[-1], lookback=n - 1)
    corr = correlation_from_covariance(cov)

    assert corr.loc["A", "A"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["B", "B"] == pytest.approx(1.0, abs=1e-9)
    assert -1.0 <= corr.loc["A", "B"] <= 1.0
    # Construction : B fortement co-mouvant avec A (0.7x + petit bruit) -> forte
    # correlation positive (theorique ~0.81 ; 0.75 laisse une marge au bruit
    # d'echantillonnage a n=500 sans affaiblir ce que le test verifie).
    assert corr.loc["A", "B"] > 0.75


def test_covariance_matrix_is_symmetric_and_positive_semidefinite():
    n = 600
    prices = {sym: _price_series(seed, n) for seed, sym in enumerate(["VIX", "SPX", "BTC", "EURUSD"])}
    cov = point_in_time_covariance(prices, as_of=prices["VIX"].index[-1], lookback=n - 1)

    assert np.allclose(cov.values, cov.values.T)
    eigenvalues = np.linalg.eigvalsh(cov.values)
    assert (eigenvalues >= -1e-10).all()  # tolerance numerique


def test_ledoit_wolf_estimator_matches_sklearn_on_the_same_returns():
    """Roadmap bloc 4 : HRP estime ~40x40 covariances sur 252 rendements --
    la covariance empirique y est bruitee (T/N ~ 6). Ledoit-Wolf retrecit
    vers une cible structuree avec une intensite estimee."""
    from sklearn.covariance import LedoitWolf

    prices = {f"S{i}": _price_series(i, 300) for i in range(5)}
    idx = prices["S0"].index
    cov = point_in_time_covariance(prices, as_of=idx[-1], lookback=250, estimator="ledoit_wolf")
    rets = pd.DataFrame({k: v.pct_change() for k, v in prices.items()}).dropna().iloc[-250:]
    expected = LedoitWolf().fit(rets.values).covariance_
    np.testing.assert_allclose(cov.values, expected, rtol=1e-10)
    assert 0.0 < cov.attrs["shrinkage"] < 1.0


def test_ledoit_wolf_stays_invertible_when_assets_outnumber_observations():
    prices = {f"S{i}": _price_series(100 + i, 40) for i in range(60)}
    as_of = prices["S0"].index[-1]
    sample = point_in_time_covariance(prices, as_of=as_of, lookback=0, min_obs=30)
    shrunk = point_in_time_covariance(prices, as_of=as_of, lookback=0, min_obs=30, estimator="ledoit_wolf")
    assert np.linalg.matrix_rank(sample.values) < 60
    assert np.linalg.eigvalsh(shrunk.values).min() > 0


def test_unknown_estimator_is_rejected():
    prices = {"A": _price_series(1, 100), "B": _price_series(2, 100)}
    with pytest.raises(ValueError):
        point_in_time_covariance(prices, as_of=prices["A"].index[-1], estimator="oas")
