"""CHANTIER B (feature/model-categories-comparison) : 3 categories de
modeles (global / par-regime / stacking) et leur comparaison croisee
(DM/FDR/PBO). Depend de CHANTIER A (feature/regime-detection-hmm, label de
regime + garde-fou de fragmentation) -- cette branche est creee directement
depuis la POINTE de feature/regime-detection-hmm (meme methode que
CHANTIER D/E pour CHANTIER C), pas un rebase apres-coup.

Portee de ce module, deliberement scopee (a signaler dans le rapport) : la
couche de COMPARAISON statistique inter-categories (DM/FDR/PBO + garde-fou
de fragmentation), pas un reecriture du moteur d'entrainement
(pipeline/engine.py) pour y brancher reellement 3 entrainements distincts
(le stacking en particulier n'a aucune implementation existante malgre le
flag `models.stacking` deja present dans le schema -- verifie par grep avant
d'ecrire ce module : ce flag n'est consomme nulle part dans engine.py). Cette
couche prend en entree les resultats DEJA calcules de chaque categorie
(fold_metric/fold_loss), produits ailleurs par le pipeline d'entrainement --
une integration complete du training per-regime/stacking dans engine.py est
hors-scope ici, signalee explicitement plutot que bricolee a la hate.

DSR (Deflated Sharpe Ratio) : `validation/dsr.py` documente lui-meme ne pas
etre encore appele depuis `pipeline/engine.py`, faute de serie de rendement
reelle (P&L) dans ce pipeline de classification -- ce module respecte la
meme limite (jamais invente une serie de rendement a partir des scores de
classification pour la contourner) : `dsr_result` reste `None` tant
qu'aucune vraie serie de rendement n'est fournie par l'appelant, jamais
silencieusement remplace par un proxy."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.tracking.model_categories import (
    CategoryResult,
    compare_categories,
    validate_per_regime_fragmentation,
)
from patrick.features.regime_detection import RegimeFragmentationError


def _category(seed: int, n_folds: int = 6, n_obs: int = 500, loss_shift: float = 0.0) -> CategoryResult:
    rng = np.random.default_rng(seed)
    fold_metric = rng.uniform(0.4, 0.6, n_folds)
    fold_loss = (rng.uniform(0, 1, n_obs) < (0.5 + loss_shift)).astype(float)
    return CategoryResult(category=f"cat{seed}", label=f"best_trial_{seed}",
                           fold_metric=fold_metric, fold_loss=fold_loss)


def test_three_categories_produce_distinct_artifacts():
    """Chaque categorie garde son propre label/metriques -- pas de fusion ni
    d'ecrasement silencieux d'une categorie par une autre."""
    global_cat = _category(1, loss_shift=-0.1)
    per_regime_cat = _category(2, loss_shift=0.0)
    stacking_cat = _category(3, loss_shift=0.1)

    results = {"global": global_cat, "per_regime": per_regime_cat, "stacking": stacking_cat}
    comparison = compare_categories(results)

    assert comparison["categories"] == ["global", "per_regime", "stacking"]
    # 3 artefacts bien distincts, pas de collision de labels/metriques.
    labels = {c.label for c in results.values()}
    assert len(labels) == 3
    assert not np.array_equal(global_cat.fold_metric, stacking_cat.fold_metric)


def test_pairwise_dm_comparison_covers_all_three_pairs_not_just_two():
    results = {
        "global": _category(1, loss_shift=-0.15),
        "per_regime": _category(2, loss_shift=0.0),
        "stacking": _category(3, loss_shift=0.15),
    }
    comparison = compare_categories(results)

    # C(3,2) = 3 comparaisons attendues, pas seulement une paire.
    assert set(comparison["pairwise_dm"].keys()) == {
        "global_vs_per_regime", "global_vs_stacking", "per_regime_vs_stacking",
    }
    for dm in comparison["pairwise_dm"].values():
        assert "p_value" in dm and "dm_stat" in dm


def test_fdr_correction_is_applied_to_exactly_the_pairwise_p_values():
    """La correction FDR doit porter sur les C(3,2)=3 p-values pairwise, pas
    sur un nombre different (ex. si un futur refactor ajoutait/retirait une
    comparaison sans mettre a jour la correction en consequence)."""
    results = {
        "global": _category(1, loss_shift=-0.15),
        "per_regime": _category(2, loss_shift=0.0),
        "stacking": _category(3, loss_shift=0.15),
    }
    comparison = compare_categories(results, fdr_alpha=0.10)

    assert comparison["fdr"]["n_tested"] == 3
    assert set(comparison["fdr"]["results"].keys()) == set(comparison["pairwise_dm"].keys())


def test_pbo_is_computed_across_the_three_categories_as_three_trials():
    results = {
        "global": _category(1),
        "per_regime": _category(2),
        "stacking": _category(3),
    }
    comparison = compare_categories(results)
    assert comparison["pbo"]["n_trials"] == 3


def test_dsr_stays_none_when_no_return_series_is_supplied():
    """Jamais un proxy invente silencieusement -- voir docstring module."""
    results = {
        "global": _category(1),
        "per_regime": _category(2),
        "stacking": _category(3),
    }
    comparison = compare_categories(results)
    assert all(v is None for v in comparison["dsr"].values())


def test_dsr_is_reported_per_category_when_a_return_series_is_supplied():
    rng = np.random.default_rng(5)
    returns = rng.normal(0.001, 0.01, 300)
    cat = _category(1)
    cat_with_dsr = CategoryResult(category=cat.category, label=cat.label,
                                   fold_metric=cat.fold_metric, fold_loss=cat.fold_loss,
                                   returns=returns, n_trials=10)
    results = {"global": cat_with_dsr, "per_regime": _category(2), "stacking": _category(3)}
    comparison = compare_categories(results)

    assert comparison["dsr"]["global"] is not None
    assert "dsr" in comparison["dsr"]["global"]
    assert comparison["dsr"]["per_regime"] is None


def test_validate_per_regime_fragmentation_blocks_on_a_rare_regime():
    idx = pd.bdate_range("2015-01-01", periods=2000)
    labels = ["calme"] * 1995 + ["stress"] * 5
    regime = pd.Series(labels, index=idx)

    with pytest.raises(RegimeFragmentationError):
        validate_per_regime_fragmentation(regime, horizon=10)


def test_validate_per_regime_fragmentation_passes_on_sufficient_history():
    idx = pd.bdate_range("2015-01-01", periods=20000)
    labels = ["calme"] * 10000 + ["normal"] * 8000 + ["stress"] * 2000
    regime = pd.Series(labels, index=idx)
    validate_per_regime_fragmentation(regime, horizon=10)  # ne doit pas lever


def test_compare_categories_requires_at_least_two_categories():
    with pytest.raises(ValueError):
        compare_categories({"global": _category(1)})
