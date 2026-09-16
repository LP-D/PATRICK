"""3 categories de modeles et leur comparaison croisee (CHANTIER B,
feature/model-categories-comparison) : "global" (pipeline actuel,
inchange), "per_regime" (un modele par regime -- label du CHANTIER A,
feature/regime-detection-hmm), "stacking" (leve explicitement l'ancien
commitment "pas de stacking" de `config/defaults.py`, voir sa docstring
mise a jour dans ce meme chantier).

*** PORTEE DELIBEREMENT SCOPEE (a lire avant d'etendre ce module) ***: ce
module est la couche de COMPARAISON statistique inter-categories
(DM/FDR/PBO + garde-fou de fragmentation), pas une reecriture du moteur
d'entrainement (`pipeline/engine.py`) pour y brancher reellement 3
entrainements distincts. Verifie avant d'ecrire ce module : le flag
`RunConfig.models.stacking` existe deja dans le schema mais n'est consomme
nulle part dans `engine.py` -- aucune implementation de stacking existante
a reutiliser, une integration complete (per-regime ET stacking reels dans
la boucle d'entrainement) est un chantier separe, plus large, hors scope
ici. `CategoryResult` prend en entree des metriques DEJA calculees par
categorie (`fold_metric`/`fold_loss`), quelle que soit la maniere dont
elles ont ete produites.

DSR (Deflated Sharpe Ratio) : `validation/dsr.py` documente lui-meme ne pas
etre encore appele dans `engine.py`, faute de serie de rendement reelle
(P&L) dans ce pipeline de classification -- ce module respecte la meme
limite plutot que de la contourner avec un proxy invente : `dsr_result`
reste `None` tant qu'aucune vraie serie de rendement (`returns`) n'est
fournie a `CategoryResult`.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.dsr import deflated_sharpe_ratio
from patrick.validation.fdr import benjamini_hochberg
from patrick.validation.pbo import compute_pbo


@dataclass(frozen=True)
class CategoryResult:
    category: str
    label: str  # identifiant du meilleur trial retenu dans cette categorie
    fold_metric: np.ndarray  # 1 valeur par fold (ex. F1_dir) -- entree de compute_pbo
    fold_loss: np.ndarray    # 0/1 loss par observation -- entree pairwise de diebold_mariano
    returns: np.ndarray | None = None  # serie de rendement REELLE, si disponible (voir docstring module)
    n_trials: int = 1  # nombre de trials parmi lesquels ce label a ete retenu (deflated_sharpe_ratio)

    def dsr(self) -> dict | None:
        if self.returns is None:
            return None
        return deflated_sharpe_ratio(self.returns, n_trials=self.n_trials)


def validate_per_regime_fragmentation(regime: pd.Series, horizon: int) -> None:
    """Reexpose `regime_detection.check_regime_fragmentation` avec le
    contexte "categorie par-regime" -- CHANTIER B ne doit jamais produire
    cette categorie sur un regime trop fragmente pour un walk-forward
    valide. Laisse `RegimeFragmentationError` se propager telle quelle
    (blocage dur, meme esprit que CHANTIER A -- jamais un warning)."""
    from patrick.features.regime_detection import check_regime_fragmentation
    check_regime_fragmentation(regime, horizon)


def compare_categories(results: dict[str, CategoryResult], dm_h: int = 1,
                        fdr_alpha: float = 0.10) -> dict:
    """`results`: {nom_categorie: CategoryResult} -- typiquement
    {"global", "per_regime", "stacking"} mais fonctionne pour N>=2. Pour
    chaque PAIRE de categories (C(N,2) comparaisons, pas seulement une
    categorie contre une baseline fixe) : test Diebold-Mariano sur
    `fold_loss` (alignement observation par observation suppose deja fait
    par l'appelant), puis correction Benjamini-Hochberg (FDR) sur
    l'ensemble de ces p-values pairwise. PBO (`compute_pbo`) traite chaque
    categorie comme UN trial (n_trials = len(results)), `fold_metric`
    empiles comme les blocs -- verifie si la categorie qui semble la
    meilleure "in-sample" (par bloc) le reste "out-of-sample", exactement
    la question que ce chantier pose. DSR : `None` par categorie tant
    qu'aucune serie de rendement reelle n'a ete fournie (voir docstring
    module) -- jamais un proxy invente."""
    categories = list(results.keys())
    if len(categories) < 2:
        raise ValueError("compare_categories necessite au moins 2 categories a comparer.")

    pairwise_dm: dict[str, dict] = {}
    p_values: dict[str, float] = {}
    for a, b in itertools.combinations(categories, 2):
        dm = diebold_mariano(results[a].fold_loss, results[b].fold_loss, h=dm_h)
        key = f"{a}_vs_{b}"
        pairwise_dm[key] = dm
        p_values[key] = dm["p_value"]

    fdr = benjamini_hochberg(p_values, alpha=fdr_alpha)

    perf_matrix = np.vstack([results[c].fold_metric for c in categories])
    pbo = compute_pbo(perf_matrix)

    dsr = {c: results[c].dsr() for c in categories}

    return {
        "categories": categories,
        "pairwise_dm": pairwise_dm,
        "fdr": fdr,
        "pbo": pbo,
        "dsr": dsr,
    }
