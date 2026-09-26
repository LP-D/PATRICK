"""Drift alert policy (decided 2026-09-26, docs/ops/politique-derive.md).

One action per (target, horizon), from what is stored (feature PSIs of the
latest measurement, resolved live calls):

- `retrain`: concept drift -- Page-Hinkley (`validation.drift`, calibrated
  to <= ~5 % false alarms over 250 independent calls) detects a falling hit
  rate on the INDEPENDENT live calls: one call every `horizon` sessions,
  overlapping h-day outcomes being autocorrelated; >= 30 required;
- `watch`: data drift -- at least 10 % of the model's features have a PSI
  above 0.25 (level `watch` below 30 %, `drift` above). Never a retrain on
  its own: inputs can shift while the model stays right, and every retrain
  adds trials to the DSR registry (F03);
- `ok`: measured, no signal;
- `unmeasured`: no PSI measurement yet.

A measurement older than `STALE_DAYS` is flagged stale (the action is kept,
the badge says it is old); the nightly job (`scripts/daily_predict.py`)
re-measures pairs older than `REMEASURE_DAYS`.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pandas as pd

from patrick.validation import drift as drift_lib

SIGNIFICANT_PSI = drift_lib.PSI_ALERT_THRESHOLD
WATCH_SHARE = 0.10
DRIFT_SHARE = 0.30
MIN_INDEPENDENT_CALLS = 30
STALE_DAYS = 14
REMEASURE_DAYS = 7

ACTION_LABELS = {"retrain": "réentraîner", "watch": "surveiller", "ok": "stable", "unmeasured": "non mesurée"}


def independent_calls(hits: Sequence[int], horizon: int) -> list[int]:
    """One resolved live call every `horizon` sessions (oldest first)."""
    return list(hits)[::max(1, int(horizon))]


def _age_days(measured_at: str | None, today: dt.date) -> int | None:
    if not measured_at:
        return None
    return (today - pd.Timestamp(measured_at).date()).days


def needs_remeasure(measured_at: str | None, today: dt.date) -> bool:
    age = _age_days(measured_at, today)
    return age is None or age >= REMEASURE_DAYS


def assess(psis: Sequence[float] | None, measured_at: str | None, hits: Sequence[int],
           horizon: int, today: dt.date) -> dict:
    out: dict = {"share_significant": None, "n_significant": None, "n_features": 0,
                 "data_level": "unmeasured", "stale": None, "age_days": None,
                 "n_independent": 0, "concept_drift": None, "concept_hit_rate": None}
    reasons = []
    if psis:
        n_sig = sum(1 for p in psis if p > SIGNIFICANT_PSI)
        share = n_sig / len(psis)
        level = "drift" if share >= DRIFT_SHARE else "watch" if share >= WATCH_SHARE else "stable"
        age = _age_days(measured_at, today)
        out.update(share_significant=round(share, 4), n_significant=n_sig, n_features=len(psis),
                   data_level=level, age_days=age, stale=age is not None and age > STALE_DAYS)
        reasons.append(f"{n_sig}/{len(psis)} feature(s) avec PSI > {SIGNIFICANT_PSI:g}"
                       + (f", mesure vieille de {age} j" if out["stale"] else ""))
    else:
        reasons.append("PSI jamais mesuré")

    indep = independent_calls(hits, horizon)
    out["n_independent"] = len(indep)
    if len(indep) >= MIN_INDEPENDENT_CALLS:
        ph = drift_lib.page_hinkley_test(indep)
        out["concept_drift"] = ph["drift_detected"]
        out["concept_hit_rate"] = round(1 - ph["mean_error_rate"], 4)
        reasons.append(f"Page-Hinkley sur {len(indep)} appels live indépendants : "
                       + ("baisse de la réussite détectée" if ph["drift_detected"] else "pas de rupture"))
    else:
        reasons.append(f"dérive de concept non testable : {len(indep)}/{MIN_INDEPENDENT_CALLS} appels "
                       f"live indépendants (un tous les {horizon} j)")

    if out["concept_drift"]:
        action = "retrain"
    elif out["data_level"] in ("watch", "drift"):
        action = "watch"
    elif out["data_level"] == "stable":
        action = "ok"
    else:
        action = "unmeasured"
    out["action"] = action
    out["action_label"] = ACTION_LABELS[action]
    out["reason"] = " ; ".join(reasons) + "."
    return out
