"""Biais du gagnant : AUC du holdout corrigée du gain attendu du meilleur de k modèles."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation import winner_bias as wb


def test_expected_max_matches_a_simulation():
    rng = np.random.default_rng(0)
    for k in (2, 10, 50):
        simulated = rng.standard_normal((20000, k)).max(axis=1).mean()
        assert wb.expected_max_standard_normal(k) == pytest.approx(simulated, abs=0.02)
    assert wb.expected_max_standard_normal(1) == 0.0


def test_auc_standard_error_shrinks_with_the_sample():
    small, big = wb.auc_standard_error(0.6, 30, 30), wb.auc_standard_error(0.6, 300, 300)
    assert small > big > 0
    assert wb.auc_standard_error(0.6, 0, 30) is None


def test_a_modest_auc_read_by_many_runs_on_few_independent_rows_no_longer_beats_chance():
    one = wb.deflated_auc(0.56, n_rows=300, horizon=5, share_up=0.5, n_readers=1)
    many = wb.deflated_auc(0.56, n_rows=300, horizon=5, share_up=0.5, n_readers=30)
    assert one["expected_gain"] == 0.0 and one["adjusted"] == 0.56
    assert many["n_eff"] == 60.0 and many["adjusted"] < 0.5 and many["beats_chance"] is False


def test_a_strong_auc_on_many_rows_survives_the_correction():
    out = wb.deflated_auc(0.70, n_rows=2500, horizon=1, share_up=0.5, n_readers=20)
    assert out["adjusted"] > 0.65 and out["beats_chance"] is True


@pytest.mark.parametrize("args", [(None, 300, 1, 0.5, 3), (0.6, 0, 1, 0.5, 3), (0.6, 300, 1, 1.0, 3), (float("nan"), 300, 1, 0.5, 3)])
def test_missing_inputs_give_none(args):
    assert wb.deflated_auc(*args) is None
