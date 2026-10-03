"""Page /simulate : ticket d'ordre en haut, portefeuilles par stratégie en dessous (rendu serveur)."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp.app import app

XSS = "<script>alert(1)</script>"
XSS_ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_page_without_a_strategy_offers_to_create_one(client):
    resp = client.get("/simulate")
    assert resp.status_code == 200
    assert "Aucune stratégie." in resp.text and 'id="new-strategy-dialog"' in resp.text
    assert 'id="ticket-form"' not in resp.text


def test_page_shows_the_ticket_then_the_portfolios_below(client):
    sid = fs.make_strategy(client)
    other = fs.make_strategy(client, "Actions PEA", wrapper="PEA", initial_capital=50_000)
    fs.place(client, sid)
    html = client.get(f"/simulate?strategy={other}").text
    assert html.index('id="ticket-form"') < html.index("Portefeuilles par stratégie")
    assert f'<option value="{other}" data-opened="2026-01-05" selected>' in html
    assert html.count('name="instrument_kind"') == 4 and 'value="future"' in html and 'value="cfd"' in html
    assert 'name="side"' in html and 'name="fees_mode"' in html and 'id="f-date"' in html
    assert 'value="2026-01-16" max="2026-01-16"' in html                  # date du ticket : aujourd'hui, pas au-delà
    assert html.count('class="account-card"') == 2 and f'href="/fonds?strategy={sid}"' in html
    assert "Macro CTO" in html and "Actions PEA" in html and "Position ouverte." not in html
    es = next(f for f in fs.json_script(html, "futures-data") if f["root"] == "ES")
    assert es["contracts"][0]["symbol"] == "ESH26.CME" and es["margin"] > 0
    assert "Position ouverte." in client.get(f"/simulate?strategy={sid}&placed=1").text


def test_page_exposes_the_js_strings_in_both_languages_and_loads_its_script(client):
    fs.make_strategy(client)
    html = client.get("/simulate").text
    strings = fs.json_script(html, "i18n-data")
    assert strings["fund_pv_day"] == "Jour d'exécution" and strings["fund_leverage_cap"] == "plafond {cap}:1"
    assert '<script src="/static/simulate.js"></script>' in html
    english = client.get("/simulate?lang=en").text
    assert fs.json_script(english, "i18n-data")["fund_pv_day"] == "Execution day"
    assert "Order ticket" in english and "Portfolios by strategy" in english


def test_strategy_names_are_escaped(client):
    sid = fs.make_strategy(client, XSS)
    fs.place(client, sid)
    html = client.get("/simulate").text
    assert XSS_ESCAPED in html and XSS not in html


def test_the_page_script_uses_only_exposed_and_defined_strings(client):
    import re

    from patrick.webapp import i18n

    js = client.get("/static/simulate.js").text
    used = set(re.findall(r"""['"](fund_[a-z_]+)['"]""", js))
    assert used <= set(i18n.STRINGS), used - set(i18n.STRINGS)
    exposed = set(i18n.js_strings("fr"))
    assert used <= exposed, used - exposed
