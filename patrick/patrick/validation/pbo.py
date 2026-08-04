"""Probability of Backtest Overfitting (Bailey, Borwein, López de Prado & Zhu,
"The Probability of Backtest Overfitting", 2017) via CSCV (Combinatorially
Symmetric Cross-Validation).

Écart assumé par rapport au papier original : celui-ci découpe la série de
rendements en S blocs temporels arbitraires (paramètre libre). Ici, les blocs
sont directement les folds walk-forward déjà calculés par le moteur
(`fold_metric`, un par (trial, fold)) — respecte la structure temporelle par
construction (chaque fold est déjà une tranche chronologique contiguë), pas
de découpage supplémentaire à inventer ni à justifier séparément.

Limite documentée : CSCV veut un nombre PAIR de blocs, idéalement S>=16 pour
un nombre de combinaisons raisonnable. `n_wf_folds` vaut 5 par défaut dans ce
projet (impair, pensé pour le walk-forward, pas pour CSCV) — le fold le plus
ancien est donc retiré pour retomber sur un nombre pair (4 par défaut, 6
combinaisons IS/OOS). Un `n_wf_folds` plus élevé donne un PBO plus robuste ;
documenté plutôt que masqué, cf. rapport de phase.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np


def compute_pbo(perf_matrix: np.ndarray) -> dict:
    """`perf_matrix` : (n_trials, n_blocks) — une métrique de performance (ex.
    F1_dir) par (trial, bloc temporel). Pour chaque partition des blocs en deux
    moitiés égales (in-sample / out-of-sample, toutes les combinaisons), on
    repère le trial le meilleur en IS puis on regarde son rang en OOS : s'il
    n'est pas meilleur que la médiane des autres trials en OOS (logit <= 0),
    la sélection "in-sample" ne généralise pas — c'est du surapprentissage de
    backtest. PBO = proportion de combinaisons dans ce cas."""
    perf_matrix = np.asarray(perf_matrix, dtype=float)
    n_trials, n_blocks = perf_matrix.shape
    if n_blocks % 2 != 0:
        perf_matrix = perf_matrix[:, 1:]
        n_blocks -= 1
    if n_blocks < 2 or n_trials < 2:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": n_trials, "n_blocks": n_blocks,
                "mean_logit": np.nan}

    half = n_blocks // 2
    block_ids = list(range(n_blocks))
    logits = []
    for is_blocks in combinations(block_ids, half):
        oos_blocks = [b for b in block_ids if b not in is_blocks]
        is_perf = perf_matrix[:, list(is_blocks)].mean(axis=1)
        oos_perf = perf_matrix[:, oos_blocks].mean(axis=1)
        best_is_trial = int(np.argmax(is_perf))

        # Rang relatif (0,1) du trial "meilleur en IS" une fois évalué en OOS —
        # proportion des AUTRES trials qu'il bat en OOS.
        if n_trials > 1:
            rank = float((oos_perf < oos_perf[best_is_trial]).sum()) / (n_trials - 1)
        else:
            rank = 0.5
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(float(np.log(rank / (1 - rank))))

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr <= 0))
    return {
        "pbo": round(pbo, 4),
        "n_combinations": len(logits_arr),
        "n_trials": n_trials,
        "n_blocks": n_blocks,
        "mean_logit": round(float(np.mean(logits_arr)), 4),
    }
