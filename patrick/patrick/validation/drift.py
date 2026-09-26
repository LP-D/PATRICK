"""Combined data/concept drift monitor per (ticker, horizon) -- Phase X
(feature/model-drift-badge). Two independent signals, not one:

- Data drift: Population Stability Index (PSI) between a reference (e.g.
  training-time) feature distribution and a recent one. Computable
  continuously, the moment a new feature observation exists -- no
  dependency on the target's outcome ever being known.
- Concept drift: a Page-Hinkley test on the REALIZED hit-rate stream
  (caller passes only RESOLVED hits -- same "resolved outcome" concept
  `tracking.history.live_hit_rate_by_target_and_horizon` already
  establishes, see that function's docstring for the backfill mechanism).
  Never computable before `horizon` days have elapsed on enough
  predictions -- there is no realized outcome to compare against before
  that.

A badge therefore has three possible states, not two: `insufficient_data`
(not even data drift is computable yet -- too few recent feature
observations), `provisional` (data drift available, concept drift not yet
-- target not realized in enough volume), `confirmed` (both signals
available). Deliberately NOT built on `patrick.audit.run_degradation_audit`:
that is a one-time comparative validator over 4 fixed leakage-fix
configurations and 5 hardcoded targets (see its module docstring), a
different tool for a different question -- not a per-ticker/horizon
continuous monitor.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Usual PSI thresholds (industry convention, e.g. credit-risk model
# monitoring): <0.1 stable, 0.1-0.25 attention, >0.25 significant drift.
# Kept as plain function-parameter defaults, same pattern as this project's
# other tunable statistical thresholds (`tracking.history.DM_SIGNIFICANCE_ALPHA`,
# the `fdr_alpha` family) -- overridable per call, not a DB config row.
PSI_WARN_THRESHOLD = 0.1
PSI_ALERT_THRESHOLD = 0.25

# Below this many recent feature observations, a PSI computed against them
# is noise, not signal -- mirrors the "gated behind a minimum sample size"
# spirit of `tracking.history.LIVE_HIT_RATE_WARNING_THRESHOLD`'s own
# `_MIN_DIRECTION_SAMPLES` gate.
MIN_OBS_FOR_DATA_DRIFT = 30

# Below this many resolved (realized) predictions, a Page-Hinkley read is
# unreliable -- matches `tracking.history.LIVE_HIT_RATE_WINDOW` (30), the
# existing rolling-hit-rate window this module's concept-drift signal is a
# more sensitive companion to (a static <0.5 threshold vs. an actual
# change-point test).
MIN_HITS_FOR_CONCEPT_DRIFT = 30

# Page-Hinkley: `delta` (tolerated rise of the error rate, the CUSUM
# allowance) and `lambda_threshold` (cumulative deviation that triggers).
# Calibrated by simulation on 2026-09-26 (drift policy,
# docs/ops/politique-derive.md) for a 0/1 hit series at ~55 % accuracy:
# - literature defaults (river / scikit-multiflow: 0.005, 5): 41 % false
#   alarms over 250 independent calls, 63 % over 750 -- with delta ~ 0 the
#   statistic is a random walk whose range grows like sqrt(n), so it fires
#   eventually whatever the model;
# - 0.05 / 12, alarm at the FIRST crossing (stopping rule): 1.3 % false
#   alarms over 250 independent calls, 5.7 % over 750; a 15-point hit-rate
#   drop (55 % -> 40 %) is caught in ~60 % of cases within 250 calls,
#   median delay ~107 calls. Deliberately conservative: a false alarm leads
#   to a retrain, and every retrain adds trials to the DSR registry (F03).
PAGE_HINKLEY_DELTA = 0.05
PAGE_HINKLEY_LAMBDA = 12.0


def population_stability_index(expected: Sequence[float], actual: Sequence[float],
                                bins: int = 10) -> float:
    """PSI of `actual` against a `bins`-quantile binning derived from
    `expected` (the reference distribution). One-shot convenience wrapper
    around `decile_reference` + `psi_from_reference` for callers that have
    both raw samples in hand and no reason to persist the reference (e.g.
    a single ad hoc comparison, or this module's own tests) -- production
    on-demand monitoring persists the reference once (`decile_reference`,
    written at fit time by `tracking.export.export_best_model`) and reuses
    it via `psi_from_reference` without ever re-touching the raw training
    sample again."""
    reference = decile_reference(expected, bins=bins)
    return psi_from_reference(reference, actual)


def decile_reference(expected: Sequence[float], bins: int = 10) -> dict:
    """The PERSISTABLE form of a PSI reference: `bins`-quantile bin edges
    derived from `expected`, plus `expected`'s own proportion in each bin
    -- small and fixed-size regardless of the training sample's length, so
    it can be stored (`tracking.db.save_drift_reference`, migration 0018)
    without ever needing to keep the raw training sample around. Edges are
    widened to +/-inf at the extremes so a genuinely shifted future sample
    (outside the reference's observed range) still lands in the extreme
    bin instead of being silently dropped by `np.histogram`. NaNs (rolling-
    window warm-up rows in the training window) are ignored: a single one
    would otherwise turn every percentile into NaN and collapse the
    reference into the degenerate single bin below."""
    expected = np.asarray(expected, dtype=float)
    quantiles = np.linspace(0, 100, bins + 1)
    breakpoints = np.unique(np.nanpercentile(expected, quantiles))
    if len(breakpoints) < 3:
        # Degenerate (near-constant) reference distribution -- a single
        # catch-all bin makes psi_from_reference return 0.0 rather than
        # dividing by a zero-count bin.
        breakpoints = np.array([-np.inf, np.inf])
    else:
        breakpoints = breakpoints.copy()
        breakpoints[0] = -np.inf
        breakpoints[-1] = np.inf
    expected_counts, _ = np.histogram(expected, bins=breakpoints)
    expected_pct = expected_counts / expected_counts.sum()
    return {"edges": breakpoints.tolist(), "expected_pct": expected_pct.tolist()}


def psi_from_reference(reference: dict, actual: Sequence[float]) -> float:
    """PSI of `actual` against a persisted `decile_reference(...)` result --
    the standard formula, `sum((actual_pct - expected_pct) * ln(actual_pct
    / expected_pct))` over the reference's own bins. Never touches the
    original training sample: everything needed lives in `reference`."""
    actual = np.asarray(actual, dtype=float)
    edges = np.asarray(reference["edges"], dtype=float)
    expected_pct = np.asarray(reference["expected_pct"], dtype=float)

    actual_counts, _ = np.histogram(actual, bins=edges)
    actual_pct = actual_counts / actual_counts.sum()

    eps = 1e-4  # avoids log(0)/division-by-zero on an empty bin, standard PSI convention
    expected_pct = np.where(expected_pct == 0, eps, expected_pct)
    actual_pct = np.where(actual_pct == 0, eps, actual_pct)
    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))


def data_drift_status(psi: float, warn: float = PSI_WARN_THRESHOLD,
                       alert: float = PSI_ALERT_THRESHOLD) -> str:
    if psi < warn:
        return "stable"
    if psi < alert:
        return "attention"
    return "significant"


def page_hinkley_test(hits: Sequence[int], delta: float = PAGE_HINKLEY_DELTA,
                       lambda_threshold: float = PAGE_HINKLEY_LAMBDA) -> dict:
    """Standard incremental Page-Hinkley test for an increase in the mean
    of the ERROR series `1 - hit` (PH detects a rise in mean; a concept
    drift here means hit rate falling, i.e. errors rising). `hits` is the
    realized 1/0 outcome of each directional call, oldest first.

    A stopping rule: the alarm is the FIRST time the statistic crosses
    `lambda_threshold` (`detected_at`, 0-based index in `hits`) and stays
    raised -- it was read at the last point only, so an alarm could appear
    then vanish from one day to the next as the running mean caught up."""
    mean_error = 0.0
    cumulative = 0.0
    min_cumulative = 0.0
    ph_value = 0.0
    detected_at = None
    n = 0
    for h in hits:
        error = 1 - h
        n += 1
        mean_error += (error - mean_error) / n
        cumulative += error - mean_error - delta
        min_cumulative = min(min_cumulative, cumulative)
        ph_value = cumulative - min_cumulative
        if detected_at is None and ph_value > lambda_threshold:
            detected_at = n - 1
    return {
        "ph_value": float(ph_value),
        "drift_detected": detected_at is not None,
        "detected_at": detected_at,
        "n": n,
        "mean_error_rate": float(mean_error),
    }


@dataclass(frozen=True)
class DriftBadge:
    symbol: str
    horizon: int
    psi: float | None
    data_drift_status: str  # "stable" | "attention" | "significant" | "insufficient_data"
    concept_drift_detected: bool | None
    concept_drift_ph_value: float | None
    state: str  # "insufficient_data" | "provisional" | "confirmed"
    reason: str


def compute_drift_badge(symbol: str, horizon: int, reference: Sequence[float],
                         recent: Sequence[float], realized_hits: Sequence[int],
                         psi_bins: int = 10, psi_warn: float = PSI_WARN_THRESHOLD,
                         psi_alert: float = PSI_ALERT_THRESHOLD,
                         min_recent_obs: int = MIN_OBS_FOR_DATA_DRIFT,
                         min_hits: int = MIN_HITS_FOR_CONCEPT_DRIFT) -> DriftBadge:
    """Combines both signals into one badge per (symbol, horizon). `state`
    is the UI-visible distinction the design calls for: `insufficient_data`
    (not even a trustworthy PSI yet), `provisional` (data drift known,
    target not realized in enough volume for concept drift),
    `confirmed` (both signals known)."""
    recent = np.asarray(recent, dtype=float)
    if len(recent) < min_recent_obs:
        return DriftBadge(
            symbol=symbol, horizon=horizon, psi=None, data_drift_status="insufficient_data",
            concept_drift_detected=None, concept_drift_ph_value=None, state="insufficient_data",
            reason=(f"Seulement {len(recent)} observation(s) recente(s) pour {symbol} -- "
                    f"{min_recent_obs} requises pour un PSI fiable."),
        )

    psi = population_stability_index(reference, recent, bins=psi_bins)
    status = data_drift_status(psi, psi_warn, psi_alert)

    if len(realized_hits) < min_hits:
        return DriftBadge(
            symbol=symbol, horizon=horizon, psi=psi, data_drift_status=status,
            concept_drift_detected=None, concept_drift_ph_value=None, state="provisional",
            reason=(f"Data drift calculable (PSI={psi:.3f}, {status}) mais cible pas encore "
                    f"realisee en volume suffisant ({len(realized_hits)}/{min_hits}) pour le "
                    f"concept drift -- badge provisoire tant que l'horizon ({horizon}j) n'est "
                    "pas ecoule sur assez de predictions."),
        )

    ph = page_hinkley_test(realized_hits)
    return DriftBadge(
        symbol=symbol, horizon=horizon, psi=psi, data_drift_status=status,
        concept_drift_detected=ph["drift_detected"], concept_drift_ph_value=ph["ph_value"],
        state="confirmed",
        reason=(f"Data drift : PSI={psi:.3f} ({status}). Concept drift (Page-Hinkley sur "
                f"{ph['n']} predictions realisees) : "
                f"{'detecte' if ph['drift_detected'] else 'non detecte'}."),
    )
