"""Candidate-universe reduction by correlation clustering, decided INSIDE
each validation fold from that fold's training bars only.

Ported from feature/replay-cache-universe (3174010) and changed on one
point: the branch reduced the universe ONCE, before training, at the end of
the first walk-forward training window. That date precedes every later
walk-forward test fold, but not the test groups of a CPCV combination
(group 0 sits at the start of history, inside that window), and the final
model trained on the whole history inherited a decision taken on its first
40 %. Here the decision is a function of a boolean TRAINING MASK over the
raw calendar (`reduce_on_mask`): the prefix before a walk-forward cut, the
pre-holdout span, the non-contiguous train complement of a CPCV
combination, or the whole history for the exported model -- each fold gets
its own, and nothing outside its training bars is ever read.

Off by default (`UniverseConfig.reduction_corr_threshold = None`): never a
silent filter. When enabled, each decision is printed with its counts, and
an explicit warning flags an aggressive setting (`AGGRESSIVE_*`).

Algorithm (unchanged from the branch): scipy `linkage`, method="average"
(UPGMA) on the condensed `1 - |corr|` distance, cut with
`fcluster(criterion="distance", t=1 - corr_threshold)` -- two series share
a cluster iff the AVERAGE |corr| linking their groups is >= the threshold
(average, not single linkage: no chaining of A~B and B~C into A~C).
Representative: the member with the most valid training observations
(ties alphabetical). The target is never a candidate, never dropped.

Returns: only between two CONSECUTIVE training bars (t-1 and t both in the
mask), so no return straddles a test block; the last `lookback` such
returns. Log returns when the series is strictly positive on those bars,
first differences otherwise (spreads and rates can be <= 0). A series with
a missing value on those bars is not eligible: kept as-is, never dropped.

What "dropping a series" removes from a fold (`mask_features`): every
feature whose OWNER -- the raw series it describes, longest raw-column
prefix of its name -- is dropped; an interaction is removed if either
operand's owner is. Group-relative features (cross-sectional momentum,
leave-one-out idiosyncratic vol, `features/guida.py`) belong to their own
member and keep their full-group definition. A feature with no identifiable
owner is kept.

`required_series` is the other direction, used by predict/explain/drift:
the raw series a set of features is COMPUTED from (group-relative features
need their whole group), so they can rebuild only those.
"""
from __future__ import annotations

import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from patrick.features.guida import multi_series_dependencies
from patrick.features.interactions import INTERACTION_TYPES

# Below this |corr| threshold, clusters start merging series that are only
# moderately related -- flagged, never refused.
AGGRESSIVE_CORR_THRESHOLD = 0.80
# Dropping more than this share of the eligible candidates is flagged too.
AGGRESSIVE_DROP_FRAC = 0.50

# Same marker resolution as `pipeline/engine.py::_apply_interaction_formulas`
# (first type, in dict order, whose marker appears in the name).
_INTERACTION_MARKERS = tuple(f"__{name}__" for name in INTERACTION_TYPES)


class AggressiveReductionWarning(UserWarning):
    pass


@dataclass
class ReductionResult:
    kept: list[str]
    dropped: dict[str, str] = field(default_factory=dict)  # dropped series -> representative
    clusters: dict[str, int] = field(default_factory=dict)
    as_of: pd.Timestamp | None = None                       # last training bar
    not_eligible: list[str] = field(default_factory=list)  # missing values on the window: kept as-is
    n_returns: int = 0
    skipped_reason: str | None = None

    def to_dict(self) -> dict:
        return {"as_of": None if self.as_of is None else str(self.as_of.date()),
                "kept": list(self.kept), "dropped": dict(sorted(self.dropped.items())),
                "not_eligible": list(self.not_eligible), "n_returns": self.n_returns,
                "skipped_reason": self.skipped_reason}


