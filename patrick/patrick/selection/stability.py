"""Phase 6.3 (P6.3) -- stabilité de la sélection de features à travers les
folds (walk-forward aujourd'hui, chemins CPCV demain -- P6.1) : une sélection
qui change presque entièrement d'un fold à l'autre ne signale pas un modèle
qui s'adapte au régime, mais une procédure de sélection instable -- le signal
identifié n'est reproductible qu'à la mesure où les features retenues le sont.

`MIN_MEAN_JACCARD_WARNING = 0.40` -- MESURÉ, pas choisi par convention (cf.
`tests/test_feature_stability.py::test_warning_threshold_is_measured_not_arbitrary`
pour la mesure reproductible) : sur des données synthétiques SANS lien réel
entre X et y (cible pur bruit, features corrélées entre elles comme le sont
les familles technical/interactions du pipeline réel), la sélection SHAP
RÉELLE (`patrick/selection/shap_select.py`, pas une formule combinatoire
naïve) produit déjà un Jaccard moyen JUSQU'À ~0.40 entre folds par la seule
structure de corrélation des features -- pas par un vrai signal récurrent.
En dessous de ce seuil, une stabilité observée est indiscernable de cet
artefact ; ce n'est PAS la preuve que le signal identifié est reproductible.
Une formule combinatoire naïve (deux sous-ensembles aléatoires indépendants
d'un pool de taille P) donnerait un Jaccard de hasard ~100x plus bas (~0.01
pour N=8/P=450) -- largement sous-estimé car elle ignore que des features
corrélées sont choisies ENSEMBLE, pas indépendamment, par un sélecteur basé
sur l'importance."""
from __future__ import annotations

from itertools import combinations

MIN_MEAN_JACCARD_WARNING = 0.40


def jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def feature_selection_stability(fold_feature_sets: dict[int, list[str]]) -> dict:
    """`fold_feature_sets` : {fold_index: [noms de features retenues]}, un
    fold peut être un fold walk-forward ou (P6.1, à venir) un chemin CPCV.

    Renvoie : `mean_jaccard` (moyenne des Jaccard par paire de folds -- NaN si
    moins de 2 folds, la stabilité n'est pas définissable sur un seul fold),
    `pairwise_jaccard` (liste, pour audit), `selection_freq` ({feature:
    fraction des folds où elle est retenue}), `n_folds`, `warning` (message
    explicite si `mean_jaccard < MIN_MEAN_JACCARD_WARNING`, sinon `None`)."""
    n_folds = len(fold_feature_sets)
    sets = {k: set(v) for k, v in fold_feature_sets.items()}

    if n_folds < 2:
        return {"mean_jaccard": float("nan"), "pairwise_jaccard": [], "selection_freq": {},
                "n_folds": n_folds, "warning": None}

    pairwise = [jaccard(sets[i], sets[j]) for i, j in combinations(sets.keys(), 2)]
    mean_jaccard = sum(pairwise) / len(pairwise)

    freq_count: dict[str, int] = {}
    for feats in sets.values():
        for f in feats:
            freq_count[f] = freq_count.get(f, 0) + 1
    selection_freq = {f: c / n_folds for f, c in freq_count.items()}

    warning = None
    if mean_jaccard < MIN_MEAN_JACCARD_WARNING:
        warning = (
            f"Jaccard moyen ({mean_jaccard:.3f}) sous le seuil ({MIN_MEAN_JACCARD_WARNING}) -- "
            "la sélection de features change substantiellement d'un fold à l'autre, indiscernable "
            "de l'artefact de corrélation mesuré sur données sans signal réel (cf. rapport de "
            "correction P6.3). Le signal identifié par ce run n'est pas démontré reproductible."
        )

    return {"mean_jaccard": mean_jaccard, "pairwise_jaccard": pairwise,
            "selection_freq": selection_freq, "n_folds": n_folds, "warning": warning}
