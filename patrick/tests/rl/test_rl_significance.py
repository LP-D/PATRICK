"""Seuil du verdict « bat acheter-garder » corrigé du nombre de runs essayés sur la cible (CO29 du 25/11)."""
from __future__ import annotations

import pytest

from patrick.rl import reading


def test_threshold_is_five_percent_for_one_run_and_shrinks_with_trials():
    assert reading.significance_threshold(1) == pytest.approx(0.05)
    assert reading.significance_threshold(None) == pytest.approx(0.05)
    assert reading.significance_threshold(20) == pytest.approx(1 - 0.95 ** (1 / 20))
    assert reading.significance_threshold(20) < 0.003


def test_a_p_of_two_percent_beats_alone_but_not_after_twenty_trials():
    base = {"sharpe": 1.0, "sharpe_buy_hold": 0.5, "p_vs_buy_hold": 0.02, "agent_share": 1.0, "engine_version": 2}
    assert reading.derive({**base, "n_trials": 1}, "^GSPC", delay={"suspect": False})["verdict"] == "beats"
    out = reading.derive({**base, "n_trials": 20}, "^GSPC", delay={"suspect": False})
    assert out["verdict"] == "better" and out["p_threshold"] < 0.003
