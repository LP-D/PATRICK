"""Exposition aux devises du patrimoine réel (FO22 du 25/11)."""
from __future__ import annotations

import pytest

from patrick.wealth.currency_exposure import currency_of, exposure


@pytest.mark.parametrize(("symbol", "ccy"), [("CW8.PA", "EUR"), ("AAPL", "USD"), ("VOD.L", "GBP"), ("NESN.SW", "CHF"), ("BTC-USD", "USD"),
                                             ("EURUSD=X", "USD"), ("DAT:fonds-euros", "EUR"), ("GC=F", "?"), ("^GSPC", "?"), ("", "EUR")])
def test_the_quote_currency_comes_from_the_symbol(symbol, ccy):
    assert currency_of(symbol) == ccy


def test_exposure_counts_cash_in_euro_and_leaves_unknown_lines_out_of_the_foreign_share():
    out = exposure([{"symbol": "AAPL", "value": 3000}, {"symbol": "CW8.PA", "value": 5000}, {"symbol": "GC=F", "value": 1000}], cash=1000)
    shares = {r["currency"]: r["share"] for r in out["rows"]}
    assert out["total"] == 10_000 and shares["EUR"] == pytest.approx(0.6) and out["foreign_share"] == pytest.approx(3000 / 9000)
