"""Lecture affichée du test de Diebold-Mariano (CO2/CO3 du 25/11) : p unilatérale « le modèle fait mieux », jamais la bilatérale brute."""
from __future__ import annotations

import math

import pytest

from patrick.tracking.run_queries import dm_reading


def test_a_better_model_gets_half_the_two_sided_p():
    r = dm_reading(dm_stat=-2.5, p_value=0.02, baseline="x")
    assert r["p_value"] == pytest.approx(0.01) and r["p_two_sided"] == 0.02 and r["worse"] is False and r["baseline"] == "x"


def test_a_clearly_worse_model_is_never_significant():
    """Avant : p bilatérale 0,02 < 0,05 -> « significatif » en vert pour un modèle NETTEMENT moins bon que sa référence."""
    r = dm_reading(dm_stat=2.5, p_value=0.02)
    assert r["p_value"] == pytest.approx(0.99) and r["worse"] is True


@pytest.mark.parametrize("p", [None, float("nan")])
def test_an_untestable_result_has_no_p(p):
    r = dm_reading(dm_stat=None, p_value=p)
    assert r["p_value"] is None and r["worse"] is False


def test_a_missing_statistic_is_not_read_as_better():
    assert dm_reading(dm_stat=None, p_value=0.02)["p_value"] == pytest.approx(0.99)
    assert dm_reading(dm_stat=math.nan, p_value=0.02)["worse"] is False
