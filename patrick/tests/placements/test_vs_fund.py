"""Compte réel contre fonds simulé (FO19 du 25/11)."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.wealth.vs_fund import compare


def test_both_start_at_the_first_common_date():
    idx = pd.bdate_range("2026-01-01", periods=40)
    account = pd.Series([100 * 1.001 ** i for i in range(40)], index=idx)
    fund = [{"t": d.date().isoformat(), "nav": 5000 * 1.002 ** i} for i, d in enumerate(idx[10:])]
    out = compare(account, fund)
    assert out["start"] == idx[10].date().isoformat() and out["n"] == 30
    assert out["account"] == pytest.approx(1.001 ** 29 - 1) and out["fund"] == pytest.approx(1.002 ** 29 - 1) and out["gap"] < 0


def test_no_common_period_gives_nothing():
    idx = pd.bdate_range("2026-01-01", periods=10)
    assert compare(pd.Series(range(1, 11), index=idx, dtype=float), [{"t": "2027-01-04", "nav": 1.0}]) is None
    assert compare(None, []) is None
