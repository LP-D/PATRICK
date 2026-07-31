"""Phase 6.1 (P6.1) -- CPCV (Combinatorial Purged Cross-Validation, López de
Prado ch. 12), en ALTERNATIVE au walk-forward existant (`validation.scheme:
walkforward | cpcv`), jamais en remplacement (contrainte explicite du rapport
de correction).

Le walk-forward n'a qu'UNE seule frontière train/test par fold (expansive
window) : chaque groupe de test est soit le tout premier (rien avant), soit
précédé uniquement de train. CPCV répartit l'historique en `n_groups` groupes
contigus et teste sur toutes les combinaisons de `k_test_groups` d'entre eux
-- un groupe de test peut donc être "intérieur" (train des DEUX côtés), ce
qui n'existe jamais en walk-forward. Il faut donc purger aux deux frontières,
pas une seule.

Défauts `n_groups=7`, `k_test_groups=2` -- CALCULÉS, pas choisis par
convention : le nombre de chemins de backtest reconstruits est
`C(N,k)*k/N` (identité combinatoire = `C(N-1,k-1)`). La garde-fou C5
(`pbo_reliability.MIN_BLOCKS=6`, dérivée du seuil de validité d'une
proportion `n*p>=5`/`n*(1-p)>=5`, pire cas `n>=10` -> `C(6,3)=20>=10`)
refusait le calcul du PBO en dessous de 6 blocs -- c'est la raison PRINCIPALE
de cette brique (cf. énoncé P6.1). `k=2` est le plus petit k
"combinatoire" utile (k=1 dégénère en un simple retrait successif de blocs,
pas une vraie combinatoire de chemins) ; `N=7` est alors le plus petit
nombre de groupes qui donne `n_paths>=6` :
  - N=6, k=2 : C(6,2)=15 combinaisons, n_paths=15*2/6=5 (insuffisant, <6).
  - N=7, k=2 : C(7,2)=21 combinaisons, n_paths=21*2/7=6 (exactement le seuil).
  - N=8, k=2 : C(8,2)=28 combinaisons, n_paths=28*2/8=7 (suffisant mais plus
    cher en calcul que nécessaire : 28 splits contre 21).
`N=7, k=2` est donc le couple minimal qui rend le PBO satisfiable (garde-fou
C5), sans calcul combinatoire superflu.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb

import numpy as np
import pandas as pd

DEFAULT_N_GROUPS = 7
DEFAULT_K_TEST_GROUPS = 2


def n_paths(n_groups: int, k_test_groups: int) -> int:
    """`C(n_groups, k_test_groups) * k_test_groups / n_groups` -- toujours un
    entier (identité combinatoire, égal à `C(n_groups-1, k_test_groups-1)`)."""
    if k_test_groups < 1 or k_test_groups >= n_groups:
        raise ValueError(f"k_test_groups doit être dans [1, n_groups-1], reçu {k_test_groups}")
    return comb(n_groups - 1, k_test_groups - 1)


def build_groups(n_bars: int, n_groups: int) -> list[tuple[int, int]]:
    """Découpe `[0, n_bars)` en `n_groups` groupes contigus de taille aussi
    égale que possible (positions inclusives des deux côtés). Les groupes en
    trop (reste de la division) reçoivent une barre de plus, répartis en tête
    -- même logique que `np.array_split`, mais explicite pour rester lisible
    dans les messages d'erreur/logs."""
    if n_groups < 2:
        raise ValueError(f"n_groups doit être >= 2, reçu {n_groups}")
    if n_bars < n_groups:
        raise ValueError(f"n_bars ({n_bars}) < n_groups ({n_groups}) : historique trop court.")
    base = n_bars // n_groups
    remainder = n_bars % n_groups
    groups = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < remainder else 0)
        end = start + size - 1
        groups.append((start, end))
        start = end + 1
    return groups


def all_combinations(n_groups: int, k_test_groups: int) -> list[tuple[int, ...]]:
    """Toutes les `C(n_groups, k_test_groups)` combinaisons de groupes de
    test, triées lexicographiquement -- l'ordre est significatif pour
    `path_assignment` (doit être reproductible/déterministe)."""
    return list(combinations(range(n_groups), k_test_groups))


def path_assignment(n_groups: int, k_test_groups: int) -> dict[int, list[tuple[int, int]]]:
    """Reconstruction des chemins de backtest (López de Prado, snippet 12.4-
    12.5) : `{path_index: [(group, combination_index), ...]}`, un couple par
    groupe (chaque chemin utilise EXACTEMENT une évaluation de chaque
    groupe). Pour un groupe `g`, les combinaisons qui le contiennent comme
    test (il y en a `C(n_groups-1, k_test_groups-1) = n_paths` par
    construction) sont assignées aux chemins 0..n_paths-1 dans leur ordre
    lexicographique -- assignation déterministe, reproductible."""
    combos = all_combinations(n_groups, k_test_groups)
    phi = n_paths(n_groups, k_test_groups)
    paths: dict[int, list[tuple[int, int]]] = {p: [] for p in range(phi)}
    for g in range(n_groups):
        combo_indices_for_g = [ci for ci, c in enumerate(combos) if g in c]
        assert len(combo_indices_for_g) == phi, (
            f"incohérence interne : groupe {g} apparaît dans {len(combo_indices_for_g)} "
            f"combinaisons, {phi} attendues."
        )
        for p, ci in enumerate(combo_indices_for_g):
            paths[p].append((g, ci))
    return paths


