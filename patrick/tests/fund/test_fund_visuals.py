"""Visuels des fonds (26/11) : treemap des positions (VI2), corrélation ordonnée (VI4), nuage risque / rendement (VI6)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.webapp import fund_visuals as fv


def test_squarify_fills_the_box_with_areas_proportional_to_values():
    values = [6, 6, 4, 3, 2, 2, 1]
    rects = fv.squarify(values, 0, 0, 600, 400)
    areas = [w * h for _x, _y, w, h in rects]
    assert len(rects) == len(values) and sum(areas) == pytest.approx(600 * 400)
    for a, v in zip(areas, values, strict=True):
        assert a == pytest.approx(600 * 400 * v / sum(values))
    assert all(0 <= x <= 600 + 1e-6 and 0 <= y <= 400 + 1e-6 for x, y, _w, _h in rects)


def test_position_tiles_use_the_notional_of_derivatives_and_the_sign_of_the_pnl():
    positions = [{"symbol": "AAPL", "status": "open", "side": "long", "value_base": 3000, "pnl": 120, "pnl_pct": 0.04},
                 {"symbol": "ES=F", "status": "open", "side": "short", "value_base": 0.0, "quantity": 1, "last_price": 5000, "fx_now": 0.9,
                  "pnl": -80, "pnl_pct": -0.02},
                 {"symbol": "OLD", "status": "closed", "value_base": 100}]
    tiles = fv.position_tiles(positions, nav=10_000)
    assert [t["symbol"] for t in tiles] == ["ES=F", "AAPL"]                  # 4 500 € de notionnel avant 3 000 €
    assert tiles[0]["tone"] == "down" and tiles[1]["tone"] == "up" and tiles[0]["weight"] == pytest.approx(0.45)


def test_correlation_groups_assets_that_move_together():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2025-01-01", periods=260)
    a, b = rng.normal(0, 0.01, 260), rng.normal(0, 0.01, 260)
    series = {s: pd.Series(100 * np.exp(np.cumsum(r)), index=idx) for s, r in
              {"A1": a, "B1": b, "A2": a + rng.normal(0, 0.002, 260), "B2": b + rng.normal(0, 0.002, 260)}.items()}
    out = fv.correlation(series)
    order = out["symbols"]
    assert abs(order.index("A1") - order.index("A2")) == 1 and abs(order.index("B1") - order.index("B2")) == 1
    assert out["matrix"][0][0] == 1.0 and fv.correlation({"A1": series["A1"]}) is None


def test_risk_return_points_place_riskier_strategies_to_the_right():
    strategies = [{"strategy": {"name": "Prudent"}, "kpis": {"volatility": 0.05, "pnl_pct": 0.02, "nav": 1000}},
                  {"strategy": {"name": "Audacieux"}, "kpis": {"volatility": 0.30, "pnl_pct": -0.10, "nav": 4000}},
                  {"strategy": {"name": "Sans vol"}, "kpis": {"volatility": None, "pnl_pct": 0.0, "nav": 10}}]
    sc = fv.risk_return_points(strategies)
    prudent, bold = sc["dots"]
    assert bold["cx"] > prudent["cx"] and bold["cy"] > sc["zero_y"] > prudent["cy"] and bold["r"] > prudent["r"]
    assert fv.risk_return_points(strategies[:1]) is None
