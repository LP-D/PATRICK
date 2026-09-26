"""Purging (VIX_PURGED_CV): a train row whose label window (horizon business
days forward) overlaps the fold cut must be removed from train, otherwise
it carries information about the test period — the leak measured in the
project was negligible (delta F1_dir≈-0.002) but the option stays wired in.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np
import pandas as pd

# `compute_would_purge` is called once per (horizon, fold, regime) combination
# within a run (`pipeline/engine.py::_FoldContext.prepare`), always against
# the SAME `all_dates` object (set once in `_FoldContext.__init__`) -- tens of
# calls per run in practice. Rebuilding `{date: position}` from scratch every
# time is pure waste for an object that never changes across those calls.
# Keyed by `id(all_dates)` (a `pd.DatetimeIndex` is not hashable) with the
# index object itself kept alive alongside its `pos` dict, so a
# garbage-collected-and-reused id can never be served a stale entry built for
# an unrelated index. Bounded (small `OrderedDict`, FIFO eviction) so a
# long-lived process (e.g. the webapp, many runs over time) doesn't
# accumulate one entry per run forever.
_POS_CACHE: OrderedDict[int, tuple[pd.DatetimeIndex, dict]] = OrderedDict()
_POS_CACHE_MAXSIZE = 8


def _positions(all_dates: pd.DatetimeIndex) -> dict:
    key = id(all_dates)
    cached = _POS_CACHE.get(key)
    if cached is not None and cached[0] is all_dates:
        _POS_CACHE.move_to_end(key)
        return cached[1]
    pos = {d: i for i, d in enumerate(all_dates)}
    _POS_CACHE[key] = (all_dates, pos)
    _POS_CACHE.move_to_end(key)
    if len(_POS_CACHE) > _POS_CACHE_MAXSIZE:
        _POS_CACHE.popitem(last=False)
    return pos


def compute_would_purge(all_dates: pd.DatetimeIndex, base_index: pd.DatetimeIndex,
                         horizon: int, cut_date) -> pd.Series:
    """For each date in `base_index` (typically the fold's train index),
    computes whether its label window (horizon business days further in
    `all_dates`, the full history index) reaches or exceeds `cut_date`."""
    pos = _positions(all_dates)

    def fwd_date(d):
        i = pos.get(d)
        if i is None:
            return d
        j = min(i + horizon, len(all_dates) - 1)
        return all_dates[j]

    would_purge = pd.Series(
        [fwd_date(d) >= cut_date for d in base_index], index=base_index
    )
    return would_purge


def purge_mask(full_index: pd.DatetimeIndex, train_mask: np.ndarray,
               all_dates: pd.DatetimeIndex, horizon: int, cut_date) -> np.ndarray:
    """Removes from `train_mask` (boolean, aligned on `full_index`) the rows
    whose label window overlaps `cut_date`. Only modifies positions already
    True."""
    train_dates = full_index[train_mask]
    would_purge = compute_would_purge(all_dates, train_dates, horizon, cut_date)
    out = train_mask.copy()
    out[np.where(train_mask)[0]] = ~would_purge.values
    return out
