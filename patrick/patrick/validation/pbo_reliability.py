"""Correction report, C5 -- PBO reliability (`patrick/validation/pbo.py`,
`compute_pbo`). The audit measured a correct expectation (~0.50 over 30
independent i.i.d. draws) but a std dev of ~0.16 on a SINGLE draw
(n_blocks=16), and worse still at the n_blocks actually reached by default
in this project (n_wf_folds=5 -> 4 blocks after dropping the oldest block
for parity) -- an isolated PBO, with no dispersion indication, is not
interpretable on its own.

This module is NOT a modification of `compute_pbo` -- this file neither
imports nor touches `pbo.py`: it provides a complementary diagnostic,
computed separately. `_combination_outcomes` deliberately reproduces
`compute_pbo`'s per-combination logic (`tests/test_pbo_reliability.py`
verifies that the PBO recomputed here matches `compute_pbo`'s EXACTLY --
an anti-drift guard in case one changes without the other).

Dispersion -- bootstrap over TRIALS, not over combinations: a first attempt
(resampling the already-computed set of C(n,n/2) binary outcomes) gave a
ridiculously narrow interval (width ~0.01 against a std dev of ~0.16 measured
by the audit) -- expected in hindsight: CSCV combinations, computed on the
SAME fixed underlying data, capture no variability from new data, only the
rearrangement of a small, already strongly-correlated set. The bootstrap
therefore resamples TRIALS (rows of `perf_matrix`, with replacement) --
closer to "what if we'd had a slightly different set of trials?", the same
question a new run poses. To stay practical (C(16,8)=12870 combinations x
300 bootstrap repetitions would take on the order of a minute), each
bootstrap repetition subsamples at most `MAX_COMBINATIONS_PER_BOOTSTRAP`
randomly-drawn combinations rather than enumerating them all -- empirically
verified to give a std dev nearly identical to full enumeration (0.113 vs
0.112 on a tested case), for ~40x less compute time. Only THIS subsampling
is approximate; the point estimate `pbo` returned remains the EXACT value
from `compute_pbo`.

Minimum threshold (MIN_BLOCKS = 6), justified by calculation, not
convention: for a proportion (PBO is the fraction of combinations where the
best IS trial does not beat the OOS median) to reasonably follow the normal
approximation, the usual rule is n*p >= 5 AND n*(1-p) >= 5 -- worst case
p=0.5, that gives n >= 10 combinations. This is a NECESSARY floor, not a
sufficient one: CSCV combinations are NOT independent (they share blocks
with each other), so the number of genuinely independent pieces of
information is strictly lower than C(n_blocks, n_blocks/2) -- the true
required threshold is therefore HIGHER than this floor of 10, not lower.
C(4,2)=6 < 10 (insufficient even under the most optimistic assumption of
total independence); C(6,3)=20 >= 10 (satisfies the floor with margin,
while staying below the S>=16 documented as "ideal" in `pbo.py` -- a
deliberately conservative compromise, not the ideal threshold). Hence
MIN_BLOCKS=6.
"""
from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np

MIN_BLOCKS = 6
MIN_COMBINATIONS_FLOOR = 10  # n*p>=5 and n*(1-p)>=5 worst case p=0.5 (binomial proportion)
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
    """All combinations (C(n_blocks, half) <= max_combinations, or
    max_combinations=None), otherwise a random draw of `max_combinations`
    subsets of size `half` (Monte Carlo approximation of the average over
    all combinations -- collisions negligible as long as
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
    """Reproduces `compute_pbo`'s per-combination logic
    (`patrick/validation/pbo.py`, not imported/modified here): for each
    partition of blocks into two equal halves, 1.0 if the best trial in IS
    does not beat the median of the others in OOS (logit<=0, "overfitting"
    in the CSCV sense), else 0.0. With `max_combinations=None` (default),
    enumerates ALL combinations -- `np.mean(outcomes)` == `compute_pbo(...)["pbo"]`
    exactly (verified by test). With `max_combinations` set, subsamples (see
    module docstring) -- approximate result, reserved for the bootstrap."""
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
    """Reliability diagnostic for a given PBO (same inputs as `compute_pbo`):
    explicit refusal below `MIN_BLOCKS`, otherwise a confidence interval (90%
    by default, 5/95 percentiles) via bootstrap OVER TRIALS (rows of
    `perf_matrix`, with replacement -- see module docstring for why not over
    combinations). The `pbo` point returned is the EXACT value from
    `compute_pbo` (no approximation); only the interval uses combination
    subsampling per bootstrap repetition."""
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
