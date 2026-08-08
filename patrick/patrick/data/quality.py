"""Phase 6.5 -- data quality gates at ingestion: every candidate series
(yfinance or FRED) goes through a battery of checks BEFORE entering the
feature universe. Every exclusion is explicitly justified and persisted
(never a `[WARN]` lost in the logs, as the FRED fallback used to be before
its fix -- same class of defect, see session report).

Default thresholds -- MEASURED, not chosen by convention (see the P6.5
correction report for simulation details):

- `DEFAULT_MAX_FROZEN_RUN = 4` (consecutive identical closes): simulation of
  500 series x 4000 days (price ~100, 1.5% daily vol, rounded to 2 decimals
  -- typical quoting) -- NO clean series reaches a run of 4 identical
  closes (max observed: 3). A run of 4+ almost never happens by chance on an
  actively quoted series.
- `DEFAULT_MAX_GAP_BDAYS = 10` (quoting gap): the longest known clusters of
  market-holiday days (Christmas/New Year with overlapping holidays
  depending on jurisdiction) reach ~5 consecutive business days -- 10
  business days (2 weeks) gives a 2x safety margin over this plausible
  maximum, while still catching a real trading suspension. Reused as-is for
  `check_stale_tail` (early series end = a quoting gap that was never
  filled).
- `DEFAULT_MAX_ROBUST_Z = 40.0` (aberrant return): simulation of 500 series
  x 4000 days of Student-t returns (df=5, fat tails realistic for a liquid
  asset) -- max robust z-score (global MAD x 1.4826, resistant to outliers
  that would bias a classical standard deviation) observed across all CLEAN
  series: 35.5 (0/500 exceed 40). An unadjusted split (2:1, mildest case
  tested) produces z ≈ 40; more blatant cases (10:1, decimal-point error)
  give 60-700+ -- a clean separation between clean market noise and data
  corruption.
- `DEFAULT_MIN_COVERAGE = 0.85`: reuses `UniverseConfig.yf_coverage`
  (already in place, Phase 0), not a newly invented threshold.
- `DEFAULT_MAX_UNIVERSE_EXCLUSION_FRAC = 0.30`: beyond this, the loss is on
  ENTIRE series (not the partial coverage already tolerated by
  `yf_coverage`) -- a third of the requested universe gone signals a
  systemic problem (bad tickers/start_date/provider outage), not a few
  individually failing series; below it, feature selection (`pool_prefilter`,
  already aggressive) remains workable on what's left.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

DEFAULT_MAX_FROZEN_RUN = 4
DEFAULT_MAX_GAP_BDAYS = 10
DEFAULT_MAX_ROBUST_Z = 40.0
DEFAULT_MIN_COVERAGE = 0.85
DEFAULT_MAX_UNIVERSE_EXCLUSION_FRAC = 0.30


@dataclass
class QualityIssue:
    series: str
    reason: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def robust_z_scores(returns: pd.Series) -> pd.Series:
    """MAD (median absolute deviation from the median) rescaled by 1.4826 to be
    a consistent estimator of the standard deviation under normality --
    resistant to fat tails (a single outlier doesn't inflate the denominator,
    unlike a classical standard deviation)."""
    med = returns.median()
    mad = (returns - med).abs().median()
    robust_sigma = mad * 1.4826
    if robust_sigma < 1e-12:
        return pd.Series(0.0, index=returns.index)
    return (returns - med) / robust_sigma


def check_frozen_prices(s: pd.Series, max_run: int = DEFAULT_MAX_FROZEN_RUN) -> QualityIssue | None:
    """`max_run`: number of consecutive identical closes above which the
    series is considered frozen (see module justification)."""
    vals = s.dropna().values
    if len(vals) < max_run:
        return None
    same = np.diff(vals) == 0
    run = 1
    best = 1
    for is_same in same:
        run = run + 1 if is_same else 1
        best = max(best, run)
    if best >= max_run:
        return QualityIssue(s.name, "prix_figes", f"{best} consecutive identical closes (threshold {max_run})")
    return None


def check_quote_gaps(s: pd.Series, max_gap_bdays: int = DEFAULT_MAX_GAP_BDAYS) -> QualityIssue | None:
    """Longest gap (in business days) between two consecutive non-NaN
    observations of `s`, on the full business-day index provided by the
    caller (`s.index` must already be the expected business-day calendar)."""
    valid_dates = s.dropna().index
    if len(valid_dates) < 2:
        return None
    gaps = valid_dates.to_series().diff().dt.days.dropna()
    # Business-day grid (no Saturday/Sunday): a "normal" one-business-day gap
    # is worth ~1-3 calendar days depending on position in the week -- we
    # convert to approximate business days via the 7/5 ratio (5 business days
    # per 7-day calendar week), consistent with `pd.bdate_range`.
    gaps_bdays = gaps * 5 / 7
    max_gap = gaps_bdays.max() if len(gaps_bdays) else 0.0
    if max_gap > max_gap_bdays:
        worst_idx = gaps_bdays.idxmax()
        return QualityIssue(s.name, "trou_de_cotation",
                             f"gap of ~{max_gap:.0f} business days ending {worst_idx.date()} "
                             f"(threshold {max_gap_bdays})")
    return None


def check_aberrant_returns(s: pd.Series, max_robust_z: float = DEFAULT_MAX_ROBUST_Z) -> QualityIssue | None:
    ret = s.dropna().pct_change().dropna()
    ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
    if len(ret) < 30:
        return None
    z = robust_z_scores(ret)
    max_abs_z = z.abs().max()
    if max_abs_z > max_robust_z:
        worst_idx = z.abs().idxmax()
        return QualityIssue(s.name, "rendement_aberrant",
                             f"return of {ret.loc[worst_idx]:.1%} on {worst_idx.date()} "
                             f"(robust z={max_abs_z:.1f}, threshold {max_robust_z})")
    return None


def check_stale_tail(s: pd.Series, requested_end: pd.Timestamp,
                      max_gap_bdays: int = DEFAULT_MAX_GAP_BDAYS) -> QualityIssue | None:
    valid_dates = s.dropna().index
    if len(valid_dates) == 0:
        return None
    last_date = valid_dates.max()
    gap_days = (requested_end - last_date).days
    gap_bdays = gap_days * 5 / 7
    if gap_bdays > max_gap_bdays:
        return QualityIssue(s.name, "fin_de_serie_precoce",
                             f"last observation {last_date.date()}, "
                             f"~{gap_bdays:.0f} business days before the requested end "
                             f"({requested_end.date()}, threshold {max_gap_bdays}) -- likely delisted")
    return None


def check_fred_missing(name: str, s: pd.Series | None) -> QualityIssue | None:
    if s is None or s.dropna().empty:
        return QualityIssue(name, "fred_absent_ou_discontinue",
                             "no observation returned (discontinued series, invalid identifier, "
                             "or fetch failure)")
    return None


def check_coverage(s: pd.Series, full_index: pd.DatetimeIndex,
                    min_coverage: float = DEFAULT_MIN_COVERAGE) -> QualityIssue | None:
    if len(full_index) == 0:
        return None
    coverage = s.reindex(full_index).notna().mean()
    if coverage < min_coverage:
        return QualityIssue(s.name, "couverture_insuffisante",
                             f"{coverage:.1%} of business days populated (threshold {min_coverage:.0%})")
    return None


def evaluate_yfinance_series(name: str, s: pd.Series, full_index: pd.DatetimeIndex,
                              requested_end: pd.Timestamp, *, max_frozen_run: int = DEFAULT_MAX_FROZEN_RUN,
                              max_gap_bdays: int = DEFAULT_MAX_GAP_BDAYS,
                              max_robust_z: float = DEFAULT_MAX_ROBUST_Z,
                              min_coverage: float = DEFAULT_MIN_COVERAGE) -> QualityIssue | None:
    """Returns the FIRST detected issue (an excluded series is excluded for
    one reason, not cumulatively) -- order: coverage, quoting gap, early end,
    frozen prices, aberrant return (from most "structural" to most fine-
    grained)."""
    s = s.rename(name) if s.name != name else s
    for check, kwargs in (
        (check_coverage, {"full_index": full_index, "min_coverage": min_coverage}),
        (check_quote_gaps, {"max_gap_bdays": max_gap_bdays}),
        (check_stale_tail, {"requested_end": requested_end, "max_gap_bdays": max_gap_bdays}),
        (check_frozen_prices, {"max_run": max_frozen_run}),
        (check_aberrant_returns, {"max_robust_z": max_robust_z}),
    ):
        issue = check(s, **kwargs)
        if issue is not None:
            return issue
    return None
