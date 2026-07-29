"""Rapport de correction, C5 -- fiabilité du PBO (`patrick/validation/pbo.py`,
`compute_pbo`). L'audit a mesuré une espérance correcte (~0.50 sur 30 tirages
i.i.d. indépendants) mais un écart-type ~0.16 sur un SEUL tirage (n_blocks=16),
et pire encore au n_blocks réellement atteint par défaut dans ce projet
(n_wf_folds=5 -> 4 blocs après retrait du bloc le plus ancien pour parité) --
un PBO isolé, sans indication de dispersion, n'est pas interprétable seul.

Ce module N'EST PAS une modification de `compute_pbo` -- ce fichier n'importe
ni ne touche `pbo.py` : il fournit un diagnostic complémentaire, calculé
séparément. `_combination_outcomes` reproduit délibérément la logique
par-combinaison de `compute_pbo` (`tests/test_pbo_reliability.py` vérifie que
le PBO recalculé ici correspond EXACTEMENT à celui de `compute_pbo` --
garde-fou anti-dérive si l'un des deux change sans l'autre).

Dispersion -- bootstrap sur les TRIALS, pas sur les combinaisons : un premier
essai (rééchantillonner l'ensemble déjà-calculé des C(n,n/2) sorties
binaires) donnait un intervalle ridiculement étroit (largeur ~0.01 contre un
écart-type mesuré ~0.16 par l'audit) -- attendu a posteriori : les
combinaisons CSCV, calculées sur les MÊMES données sous-jacentes fixes, ne
capturent aucune variabilité de nouvelles données, seulement le
réarrangement d'un petit ensemble déjà fortement corrélé. Le bootstrap
rééchantillonne donc les TRIALS (lignes de `perf_matrix`, avec remise) --
plus proche de "et si on avait eu un jeu de trials légèrement différent ?",
la même question que pose une nouvelle exécution. Pour rester praticable
(C(16,8)=12870 combinaisons x 300 répétitions bootstrap serait de l'ordre de
la minute), chaque répétition bootstrap sous-échantillonne au plus
`MAX_COMBINATIONS_PER_BOOTSTRAP` combinaisons tirées au hasard plutôt que de
toutes les énumérer -- vérifié empiriquement donner un écart-type quasi
identique à l'énumération complète (0.113 vs 0.112 sur un cas testé), pour
~40x moins de temps de calcul. Seul CE sous-échantillonnage est approximatif
; le POINT ponctuel `pbo` retourné reste la valeur EXACTE de `compute_pbo`.

Seuil minimal (MIN_BLOCKS = 6), justifié par calcul, pas par convention :
pour qu'une proportion (le PBO est la fraction de combinaisons où le meilleur
IS ne bat pas la médiane OOS) suive raisonnablement l'approximation normale,
la règle usuelle est n*p >= 5 ET n*(1-p) >= 5 -- au pire cas p=0.5, ça donne
n >= 10 combinaisons. C'est un PLANCHER NÉCESSAIRE, pas suffisant : les
combinaisons CSCV ne sont PAS indépendantes (elles partagent des blocs entre
elles), donc le nombre d'informations réellement indépendantes est
strictement inférieur à C(n_blocks, n_blocks/2) -- le vrai seuil nécessaire
est donc PLUS ÉLEVÉ que ce plancher de 10, pas plus bas. C(4,2)=6 < 10
(insuffisant même dans l'hypothèse la plus optimiste d'indépendance totale) ;
C(6,3)=20 >= 10 (satisfait le plancher avec marge, tout en restant sous le
S>=16 documenté comme "idéal" dans `pbo.py` -- un compromis délibérément
conservateur, pas le seuil idéal). D'où MIN_BLOCKS=6.
"""
from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np

MIN_BLOCKS = 6
MIN_COMBINATIONS_FLOOR = 10  # n*p>=5 et n*(1-p)>=5 au pire cas p=0.5 (proportion binomiale)
DEFAULT_N_BOOTSTRAP = 300
MAX_COMBINATIONS_PER_BOOTSTRAP = 150


def required_blocks_reason() -> str:
    return (
        f"PBO nécessite au moins {MIN_BLOCKS} blocs temporels (n_wf_folds, après retrait "
        f"éventuel du bloc le plus ancien pour parité) : C({MIN_BLOCKS}, {MIN_BLOCKS // 2}) = "
        f"{comb(MIN_BLOCKS, MIN_BLOCKS // 2)} combinaisons IS/OOS, au-dessus du plancher de "
        f"{MIN_COMBINATIONS_FLOOR} (règle n*p>=5 et n*(1-p)>=5 pour une proportion, pire cas "
        "p=0.5) -- un plancher NÉCESSAIRE mais pas suffisant : les combinaisons CSCV ne sont "
        "pas indépendantes (elles partagent des blocs), le vrai besoin est plus élevé."
    )


