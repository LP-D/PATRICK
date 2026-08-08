"""Embargo (López de Prado): beyond purge (removes from train the rows whose
LABEL window overlaps the cut), embargo removes from TEST the `e` bars
immediately following the cut. Distinct motivation from purge: rolling-
window features (rolling mean/std/EWMA...) computed just after the cut
still include train observations in their window, so can stay correlated
with it even once the label is "clean" (already handled by purge). Default
`e = horizon` (see `ValidationConfig.embargo_bars=None` -> derived from the
current horizon rather than hardcoded), consistent with the order of
magnitude of the longest feature windows used in this project.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def embargo_mask(full_index: pd.DatetimeIndex, mask: np.ndarray, cut_date,
                  embargo_bars: int) -> np.ndarray:
    """Removes from `mask` (typically the test mask, aligned on `full_index`)
    the first `embargo_bars` rows at or after `cut_date`. Only modifies
    positions already True; does not touch positions before `cut_date`
    (embargo applies to the start of test, not the end of train -- see
    purge for that side)."""
    if embargo_bars <= 0:
        return mask
    out = mask.copy()
    positions = np.where(mask)[0]
    if len(positions) == 0:
        return out
    dates_at_positions = full_index[positions]
    is_at_or_after_cut = dates_at_positions >= cut_date
    to_drop = positions[is_at_or_after_cut][:embargo_bars]
    out[to_drop] = False
    return out
