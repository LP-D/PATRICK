"""Chantier 2 (feature/model-drift-badge): combined data+concept drift
monitor per (ticker, horizon). Two independent signals:

- data drift: Population Stability Index (PSI) on a feature's distribution,
  reference (training) window vs recent window -- computable continuously,
  no dependency on the target's outcome being known yet.
- concept drift: Page-Hinkley test on the REALIZED hit-rate stream (the
  caller passes only resolved hits -- same "resolved outcome" concept
  `tracking.history.live_hit_rate_by_target_and_horizon` already
  establishes, see that function's docstring for the backfill mechanism)
  -- only computable once outcomes are known, i.e. never before `horizon`
  days after each prediction.

Deliberately NOT built on `patrick.audit.run_degradation_audit`: that is a
one-time comparative validator over 4 fixed leakage-fix configurations and
5 hardcoded targets (see its module docstring) -- a different tool for a
different question, not a per-ticker/horizon continuous monitor.
"""
from __future__ import annotations

import numpy as np

from patrick.validation import drift


def test_psi_is_near_zero_for_identical_distributions():
    rng = np.random.default_rng(0)
    reference = rng.normal(0, 1, 2000)
    recent = rng.normal(0, 1, 2000)
    psi = drift.population_stability_index(reference, recent, bins=10)
    assert psi < 0.02


def test_psi_flags_significant_shift_on_known_case():
    rng = np.random.default_rng(1)
    reference = rng.normal(0, 1, 2000)
    recent = rng.normal(2.5, 1, 2000)  # large mean shift, known/expected to trip "significant"
    psi = drift.population_stability_index(reference, recent, bins=10)
    assert psi > drift.PSI_ALERT_THRESHOLD


def test_data_drift_status_thresholds():
    assert drift.data_drift_status(0.05) == "stable"
    assert drift.data_drift_status(0.15) == "attention"
    assert drift.data_drift_status(0.30) == "significant"


def test_page_hinkley_detects_a_known_hit_rate_break():
    rng = np.random.default_rng(2)
    stable = rng.binomial(1, 0.7, 200)
    degraded = rng.binomial(1, 0.3, 200)
    hits = list(stable) + list(degraded)
    result = drift.page_hinkley_test(hits)
    assert result["drift_detected"] is True
    assert result["n"] == 400


def test_page_hinkley_does_not_flag_a_stable_hit_rate():
    rng = np.random.default_rng(3)
    hits = list(rng.binomial(1, 0.65, 400))
    result = drift.page_hinkley_test(hits)
    assert result["drift_detected"] is False


def test_page_hinkley_false_alarm_rate_is_controlled_over_a_year_of_calls():
    """Drift policy of 2026-09-26: the literature defaults (delta 0.005,
    lambda 5) fired on ~63 % of 3-year simulations WITHOUT any drift (the
    statistic is a random walk whose range grows like sqrt(n)). Calibrated
    by simulation, alarm at the first crossing: <= 5 % false alarms over 250
    independent calls at a 55 % hit rate (<= 10 % over 750), and a 15-point
    drop still caught in about 60 % of cases, never before it happens."""
    def run(hits):
        return drift.page_hinkley_test(list(hits))

    alarms_1y = sum(run(np.random.default_rng(s).binomial(1, 0.55, 250))["drift_detected"] for s in range(300))
    alarms_3y = sum(run(np.random.default_rng(s).binomial(1, 0.55, 750))["drift_detected"] for s in range(150))
    assert alarms_1y / 300 <= 0.05 and alarms_3y / 150 <= 0.10
    detected = early = 0
    for s in range(200):
        rng = np.random.default_rng(1000 + s)
        res = run(np.r_[rng.binomial(1, 0.55, 100), rng.binomial(1, 0.40, 250)])
        detected += res["drift_detected"] and res["detected_at"] >= 100
        early += res["drift_detected"] and res["detected_at"] < 100
    assert detected / 200 >= 0.5 and early / 200 <= 0.02


def test_badge_is_provisional_before_target_is_realized_in_enough_volume():
    """Data drift alone (horizon not yet elapsed on enough predictions to
    trust a concept-drift read) -> 'provisional', never 'confirmed' --
    the state the badge must show while a data-drift signal already exists
    but the target outcome is still unknown/too sparse."""
    rng = np.random.default_rng(4)
    reference = rng.normal(0, 1, 500)
    recent = rng.normal(0, 1, 500)
    badge = drift.compute_drift_badge("GSPC", 5, reference, recent, realized_hits=[])
    assert badge.state == "provisional"
    assert badge.concept_drift_detected is None
    assert badge.psi is not None  # data drift itself IS available


def test_badge_is_confirmed_once_target_is_realized_with_enough_hits():
    rng = np.random.default_rng(5)
    reference = rng.normal(0, 1, 500)
    recent = rng.normal(0, 1, 500)
    hits = list(rng.binomial(1, 0.6, 60))
    badge = drift.compute_drift_badge("GSPC", 5, reference, recent, realized_hits=hits)
    assert badge.state == "confirmed"
    assert badge.concept_drift_detected is not None


def test_badge_is_insufficient_data_with_too_few_recent_observations():
    rng = np.random.default_rng(6)
    reference = rng.normal(0, 1, 500)
    recent = rng.normal(0, 1, 3)  # far below any usable sample size for PSI
    badge = drift.compute_drift_badge("GSPC", 5, reference, recent, realized_hits=[])
    assert badge.state == "insufficient_data"
    assert badge.psi is None