@dataclass
class CPCVSplit:
    combo_index: int
    test_groups: tuple[int, ...]
    train_mask: np.ndarray
    test_mask: np.ndarray


def _purge_around_test_groups(train_mask: np.ndarray, groups: list[tuple[int, int]],
                               test_group_indices: tuple[int, ...], horizon: int) -> np.ndarray:
    """Retire de `train_mask` toute observation à moins de `horizon` barres
    d'UNE OU L'AUTRE frontière de chaque groupe de test -- symétrique
    (contrairement au walk-forward, qui n'a qu'une frontière) :
    - frontière AVANT (train precede test) : la fenêtre de label (forward,
      `horizon` barres) d'une observation de train juste avant le groupe de
      test peut recouvrir le groupe de test -- fuite de label classique
      (même mécanisme que `validation/purge.py`, une frontière à la fois).
    - frontière APRÈS (test precede train) : symétrique, protection
      conservative contre une observation de train juste après le groupe de
      test dont la fenêtre de feature (lookback, jusqu'à `horizon` barres)
      pourrait recouvrir le groupe de test -- un groupe de test INTÉRIEUR
      (train des deux côtés) a donc les deux frontières purgées, un groupe
      de test en bord d'historique n'en a qu'une (l'autre n'a pas de train)."""
    out = train_mask.copy()
    n_bars = len(train_mask)
    for gi in test_group_indices:
        start, end = groups[gi]
        lo = max(start - horizon, 0)
        hi = min(end + horizon, n_bars - 1)
        out[lo:hi + 1] = False
    return out


def _embargo_after_test_groups(mask: np.ndarray, groups: list[tuple[int, int]],
                                test_group_indices: tuple[int, ...], embargo_bars: int) -> np.ndarray:
    """Retire du masque de TEST les `embargo_bars` premières barres de chaque
    groupe de test dont la frontière AVANT touche un groupe de train (même
    motivation que `validation/embargo.py` : features à fenêtre glissante
    calculées juste après la coupure encore corrélées avec le train). Un
    groupe de test dont le voisin précédent est LUI-MÊME un groupe de test
    (deux groupes de test adjacents dans la même combinaison) n'a pas besoin
    d'embargo à cette frontière -- pas de train juste avant."""
    if embargo_bars <= 0:
        return mask
    out = mask.copy()
    test_set = set(test_group_indices)
    for gi in test_group_indices:
        start, _ = groups[gi]
        preceded_by_train = (gi - 1) not in test_set and gi > 0
        if preceded_by_train:
            hi = min(start + embargo_bars - 1, len(mask) - 1)
            out[start:hi + 1] = False
    return out


def build_split(groups: list[tuple[int, int]], combo: tuple[int, ...],
                 horizon: int, embargo_bars: int | None = None) -> CPCVSplit:
    """Un split = un jeu (train_mask, test_mask) pour UNE combinaison de
    groupes de test. `embargo_bars` : défaut `horizon` (même convention que
    `ValidationConfig.embargo_bars=None`, walk-forward)."""
    n_bars = groups[-1][1] + 1
    embargo_bars = horizon if embargo_bars is None else embargo_bars
    combo_index = all_combinations(len(groups), len(combo)).index(combo)

    test_mask = np.zeros(n_bars, dtype=bool)
    for gi in combo:
        start, end = groups[gi]
        test_mask[start:end + 1] = True

    train_mask = ~test_mask
    train_mask = _purge_around_test_groups(train_mask, groups, combo, horizon)
    test_mask = _embargo_after_test_groups(test_mask, groups, combo, embargo_bars)

    return CPCVSplit(combo_index=combo_index, test_groups=combo,
                      train_mask=train_mask, test_mask=test_mask)


def all_splits(n_bars: int, n_groups: int, k_test_groups: int,
                horizon: int, embargo_bars: int | None = None) -> list[CPCVSplit]:
    groups = build_groups(n_bars, n_groups)
    return [build_split(groups, combo, horizon, embargo_bars)
            for combo in all_combinations(n_groups, k_test_groups)]


def path_performance_distribution(path_values: dict[int, float]) -> dict:
    """Performance CPCV rapportée comme une DISTRIBUTION sur les chemins
    (médiane, quantiles 5/95, écart-type) -- jamais un point unique, cf.
    rapport de correction P6.1. `path_values` : {path_index: métrique
    agrégée sur ce chemin (ex. F1_dir moyen sur ses n_groups évaluations)}."""
    values = np.array(list(path_values.values()), dtype=float)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        return {"median": float("nan"), "q05": float("nan"), "q95": float("nan"),
                "std": float("nan"), "n_paths": 0}
    return {
        "median": float(np.median(values)),
        "q05": float(np.percentile(values, 5)),
        "q95": float(np.percentile(values, 95)),
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "n_paths": len(values),
    }
