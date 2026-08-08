"""Phase 6.3 (P6.3) -- feature selection stability across folds
(walk-forward today, CPCV paths tomorrow -- P6.1): a selection that changes
almost entirely from one fold to the next does not signal a model adapting
to the regime, but an unstable selection procedure -- the identified signal
is only as reproducible as the retained features are.

`MIN_MEAN_JACCARD_WARNING = 0.40` -- MEASURED, not chosen by convention (see
`tests/test_feature_stability.py::test_warning_threshold_is_measured_not_arbitrary`
for the reproducible measurement): on synthetic data with NO real link
between X and y (pure-noise target, features correlated with each other the
way the real pipeline's technical/interactions families are), the REAL SHAP
selection (`patrick/selection/shap_select.py`, not a naive combinatorial
formula) already produces a mean Jaccard of UP TO ~0.40 between folds from
feature correlation structure alone -- not from a genuine recurring signal.
Below this threshold, observed stability is indistinguishable from that
artifact; it is NOT proof that the identified signal is reproducible. A
naive combinatorial formula (two independent random subsets of a pool of
size P) would give a chance Jaccard ~100x lower (~0.01 for N=8/P=450) --
grossly underestimated because it ignores that correlated features are
chosen TOGETHER, not independently, by an importance-based selector."""
from __future__ import annotations

from itertools import combinations

MIN_MEAN_JACCARD_WARNING = 0.40


def jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def feature_selection_stability(fold_feature_sets: dict[int, list[str]]) -> dict:
    """`fold_feature_sets`: {fold_index: [names of retained features]}, a
    fold can be a walk-forward fold or (P6.1, upcoming) a CPCV path.

    Returns: `mean_jaccard` (average of pairwise fold Jaccards -- NaN if
    fewer than 2 folds, stability isn't definable on a single fold),
    `pairwise_jaccard` (list, for audit), `selection_freq` ({feature:
    fraction of folds where it is retained}), `n_folds`, `warning` (explicit
    message if `mean_jaccard < MIN_MEAN_JACCARD_WARNING`, else `None`)."""
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
            f"Mean Jaccard ({mean_jaccard:.3f}) below the threshold ({MIN_MEAN_JACCARD_WARNING}) -- "
            "feature selection changes substantially from one fold to the next, indistinguishable "
            "from the correlation artifact measured on data with no real signal (see the P6.3 "
            "correction report). The signal identified by this run is not shown to be reproducible."
        )

    return {"mean_jaccard": mean_jaccard, "pairwise_jaccard": pairwise,
            "selection_freq": selection_freq, "n_folds": n_folds, "warning": warning}
