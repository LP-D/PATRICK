"""Écart achat-vente observé contre le modèle de frais (AM11 du 25/11)."""
from __future__ import annotations

import pytest

from patrick.fund import spread_check


def test_relative_spread_ignores_empty_or_crossed_quotes():
    assert spread_check.relative_spread_bps(99.9, 100.1) == pytest.approx(20.0)
    assert spread_check.relative_spread_bps(0, 100) is None and spread_check.relative_spread_bps(101, 100) is None
    assert spread_check.relative_spread_bps(None, 1) is None


def test_measure_compares_each_class_to_the_model_median():
    quotes = {"A": (99.99, 100.01), "B": (99.98, 100.02), "C": (0, 0), "D": RuntimeError("panne")}

    def quote(sym):
        q = quotes[sym]
        if isinstance(q, Exception):
            raise q
        return q

    (row,) = spread_check.measure(quote, {"equity_large": ("A", "B", "C", "D")})
    assert row["n"] == 2 and row["measured_bps"] == pytest.approx(3.0) and row["ratio"] == pytest.approx(1.5)
