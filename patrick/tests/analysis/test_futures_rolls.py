"""Sauts de changement d'échéance des contrats à terme continus (CO26 du 25/11)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.analysis import futures_rolls


def _series(jump_dates: list[str], size: float = 0.05) -> pd.Series:
    idx = pd.bdate_range("2023-01-02", "2024-12-31")
    r = np.random.default_rng(0).normal(0, 0.008, len(idx))
    s = pd.Series(r, index=idx)
    for d in jump_dates:
        s.loc[pd.Timestamp(d)] = size
    return 100 * np.exp(s.cumsum())


def test_a_jump_on_a_third_friday_is_flagged_and_an_ordinary_day_is_not():
    close = _series(["2024-03-15", "2024-05-08"])                 # 15/03/2024 = troisième vendredi ; 08/05 : loin d'une échéance
    rows = futures_rolls.suspected_rolls("ES=F", close)
    dates = {str(d)[:10] for d in rows["date"]}
    assert "2024-03-15" in dates and "2024-05-08" not in dates


def test_energy_contracts_roll_near_month_end():
    close = _series(["2024-06-28"])
    assert "2024-06-28" in {str(d)[:10] for d in futures_rolls.suspected_rolls("CL=F", close)["date"]}


def test_a_short_series_gives_an_empty_answer():
    assert futures_rolls.suspected_rolls("ES=F", _series([]).iloc[:30]).empty
    assert futures_rolls.summary("ES=F", _series(["2024-03-15"]))["n_suspect"] >= 1