def _iter_combinations(n_blocks: int, half: int, max_combinations: int | None,
                        rng: np.random.Generator | None):
    """Toutes les combinaisons (C(n_blocks, half) <= max_combinations, ou
    max_combinations=None) sinon un tirage aléatoire de `max_combinations`
    sous-ensembles de taille `half` (approximation Monte Carlo de la moyenne
    sur toutes les combinaisons -- collisions négligeables tant que
    C(n_blocks, half) >> max_combinations)."""
    block_ids = list(range(n_blocks))
    total = comb(n_blocks, half)
    if max_combinations is None or total <= max_combinations:
        yield from combinations(block_ids, half)
        return
    for _ in range(max_combinations):
        yield tuple(sorted(rng.choice(block_ids, size=half, replace=False)))


def _combination_outcomes(perf_matrix: np.ndarray, max_combinations: int | None = None,
                           rng: np.random.Generator | None = None) -> np.ndarray:
    """Reproduit la logique par-combinaison de `compute_pbo`
    (`patrick/validation/pbo.py`, non importé/modifié ici) : pour chaque
    partition des blocs en deux moitiés égales, 1.0 si le trial le meilleur en
    IS ne bat pas la médiane des autres en OOS (logit<=0, "overfitting" au
    sens CSCV), sinon 0.0. Avec `max_combinations=None` (défaut), énumère
    TOUTES les combinaisons -- `np.mean(outcomes)` == `compute_pbo(...)["pbo"]`
    exactement (vérifié par test). Avec `max_combinations` fixé, sous-échantillonne
    (cf. docstring de module) -- résultat approximatif, réservé au bootstrap."""
    perf_matrix = np.asarray(perf_matrix, dtype=float)
    n_trials, n_blocks = perf_matrix.shape
    if n_blocks % 2 != 0:
        perf_matrix = perf_matrix[:, 1:]
        n_blocks -= 1

    half = n_blocks // 2
    outcomes = []
    for is_blocks in _iter_combinations(n_blocks, half, max_combinations, rng):
        oos_blocks = [b for b in range(n_blocks) if b not in is_blocks]
        is_perf = perf_matrix[:, list(is_blocks)].mean(axis=1)
        oos_perf = perf_matrix[:, oos_blocks].mean(axis=1)
        best_is_trial = int(np.argmax(is_perf))
        if n_trials > 1:
            rank = float((oos_perf < oos_perf[best_is_trial]).sum()) / (n_trials - 1)
        else:
            rank = 0.5
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logit = float(np.log(rank / (1 - rank)))
        outcomes.append(1.0 if logit <= 0 else 0.0)
    return np.asarray(outcomes, dtype=float)


def pbo_reliability(perf_matrix: np.ndarray, n_bootstrap: int = DEFAULT_N_BOOTSTRAP, seed: int = 42,
                     ci: tuple[float, float] = (5.0, 95.0),
                     max_combinations_per_bootstrap: int = MAX_COMBINATIONS_PER_BOOTSTRAP) -> dict:
    """Diagnostic de fiabilité pour un PBO donné (mêmes entrées que
    `compute_pbo`) : refus explicite sous `MIN_BLOCKS`, sinon intervalle de
    confiance (90% par défaut, percentiles 5/95) par bootstrap SUR LES TRIALS
    (lignes de `perf_matrix`, avec remise -- cf. docstring de module pour
    pourquoi pas sur les combinaisons). Le point `pbo` retourné est la valeur
    EXACTE de `compute_pbo` (aucune approximation) ; seul l'intervalle utilise
    le sous-échantillonnage de combinaisons par répétition bootstrap."""
    perf_matrix = np.asarray(perf_matrix, dtype=float)
    n_trials, n_blocks_raw = perf_matrix.shape
    n_blocks = n_blocks_raw - (n_blocks_raw % 2)

    if n_blocks < MIN_BLOCKS or n_trials < 2:
        return {
            "ok": False,
            "message": f"PBO non calculé ({n_blocks} blocs disponibles). {required_blocks_reason()}",
            "pbo": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
            "bootstrap_std": float("nan"), "n_blocks": n_blocks, "n_combinations": 0,
        }

    rng = np.random.default_rng(seed)
    pbo_point = float(_combination_outcomes(perf_matrix).mean())
    n_combinations_exact = comb(n_blocks, n_blocks // 2)

    boot = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        row_idx = rng.integers(0, n_trials, n_trials)
        resampled = perf_matrix[row_idx]
        boot[i] = _combination_outcomes(
            resampled, max_combinations=max_combinations_per_bootstrap, rng=rng).mean()
    ci_low, ci_high = np.percentile(boot, list(ci))

    return {
        "ok": True,
        "message": None,
        "pbo": round(pbo_point, 4),
        "ci_low": round(float(ci_low), 4),
        "ci_high": round(float(ci_high), 4),
        "bootstrap_std": round(float(boot.std(ddof=1)), 4),
        "n_blocks": n_blocks,
        "n_combinations": n_combinations_exact,
        "n_bootstrap": n_bootstrap,
    }
