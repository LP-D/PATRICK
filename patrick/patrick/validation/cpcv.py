"""Phase 6.1 (P6.1) -- CPCV (Combinatorial Purged Cross-Validation, López de
Prado ch. 12), as an ALTERNATIVE to the existing walk-forward
(`validation.scheme: walkforward | cpcv`), never as a replacement (explicit
constraint from the correction report).

Walk-forward has only ONE train/test boundary per fold (expanding window):
each test group is either the very first (nothing before it), or preceded
only by train. CPCV splits the history into `n_groups` contiguous groups and
tests on every combination of `k_test_groups` of them -- a test group can
therefore be "interior" (train on BOTH sides), which never happens in
walk-forward. Purging is therefore needed at both boundaries, not just one.

Defaults `n_groups=7`, `k_test_groups=2` -- CALCULATED, not chosen by
convention: the number of reconstructed backtest paths is `C(N,k)*k/N`
(combinatorial identity = `C(N-1,k-1)`). Guard C5
(`pbo_reliability.MIN_BLOCKS=6`, derived from the validity threshold for a
proportion `n*p>=5`/`n*(1-p)>=5`, worst case `n>=10` -> `C(6,3)=20>=10`)
refused to compute the PBO below 6 blocks -- that is the MAIN reason for
this component (see the P6.1 statement). `k=2` is the smallest useful
"combinatorial" k (k=1 degenerates into simply dropping blocks one at a
time, not a genuine combinatorics of paths); `N=7` is then the smallest
number of groups that gives `n_paths>=6`:
  - N=6, k=2: C(6,2)=15 combinations, n_paths=15*2/6=5 (insufficient, <6).
  - N=7, k=2: C(7,2)=21 combinations, n_paths=21*2/7=6 (exactly the threshold).
  - N=8, k=2: C(8,2)=28 combinations, n_paths=28*2/8=7 (sufficient but more
    compute than necessary: 28 splits versus 21).
`N=7, k=2` is therefore the minimal pair that makes the PBO satisfiable
(guard C5), with no superfluous combinatorial cost.
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
    """`C(n_groups, k_test_groups) * k_test_groups / n_groups` -- always an
    integer (combinatorial identity, equal to `C(n_groups-1, k_test_groups-1)`)."""
    if k_test_groups < 1 or k_test_groups >= n_groups:
        raise ValueError(f"k_test_groups must be in [1, n_groups-1], got {k_test_groups}")
    return comb(n_groups - 1, k_test_groups - 1)


def build_groups(n_bars: int, n_groups: int) -> list[tuple[int, int]]:
    """Splits `[0, n_bars)` into `n_groups` contiguous groups of as equal a
    size as possible (inclusive positions on both sides). Leftover groups
    (division remainder) get one extra bar, distributed at the front -- same
    logic as `np.array_split`, but explicit to stay readable in error
    messages/logs."""
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if n_bars < n_groups:
        raise ValueError(f"n_bars ({n_bars}) < n_groups ({n_groups}): history too short.")
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
    """All `C(n_groups, k_test_groups)` combinations of test groups, sorted
    lexicographically -- the order is significant for `path_assignment`
    (must be reproducible/deterministic)."""
    return list(combinations(range(n_groups), k_test_groups))


def path_assignment(n_groups: int, k_test_groups: int) -> dict[int, list[tuple[int, int]]]:
    """Backtest path reconstruction (López de Prado, snippet 12.4-12.5):
    `{path_index: [(group, combination_index), ...]}`, one pair per group
    (each path uses EXACTLY one evaluation of each group). For a group `g`,
    the combinations that contain it as test (there are
    `C(n_groups-1, k_test_groups-1) = n_paths` of them by construction) are
    assigned to paths 0..n_paths-1 in their lexicographic order --
    deterministic, reproducible assignment."""
    combos = all_combinations(n_groups, k_test_groups)
    phi = n_paths(n_groups, k_test_groups)
    paths: dict[int, list[tuple[int, int]]] = {p: [] for p in range(phi)}
    for g in range(n_groups):
        combo_indices_for_g = [ci for ci, c in enumerate(combos) if g in c]
        assert len(combo_indices_for_g) == phi, (
            f"internal inconsistency: group {g} appears in {len(combo_indices_for_g)} "
            f"combinations, expected {phi}."
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
    """Removes from `train_mask` any observation within `horizon` bars of
    EITHER boundary of each test group -- symmetric (unlike walk-forward,
    which has only one boundary):
    - BEFORE boundary (train precedes test): the label window (forward,
      `horizon` bars) of a train observation just before the test group can
      overlap the test group -- classic label leak (same mechanism as
      `validation/purge.py`, one boundary at a time).
    - AFTER boundary (test precedes train): symmetric, conservative
      protection against a train observation just after the test group
      whose feature window (lookback, up to `horizon` bars) could overlap
      the test group -- an INTERIOR test group (train on both sides)
      therefore has both boundaries purged, a test group at the edge of the
      history has only one (the other side has no train)."""
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
    """Removes from the TEST mask the first `embargo_bars` bars of each test
    group whose BEFORE boundary touches a train group (same motivation as
    `validation/embargo.py`: rolling-window features computed just after
    the cut are still correlated with train). A test group whose preceding
    neighbor is ITSELF a test group (two adjacent test groups in the same
    combination) does not need embargo at that boundary -- no train right
    before it."""
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
    """A split = one (train_mask, test_mask) pair for ONE combination of
    test groups. `embargo_bars`: defaults to `horizon` (same convention as
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
    """CPCV performance reported as a DISTRIBUTION over paths (median, 5/95
    quantiles, std dev) -- never a single point, see the P6.1 correction
    report. `path_values`: {path_index: metric aggregated over that path
    (e.g. mean F1_dir over its n_groups evaluations)}."""
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
