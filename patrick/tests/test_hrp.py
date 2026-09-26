"""CHANTIER D (feature/hrp-portfolio) : Hierarchical Risk Parity (Lopez de
Prado) -- clustering hierarchique par distance de correlation,
quasi-diagonalisation, bissection recursive ponderee par variance inverse.
S'ajoute a la detection de contradiction cross-actifs existante sur
`/portfolio` (`tracking/portfolio.py`), ne la remplace pas -- ce module ne
touche pas `portfolio.py`.

Depend de CHANTIER C (feature/covariance-matrix-utility) : cette branche est
creee directement depuis la POINTE de cette branche (pas un rebase
apres-coup, pas une reimportation du module) -- `git log` de cette branche
contient donc deja les commits de C."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.data.store import DataStore
from patrick.tracking.hrp import hrp_overview, hrp_weights


def test_hrp_weights_sum_to_one_and_are_non_negative():
    rng = np.random.default_rng(1)
    symbols = ["A", "B", "C", "D", "E"]
    cov = pd.DataFrame(rng.uniform(0.5, 2.0, (5, 5)), index=symbols, columns=symbols)
    cov = (cov + cov.T) / 2 + np.eye(5) * 5  # symetrique, diagonale dominante -> SDP valide
    cov = pd.DataFrame(cov.values, index=symbols, columns=symbols)

    w = hrp_weights(cov)

    assert set(w.index) == set(symbols)
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert (w >= 0).all()


def test_hrp_reduces_to_exact_inverse_variance_for_two_uncorrelated_assets():
    """Cas a la main : 2 actifs non correles, bissection recursive a un seul
    niveau -- degenerate exactement en ponderation inverse-variance (l'actif
    le plus volatil recoit le poids le plus faible)."""
    cov = pd.DataFrame(
        [[4.0, 0.0], [0.0, 1.0]],  # var_A=4, var_B=1, non correles
        index=["A", "B"], columns=["A", "B"],
    )
    w = hrp_weights(cov)

    expected_w_a = 1.0 / (1.0 + 4.0)  # var_B / (var_A + var_B)
    expected_w_b = 4.0 / (1.0 + 4.0)  # var_A / (var_A + var_B)
    assert w["A"] == pytest.approx(expected_w_a, rel=1e-6)
    assert w["B"] == pytest.approx(expected_w_b, rel=1e-6)
    assert w["B"] > w["A"]  # B (var=1) moins volatil que A (var=4) -> poids plus eleve


def _two_cluster_covariance(n_per_cluster: int = 4, within_corr: float = 0.9,
                             across_corr: float = 0.0, var: float = 1.0,
                             vary_vols: bool = False) -> pd.DataFrame:
    """2 clusters de `n_per_cluster` actifs fortement correles entre eux
    (within_corr) et quasi non correles entre clusters. `vary_vols=False`
    (defaut) : meme variance partout, pour que seule la STRUCTURE de
    correlation pilote les poids (isoler ce que HRP est cense capturer).
    `vary_vols=True` : volatilites legerement differentes par actif (casse
    la symetrie parfaite -- necessaire pour que la reference Markowitz
    min-variance de `test_hrp_does_not_concentrate_extremely...` ait
    effectivement quelque chose a "choisir" plutot que de retomber sur des
    poids uniformes par symetrie, ce qui ne testerait rien)."""
    n = n_per_cluster * 2
    corr = np.full((n, n), across_corr)
    corr[:n_per_cluster, :n_per_cluster] = within_corr
    corr[n_per_cluster:, n_per_cluster:] = within_corr
    np.fill_diagonal(corr, 1.0)
    if vary_vols:
        vols = np.tile(np.linspace(0.8, 1.2, n_per_cluster), 2) * np.sqrt(var)
    else:
        vols = np.full(n, np.sqrt(var))
    cov = corr * np.outer(vols, vols)
    symbols = [f"C1_{i}" for i in range(n_per_cluster)] + [f"C2_{i}" for i in range(n_per_cluster)]
    return pd.DataFrame(cov, index=symbols, columns=symbols)


def test_hrp_does_not_concentrate_extremely_on_a_near_singular_covariance():
    """Cas connu de la litterature HRP (Lopez de Prado) : sur une matrice de
    covariance quasi-singuliere (cluster fortement correle -> conditionnement
    numerique degrade), un optimiseur Markowitz classique (min-variance,
    inv(cov) @ 1) produit des poids extremes (voire negatifs, sans contrainte
    de non-negativite) -- HRP, par construction (jamais d'inversion globale de
    la matrice), reste borne et diversifie."""
    cov = _two_cluster_covariance(n_per_cluster=4, within_corr=0.95, vary_vols=True)

    w_hrp = hrp_weights(cov)
    assert w_hrp.max() < 0.40  # aucune concentration extreme malgre la quasi-singularite

    # Reference Markowitz min-variance (sans contrainte), sur la MEME matrice :
    # doit produire des poids bien plus extremes (au moins un > 0.40 ou negatif)
    # -- confirme que le cas est bien discriminant, pas que le seuil ci-dessus
    # est juste toujours vrai.
    inv_cov = np.linalg.inv(cov.values)
    ones = np.ones(len(cov))
    raw = inv_cov @ ones
    w_markowitz = raw / raw.sum()
    assert (np.abs(w_markowitz) > 0.40).any() or (w_markowitz < 0).any()


def test_hrp_gives_similar_weights_within_a_tightly_correlated_cluster():
    """Propriete de diversification attendue : au sein d'un cluster fortement
    correle et de variance identique, HRP ne doit pas ecraser un membre au
    profit d'un autre (contrairement a Markowitz, sensible au bruit
    d'estimation sur une matrice quasi-singuliere)."""
    cov = _two_cluster_covariance(n_per_cluster=4, within_corr=0.95)
    w = hrp_weights(cov)

    cluster1 = w[[c for c in w.index if c.startswith("C1_")]]
    assert (cluster1.max() / cluster1.min()) < 2.0