def _training_returns(prices: pd.DataFrame, train_mask: np.ndarray, lookback: int
                      ) -> tuple[pd.DataFrame, list[str]]:
    """Returns of each column over the last `lookback` pairs of consecutive
    training bars. Second element: columns with a missing value there."""
    mask = np.asarray(train_mask, dtype=bool)
    if len(mask) != len(prices):
        raise ValueError(f"train_mask has {len(mask)} entries for {len(prices)} bars")
    pos = np.flatnonzero(mask[1:] & mask[:-1]) + 1
    pos = pos[-lookback:] if lookback else pos
    prev = prices.to_numpy(dtype=float)[pos - 1]
    cur = prices.to_numpy(dtype=float)[pos]
    out, not_eligible = {}, []
    for j, col in enumerate(prices.columns):
        p0, p1 = prev[:, j], cur[:, j]
        if not (np.isfinite(p0).all() and np.isfinite(p1).all()):
            not_eligible.append(col)
            continue
        if (p0 > 0).all() and (p1 > 0).all():
            out[col] = np.log(p1 / p0)
        else:
            out[col] = p1 - p0
    return pd.DataFrame(out, index=prices.index[pos]), not_eligible


def _clusters(returns: pd.DataFrame, corr_threshold: float) -> dict[str, int]:
    corr = returns.corr().fillna(0.0)  # zero-variance series: distance 1, never merged
    arr = (1.0 - corr.abs()).clip(lower=0.0).to_numpy(copy=True)
    np.fill_diagonal(arr, 0.0)
    arr = (arr + arr.T) / 2.0
    if len(arr) < 2:
        return {s: 1 for s in corr.index}
    link = linkage(squareform(arr, checks=False), method="average")
    labels = fcluster(link, t=1.0 - corr_threshold, criterion="distance")
    return {sym: int(lab) for sym, lab in zip(corr.index, labels)}


def reduce_on_mask(prices: pd.DataFrame, train_mask, corr_threshold: float,
                   lookback: int = 252, min_obs: int = 60) -> ReductionResult:
    """Reduction decided on the bars where `train_mask` is True, nothing
    else (see module docstring). `prices`: one column per candidate series
    on the raw calendar -- the target excluded by the caller."""
    if not 0.0 < corr_threshold <= 1.0:
        raise ValueError(f"corr_threshold must be in (0, 1], got {corr_threshold}")
    mask = np.asarray(train_mask, dtype=bool)
    as_of = prices.index[mask][-1] if mask.any() else None
    candidates = list(prices.columns)
    returns, not_eligible = _training_returns(prices, mask, lookback)
    if len(returns) < min_obs:
        return ReductionResult(kept=candidates, as_of=as_of, not_eligible=not_eligible,
                               n_returns=len(returns),
                               skipped_reason=f"{len(returns)} training returns < min_obs={min_obs}")
    if returns.shape[1] < 2:
        return ReductionResult(kept=candidates, as_of=as_of, not_eligible=not_eligible,
                               n_returns=len(returns), skipped_reason="fewer than 2 eligible series")

    clusters = _clusters(returns, corr_threshold)
    train_values = prices[mask]
    n_valid = {sym: int(train_values[sym].notna().sum()) for sym in returns.columns}
    representative: dict[int, str] = {}
    for sym in sorted(returns.columns, key=lambda x: (-n_valid[x], x)):
        representative.setdefault(clusters[sym], sym)
    dropped = {sym: representative[clusters[sym]] for sym in returns.columns
               if representative[clusters[sym]] != sym}

    drop_frac = len(dropped) / returns.shape[1]
    if corr_threshold < AGGRESSIVE_CORR_THRESHOLD or drop_frac > AGGRESSIVE_DROP_FRAC:
        warnings.warn(
            f"Aggressive universe reduction: corr_threshold={corr_threshold} "
            f"(flagged below {AGGRESSIVE_CORR_THRESHOLD}), {len(dropped)}/{returns.shape[1]} "
            f"eligible series dropped ({drop_frac:.0%}).", AggressiveReductionWarning, stacklevel=2)
    return ReductionResult(kept=[s for s in candidates if s not in dropped], dropped=dropped,
                           clusters=clusters, as_of=as_of, not_eligible=not_eligible,
                           n_returns=len(returns))


def reduce_universe(prices: dict[str, pd.Series] | pd.DataFrame, as_of, corr_threshold: float,
                    lookback: int = 252, min_obs: int = 60) -> ReductionResult:
    """Walk-forward special case: the training bars are every bar <= `as_of`."""
    frame = prices if isinstance(prices, pd.DataFrame) else pd.DataFrame(prices)
    return reduce_on_mask(frame, np.asarray(frame.index <= pd.Timestamp(as_of)), corr_threshold,
                          lookback=lookback, min_obs=min_obs)


