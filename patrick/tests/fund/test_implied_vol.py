"""Volatilité implicite contre la prévision HAR (FO24 du 25/11)."""
from __future__ import annotations

import math

import pytest

from patrick.fund import vol_forecast


def test_the_premium_compares_implied_and_forecast_annual_volatility():
    out = vol_forecast.implied_vs_forecast("^GSPC", 0.01, 20.0)
    assert out["index"] == "^VIX" and out["implied"] == pytest.approx(0.20)
    assert out["forecast"] == pytest.approx(0.01 * math.sqrt(252)) and out["premium_var"] > 0 and out["ratio"] > 1


def test_missing_inputs_give_nothing():
    assert vol_forecast.implied_vs_forecast("^GSPC", None, 20.0) is None and vol_forecast.implied_vs_forecast("^GSPC", 0.01, None) is None