def test_hrp_raises_on_non_square_or_mismatched_covariance():
    bad = pd.DataFrame([[1.0, 0.5]], index=["A"], columns=["A", "B"])
    with pytest.raises(ValueError):
        hrp_weights(bad)


def test_hrp_single_asset_gets_full_weight():
    cov = pd.DataFrame([[1.0]], index=["ONLY"], columns=["ONLY"])
    w = hrp_weights(cov)
    assert w["ONLY"] == pytest.approx(1.0)


def test_hrp_overview_reads_only_what_is_cached_and_reports_skipped(tmp_path, monkeypatch):
    """`/portfolio` est en lecture seule (meme philosophie que
    `check_feasibility`) : `hrp_overview` ne doit jamais declencher de
    telechargement, seulement lire ce qui est deja en cache local, et
    lister explicitement ce qu'il n'a pas pu utiliser."""
    import patrick.config.defaults as D
    from patrick.data.sources.yfinance_source import clean_symbol

    store = DataStore(root=str(tmp_path))
    universe = D.DEFAULT_UNIVERSE_YF_TICKERS
    assert len(universe) >= 2, "l'univers reel doit contenir au moins 2 tickers pour ce test"

    rng = np.random.default_rng(42)
    cached_symbols = universe[:3]
    idx = pd.bdate_range("2018-01-01", periods=400)
    for sym in cached_symbols:
        col = clean_symbol(sym)
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, len(idx)))
        store.save(f"raw_{sym}", pd.DataFrame({col: prices}, index=idx))

    result = hrp_overview(store=store, lookback=252, min_obs=60)

    assert set(result["weights"].index) == set(cached_symbols)
    assert result["weights"].sum() == pytest.approx(1.0, abs=1e-9)
    for sym in universe:
        if sym not in cached_symbols:
            assert sym in result["skipped"]


def test_hrp_overview_uses_ledoit_wolf_and_reports_the_shrinkage(tmp_path):
    """Roadmap bloc 4 : covariance retrecie (Ledoit-Wolf) par defaut pour
    HRP ; l'estimateur et l'intensite sont exposes a la page."""
    import patrick.config.defaults as D
    from patrick.data.sources.yfinance_source import clean_symbol

    store = DataStore(root=str(tmp_path))
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2018-01-01", periods=400)
    for sym in D.DEFAULT_UNIVERSE_YF_TICKERS[:4]:
        store.save(f"raw_{sym}", pd.DataFrame(
            {clean_symbol(sym): 100 * np.cumprod(1 + rng.normal(0, 0.01, len(idx)))}, index=idx))
    result = hrp_overview(store=store)
    assert result["covariance"] == "ledoit_wolf"
    assert 0.0 < result["shrinkage"] < 1.0
    assert result["weights"].sum() == pytest.approx(1.0, abs=1e-9)