def correlation_clusters(prices: dict[str, pd.Series] | pd.DataFrame, as_of, corr_threshold: float,
                         lookback: int = 252, min_obs: int = 60) -> dict[str, int]:
    return reduce_universe(prices, as_of, corr_threshold, lookback, min_obs).clusters


def _split_interaction(feature: str) -> tuple[str, str] | None:
    for marker in _INTERACTION_MARKERS:
        if marker in feature:
            a, b = feature.split(marker, 1)
            return a, b
    return None


def feature_owner(feature: str, raw_columns: Sequence[str]) -> str | None:
    """The raw series a (non-interaction) feature describes: the longest raw
    column that is the feature's name or a `<column>_` prefix of it."""
    best = None
    for col in raw_columns:
        if (feature == col or feature.startswith(col + "_")) and (best is None or len(col) > len(best)):
            best = col
    return best


def feature_owners(feature: str, raw_columns: Sequence[str]) -> frozenset[str] | None:
    parts = _split_interaction(feature)
    if parts is not None:
        a, b = (feature_owners(p, raw_columns) for p in parts)
        return None if a is None or b is None else a | b
    owner = feature_owner(feature, raw_columns)
    return None if owner is None else frozenset((owner,))


def mask_features(feature_pool: Sequence[str], dropped: Iterable[str], raw_columns: Sequence[str],
                  owners_cache: dict | None = None) -> list[str]:
    """`feature_pool` minus every feature owned (even partly) by a dropped
    series, order preserved. Unknown owner -> kept."""
    dropped = set(dropped)
    if not dropped:
        return list(feature_pool)
    cache = owners_cache if owners_cache is not None else {}
    kept = []
    for f in feature_pool:
        if f not in cache:
            cache[f] = feature_owners(f, raw_columns)
        owners = cache[f]
        if owners is None or not (owners & dropped):
            kept.append(f)
    return kept


def feature_dependencies(feature: str, raw_columns: Sequence[str]) -> frozenset[str] | None:
    """Every raw series `feature`'s VALUE is computed from; None if unknown."""
    parts = _split_interaction(feature)
    if parts is not None:
        a, b = (feature_dependencies(p, raw_columns) for p in parts)
        return None if a is None or b is None else a | b
    group = multi_series_dependencies(feature, raw_columns)
    if group is not None:
        return group
    owner = feature_owner(feature, raw_columns)
    return None if owner is None else frozenset((owner,))


def required_series(features: Iterable[str], raw_columns: Sequence[str], target_col: str) -> list[str] | None:
    """Raw columns (in `raw_columns` order, target always included) enough
    to rebuild `features` identically; None if any feature's dependencies
    are unknown (the caller then keeps the whole universe)."""
    needed = {target_col}
    for f in features:
        deps = feature_dependencies(f, raw_columns)
        if deps is None:
            return None
        needed |= deps
    return [c for c in raw_columns if c in needed]


def restrict_to_required_series(raw: pd.DataFrame, features: Iterable[str], target_col: str) -> pd.DataFrame:
    """`raw` reduced to the series `features` are computed from (same
    index, `attrs` kept); `raw` itself when that is everything or unknown."""
    needed = required_series(features, list(raw.columns), target_col)
    if needed is None or len(needed) == raw.shape[1]:
        return raw
    out = raw[needed]
    out.attrs = dict(raw.attrs)
    return out


def summary_line(label: str, result: ReductionResult, n_candidates: int, n_features: int,
                 n_pool: int, corr_threshold: float) -> str:
    if result.skipped_reason:
        return f"[UNIVERSE] {label}: reduction skipped ({result.skipped_reason}), universe unchanged"
    extra = f", {len(result.not_eligible)} with missing values kept as-is" if result.not_eligible else ""
    return (f"[UNIVERSE] {label} (train to {result.as_of.date()}, |corr|>={corr_threshold}): "
            f"{n_candidates - len(result.dropped)}/{n_candidates} candidate series kept{extra}, "
            f"{n_features}/{n_pool} features")
