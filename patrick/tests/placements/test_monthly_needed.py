"""Versement mensuel qui atteint un objectif de patrimoine (FO21 du 25/11)."""
from __future__ import annotations

import numpy as np

from patrick.placements import projection
from patrick.placements.envelopes import ENVELOPES


def _paths(monthly_ret: float, n: int = 400, months: int = 120):
    rng = np.random.default_rng(0)
    return monthly_ret + rng.normal(0, 0.02, (n, months)), np.zeros((n, months))


def test_more_certainty_needs_a_higher_monthly_saving():
    port, euro = _paths(0.004)
    contrib = {"initial": 1000.0, "monthly": 0.0, "yearly": 0.0, "growth": 0.0, "goal": 50_000.0}
    out = projection.monthly_needed(port, euro, 0.0, ENVELOPES["cto"], contrib, 120, 10, 50_000.0)
    assert out["p50"] is not None and out["p80"] is not None and 0 < out["p50"] <= out["p80"] < 500


def test_a_goal_already_reached_needs_nothing_and_an_impossible_one_is_said_so():
    port, euro = _paths(0.004)
    rich = {"initial": 200_000.0, "monthly": 0.0, "yearly": 0.0, "growth": 0.0, "goal": 50_000.0}
    assert projection.monthly_needed(port, euro, 0.0, ENVELOPES["cto"], rich, 120, 10, 50_000.0) == {"p50": 0.0, "p80": 0.0}
    crash, euro = _paths(-0.08)
    poor = {"initial": 0.0, "monthly": 0.0, "yearly": 0.0, "growth": 0.0, "goal": 1_000_000.0}
    assert projection.monthly_needed(crash, euro, 0.0, ENVELOPES["cto"], poor, 120, 10, 1_000_000.0)["p80"] is None
