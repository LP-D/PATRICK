"""A19 : VaR et ES à 99 % par la théorie des valeurs extrêmes (loi de Pareto généralisée sur les pertes au-delà de leur 90e centile)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from patrick.fund import kpis


def test_on_student_returns_the_evt_var_matches_the_true_quantile_better_than_a_thin_tail():
    df, scale = 3, 0.01
    r = pd.Series(stats.t.rvs(df, size=3000, random_state=4) * scale)
    out = kpis.tail_risk(r)
    true_var = -stats.t.ppf(0.01, df) * scale
    assert out["var_evt"] == pytest.approx(true_var, rel=0.15)
    assert out["xi"] > 0.1                                               # queue épaisse reconnue (t à 3 degrés : xi théorique 1/3)
    assert out["es_evt"] > out["var_evt"] > 0 and out["n_tail"] == pytest.approx(300, abs=2)


def test_a_normal_tail_has_a_shape_near_zero():
    r = pd.Series(np.random.default_rng(1).normal(0, 0.01, 4000))
    out = kpis.tail_risk(r)
    assert abs(out["xi"]) < 0.2 and out["var_evt"] == pytest.approx(2.326 * 0.01, rel=0.1)


def test_too_few_returns_give_none():
    assert kpis.tail_risk(pd.Series(np.random.default_rng(2).normal(0, 0.01, 100))) is None
