"""Valorisation d'une action (A8) : multiples, DCF inversé, DCF et sensibilité ; fragment de la fiche d'actif."""
from __future__ import annotations

import pytest

from patrick.analysis import valuation as v

INFO = {"longName": "Exemple SA", "currency": "USD", "financialCurrency": "USD", "currentPrice": 100.0, "marketCap": 100e9,
        "enterpriseValue": 110e9, "freeCashflow": 4e9, "sharesOutstanding": 1e9, "beta": 1.2, "trailingPE": 25.0, "forwardPE": 21.5,
        "enterpriseToEbitda": 15.0, "enterpriseToRevenue": 4.0, "priceToBook": 6.0, "trailingAnnualDividendYield": 0.012}


def test_enterprise_value_matches_the_gordon_formula_without_growth_phase():
    # croissance du FCF égale à la croissance terminale : rente perpétuelle croissante FCF1 / (r - g)
    ev = v.enterprise_value(100.0, 0.02, 0.08, terminal=0.02, years=10)
    assert ev == pytest.approx(100.0 * 1.02 / (0.08 - 0.02), rel=1e-9)


def test_implied_growth_recovers_the_growth_used_to_price():
    ev = v.enterprise_value(4e9, 0.07, 0.10)
    assert v.implied_growth(ev, 4e9, 0.10) == pytest.approx(0.07, abs=1e-6)
    assert v.implied_growth(ev, -1.0, 0.10) is None


def test_analyse_reads_multiples_and_builds_the_dcf():
    out = v.analyse(INFO, rf=0.04, growth=0.05)
    m = out["multiples"]
    assert m["pe_trailing"] == 25.0 and m["fcf_yield"] == pytest.approx(0.04) and m["dividend_yield"] == pytest.approx(0.012)
    d = out["dcf"]
    assert d["rate"] == pytest.approx(0.04 + 1.2 * 0.05)
    expected = (v.enterprise_value(4e9, 0.05, d["rate"]) - 10e9) / 1e9
    assert d["value"] == pytest.approx(expected) and d["upside"] == pytest.approx(expected / 100.0 - 1)
    assert d["grid"][1][1] == pytest.approx(d["value"], rel=1e-12)
    assert d["grid"][0][2] > d["grid"][1][1] > d["grid"][2][0]          # taux plus bas et croissance plus forte : valeur plus haute
    assert -0.5 < d["implied_growth"] < 1.0


@pytest.mark.parametrize(("patch", "reason"), [({"freeCashflow": -1e9}, "negative_fcf"), ({"financialCurrency": "TWD"}, "currency"),
                                              ({"sharesOutstanding": None}, "missing")])
def test_no_dcf_when_it_makes_no_sense(patch, reason):
    out = v.analyse({**INFO, **patch})
    assert out["dcf"] is None and out["dcf_reason"] == reason


def test_beta_is_bounded_and_defaults_to_one():
    assert v.discount_rate(None, 0.04) == pytest.approx(0.09)
    assert v.discount_rate(5.0, 0.04) == pytest.approx(0.14) and v.discount_rate(0.1, 0.04) == pytest.approx(0.065)


def test_risk_free_of_the_quote_currency():
    asked = []

    def loader(symbol):
        asked.append(symbol)
        return {"closes": [4.1, 4.25]} if symbol == "^TNX" else {"closes": [2.71]}
    assert v.risk_free("USD", loader=loader) == pytest.approx(0.0425)
    assert v.risk_free("EUR", loader=loader) == pytest.approx(0.0271)
    assert v.risk_free(None, loader=loader) == pytest.approx(0.0425)
    assert asked == ["^TNX", "IRLTLT01DEM156N", "^TNX"]
    assert v.risk_free("USD", loader=lambda s: {"closes": []}) is None


def test_fragment_renders_and_refuses_unknown_symbols(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from patrick.webapp import app as webapp
    from patrick.webapp import forms
    from patrick.webapp.routes import assets as assets_routes

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    symbol = next(s for s, src in forms.TARGET_SOURCE_BY_SYMBOL.items() if src == "yfinance" and "." not in s and not s.startswith("^"))
    monkeypatch.setattr(v, "load_info", lambda s: dict(INFO))
    monkeypatch.setattr(v, "risk_free", lambda currency=None, loader=None: 0.04)
    assets_routes._VALUATION_CACHE.clear()
    client = TestClient(webapp.app)
    text = client.get(f"/fragments/valuation/{symbol}", params={"g": 0.08}).text
    assert "DCF inversé" in text and "PER attendu" in text and "21,5" in text and 'value="0.08" selected' in text
    assert client.get("/fragments/valuation/NOPE_XYZ").status_code == 404
    assets_routes._VALUATION_CACHE.clear()
    monkeypatch.setattr(v, "load_info", lambda s: {})
    assert "Pas de données de valorisation" in client.get(f"/fragments/valuation/{symbol}").text
