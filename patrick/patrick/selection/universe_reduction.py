"""Candidate-universe reduction ahead of training: hierarchical clustering on
the correlation distance `1 - |corr|`, one representative kept per cluster.

Point-in-time by construction: the correlation matrix is the one already
shared with HRP/Black-Litterman (`tracking/covariance.py::
point_in_time_covariance` + `correlation_from_covariance`), computed at an
`as_of` date chosen by the caller -- `pipeline/engine.py` passes the END of
the first walk-forward training window, so neither any test fold nor the
terminal holdout ever influences which series enter the universe. No
full-history correlation is ever computed here.

Off by default (`UniverseConfig.reduction_corr_threshold = None`): this is
an exploration platform, never a silent filter. When enabled, every dropped
series is logged with the cluster representative that replaced it, and an
explicit warning is emitted if the setting is aggressive (see
`AGGRESSIVE_CORR_THRESHOLD` / `AGGRESSIVE_DROP_FRAC`).

Algorithm (decision recorded in the chantier report): scipy `linkage`,
method="average" (UPGMA) on the condensed `1 - |corr|` distance, cut with
`fcluster(criterion="distance", t=1 - corr_threshold)` -- two series end up
in the same cluster iff the AVERAGE |corr| linking their groups is >=
`corr_threshold`. Average (not single) linkage avoids the chaining effect
where A~B and B~C merge A and C despite A and C being unrelated.
Representative of a cluster: the member with the most valid observations
up to `as_of` (ties broken alphabetically) -- a point-in-time criterion.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from patrick.tracking.covariance import correlation_from_covariance, point_in_time_covariance

logger = logging.getLogger(__name__)

# Below this |corr| threshold, clusters start merging series that are only
# moderately related -- flagged, never refused.
AGGRESSIVE_CORR_THRESHOLD = 0.80
# Dropping more than this share of the eligible candidates is flagged too.
AGGRESSIVE_DROP_FRAC = 0.50


class AggressiveReductionWarning(UserWarning):
    pass


@dataclass
class ReductionResult:
    kept: list[str]
    dropped: dict[str, str] = field(default_factory=dict)  # dropped series -> representative
    clusters: dict[str, int] = field(default_factory=dict)
    as_of: pd.Timestamp | None = None
    not_eligible: list[str] = field(default_factory=list)  # too little history at as_of: kept as-is


def correlation_clusters(prices: dict[str, pd.Series], as_of, corr_threshold: float,
                         lookback: int = 252, min_obs: int = 60) -> dict[str, int]:
    """Cluster label per series, from the point-in-time correlation at `as_of`."""
    cov = point_in_time_covariance(prices, as_of=as_of, lookback=lookback, min_obs=min_obs)
    corr = correlation_from_covariance(cov).fillna(0.0)  # zero-variance series: distance 1, never merged
    dist = (1.0 - corr.abs()).clip(lower=0.0)
    arr = dist.values.copy()
    np.fill_diagonal(arr, 0.0)
    arr = (arr + arr.T) / 2.0
    if len(arr) < 2:
        return {s: 1 for s in cov.index}
    link = linkage(squareform(arr, checks=False), method="average")
    labels = fcluster(link, t=1.0 - corr_threshold, criterion="distance")
    return {sym: int(lab) for sym, lab in zip(cov.index, labels)}


def reduce_universe(prices: dict[str, pd.Series], as_of, corr_threshold: float,
                    lookback: int = 252, min_obs: int = 60) -> ReductionResult:
    if not 0.0 < corr_threshold <= 1.0:
        raise ValueError(f"corr_threshold must be in (0, 1], got {corr_threshold}")
    as_of = pd.Timestamp(as_of)

    eligible: dict[str, pd.Series] = {}
    not_eligible: list[str] = []
    for sym, s in prices.items():
        window = s[s.index <= as_of].iloc[-(lookback + 1):]
        if len(window) >= min_obs + 1 and window.notna().all():
            eligible[sym] = s
        else:
            not_eligible.append(sym)

    if len(eligible) < 2:
        return ReductionResult(kept=list(prices), as_of=as_of, not_eligible=not_eligible)

    try:
        clusters = correlation_clusters(eligible, as_of, corr_threshold, lookback, min_obs)
    except ValueError as exc:  # too few common dates at as_of: reduce nothing, say so
        print(f"  [WARN] universe reduction skipped (universe unchanged): {exc}")
        return ReductionResult(kept=list(prices), as_of=as_of, not_eligible=not_eligible)
    n_valid = {sym: int(s[s.index <= as_of].notna().sum()) for sym, s in eligible.items()}
    representative: dict[int, str] = {}
    for sym in sorted(eligible, key=lambda x: (-n_valid[x], x)):
        representative.setdefault(clusters[sym], sym)

    dropped = {sym: representative[clusters[sym]] for sym in eligible
               if representative[clusters[sym]] != sym}
    kept = [sym for sym in prices if sym not in dropped]

    drop_frac = len(dropped) / len(eligible)
    if corr_threshold < AGGRESSIVE_CORR_THRESHOLD or drop_frac > AGGRESSIVE_DROP_FRAC:
        warnings.warn(
            f"Aggressive universe reduction: corr_threshold={corr_threshold} "
            f"(flagged below {AGGRESSIVE_CORR_THRESHOLD}), {len(dropped)}/{len(eligible)} "
            f"eligible series dropped ({drop_frac:.0%}).", AggressiveReductionWarning, stacklevel=2)
    return ReductionResult(kept=kept, dropped=dropped, clusters=clusters, as_of=as_of,
                           not_eligible=not_eligible)


def reduction_as_of(index: pd.DatetimeIndex, min_train_frac: float, holdout_start_idx: int | None = None) -> pd.Timestamp:
    """End of the first walk-forward training window (same arithmetic as
    `validation/walkforward.py::build_fold_cuts`, applied to the
    pre-holdout span): the latest date no test fold / holdout ever precedes."""
    n = len(index) if holdout_start_idx is None else holdout_start_idx
    first_cut = max(int(n * min_train_frac), 1)
    return index[first_cut - 1]


def apply_to_raw(raw: pd.DataFrame, target_col: str, as_of, corr_threshold: float,
                 lookback: int = 252, min_obs: int = 60) -> tuple[pd.DataFrame, ReductionResult]:
    """Reduces the candidate columns of the aligned raw frame (the target
    column is never a candidate, never dropped). `raw.attrs` (snapshot
    context) is preserved."""
    candidates = {c: raw[c] for c in raw.columns if c != target_col}
    result = reduce_universe(candidates, as_of, corr_threshold, lookback, min_obs)
    out = raw.drop(columns=list(result.dropped))
    out.attrs = dict(raw.attrs)
    for sym, rep in sorted(result.dropped.items()):
        logger.info("universe reduction: %s dropped (cluster represented by %s)", sym, rep)
    print(f"[UNIVERSE] correlation clustering at {result.as_of.date()} (|corr|>={corr_threshold}): "
          f"{len(candidates) - len(result.dropped)}/{len(candidates)} candidate series kept"
          + (f", {len(result.not_eligible)} too short at as_of kept as-is" if result.not_eligible else ""))
    return out, result
