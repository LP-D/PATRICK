"""Drift alert policy (decided 2026-09-26, docs/ops/politique-derive.md).

- Data drift never triggers a retrain on its own: the model may still be
  right on shifted inputs, and every retrain adds trials to the DSR
  registry (F03). It is judged on the SHARE of the model's features whose
  PSI exceeds 0.25 -- the single worst PSI among 20 features is itself a
  maximum, inflated by construction.
- Concept drift (live hit rate falling) is the only "retrain" signal. It is
  tested on INDEPENDENT calls only: one live call every `horizon` sessions
  (overlapping h-day outcomes are autocorrelated; measured on 750 simulated
  daily calls without drift: Page-Hinkley false alarms 10 % at h = 5 and
  16 % at h = 20 on overlapping calls, 0 % once thinned), and needs >= 30.
- A PSI measurement older than 14 days is flagged stale; the nightly job
  re-measures pairs older than 7 days.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from patrick.validation import drift_policy as pol

TODAY = dt.date(2026, 9, 26)


def test_data_drift_levels_use_the_share_of_drifting_features():
    ok = pol.assess([0.05] * 10, "2026-09-25 22:10:00", [], 5, TODAY)
    assert ok["data_level"] == "stable" and ok["action"] == "ok"
    one_of_twenty = pol.assess([0.4] + [0.02] * 19, "2026-09-25", [], 5, TODAY)
    assert one_of_twenty["share_significant"] == 0.05 and one_of_twenty["action"] == "ok"
    watch = pol.assess([0.3, 0.3] + [0.02] * 8, "2026-09-25", [], 5, TODAY)
    assert watch["data_level"] == "watch" and watch["action"] == "watch"
    heavy = pol.assess([0.5] * 4 + [0.02] * 6, "2026-09-25", [], 5, TODAY)
    assert heavy["data_level"] == "drift" and heavy["action"] == "watch"   # never "retrain" on data alone


def test_concept_drift_is_tested_on_independent_calls_only():
    rng = np.random.default_rng(0)
    drop = list(rng.binomial(1, 0.6, 150)) + list(rng.binomial(1, 0.1, 150))
    daily = pol.assess([0.02] * 10, "2026-09-25", drop, 1, TODAY)
    assert daily["n_independent"] == 300 and daily["concept_drift"] is True and daily["action"] == "retrain"
    # the same 300 daily calls at a 20-day horizon are only 15 independent ones: not enough
    monthly = pol.assess([0.02] * 10, "2026-09-25", drop, 20, TODAY)
    assert monthly["n_independent"] == 15 and monthly["concept_drift"] is None and monthly["action"] == "ok"


def test_unmeasured_and_stale_measurements():
    none = pol.assess(None, None, [], 5, TODAY)
    assert none["action"] == "unmeasured" and none["stale"] is None
    old = pol.assess([0.02] * 10, "2026-09-01 22:00:00", [], 5, TODAY)
    assert old["stale"] is True and old["action"] == "ok"
    assert pol.needs_remeasure(None, TODAY) and pol.needs_remeasure("2026-09-18", TODAY)
    assert not pol.needs_remeasure("2026-09-22 22:05:00", TODAY)


def test_reason_is_a_readable_sentence():
    r = pol.assess([0.3, 0.3] + [0.02] * 8, "2026-09-25", [], 5, TODAY)["reason"]
    assert "2/10" in r and "PSI" in r
