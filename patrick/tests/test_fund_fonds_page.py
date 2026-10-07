"""Page /fonds et fragment /api/fund/strategies/{id}/panel : rendu serveur, échappement, i18n, navigation."""
from __future__ import annotations

import re

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp import i18n, i18n_fund, nav_registry
from patrick.webapp.app import app

XSS = "<script>alert(1)</script>"
XSS_ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_fonds_page_lists_strategies_and_totals(client):
    assert "Aucune stratégie." in client.get("/fonds").text
    a = fs.make_strategy(client)
    fs.make_strategy(client, "Actions PEA", wrapper="PEA", initial_capital=50_000)
    fs.place(client, a)
    html = client.get(f"/fonds?strategy={a}").text
    assert html.count('class="fund-row') == 2 and f'data-strategy-id="{a}"' in html
    assert "Valeur du fonds" in html and "Capital total" in html and "150 000,00 €" in html
    assert 'id="fund-panel"' in html and '<script src="/static/fonds.js"></script>' in html
    assert fs.json_script(html, "fund-selected") == a and 'class="fund-row is-selected"' in html
    assert fs.json_script(client.get("/fonds").text, "fund-selected") is None


def test_fonds_page_is_available_in_english(client):
    fs.make_strategy(client)
    fund = client.get("/fonds?lang=en").text
    assert "LP Fund" in fund and "Fund value" in fund and "Valeur du fonds" not in fund


def test_the_old_wealth_simulator_url_redirects_to_the_fund_page(client):
    resp = client.get("/patrimoine-simulation", follow_redirects=False)
    assert resp.status_code == 308 and resp.headers["location"] == "/fonds"
    assert client.get("/patrimoine-simulation").url.path == "/fonds"


def test_navigation_lists_fonds_in_the_simulation_category_and_lights_it_up(client):
    entries = [e.slug for e in nav_registry.entries_for("simulation")]
    assert entries == ["simulate", "fonds"]
    side = client.get("/fonds").text
    assert 'href="/fonds"' in side and 'href="/patrimoine-simulation"' not in side
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', side)
    assert current == ["/fonds"]
    assert "/patrimoine-simulation" not in nav_registry.registered_routes()
    assert nav_registry.is_non_page_route("/patrimoine-simulation")


def test_strategy_names_are_escaped_on_the_fund_page_and_in_the_panel(client):
    sid = fs.make_strategy(client, XSS)
    fs.place(client, sid)
    for url in ("/fonds", f"/api/fund/strategies/{sid}/panel"):
        html = client.get(url).text
        assert XSS_ESCAPED in html, url
        assert XSS not in html, url


def test_panel_for_a_strategy_without_positions(client):
    sid = fs.make_strategy(client)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "Aucune position ouverte." in html and f'href="/simulate?strategy={sid}"' in html
    assert "Valeur (NAV)" in html and "Historique des ordres (0)" in html
    assert "Positions fermées" not in html and "data-form=" not in html
    assert client.get("/api/fund/strategies/str_missing/panel").status_code == 404


def test_panel_shows_kpis_chart_positions_and_per_position_forms(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, instrument_kind="equity", symbol="AAPL", quantity=10)
    fs.place(client, sid, instrument_kind="future", side="short", quantity=1, date="2026-01-08",
             spec={"root": "ES", "year": 2026, "month": 12, "stop": 7000})
    fs.place(client, sid, instrument_kind="cfd", symbol="^GSPC", quantity=2, date="2026-01-09", spec={"leverage": 10})
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    for label in ("Valeur (NAV)", "Réalisé", "Latent", "Frais cumulés", "Volatilité annualisée", "Drawdown max",
                  "Exposition brute", "Levier brut", "Marge utilisée", "Liquidités disponibles", "Cash"):
        assert label in html, label
    chart = fs.json_script(html, "fund-chart-data")
    assert chart["capital"] == 100_000 and len(chart["series"]) > 5
    assert html.count('class="fund-position"') == 3 and html.count('data-form="adjust"') == 3
    assert html.count('data-form="correct"') == 3 and html.count('data-act="delete-position"') == 3
    assert "AAPL" in html and "ESZ26.CME" in html and "^GSPC" in html and "USD · " in html
    assert "éch. 2026-12-18" in html and "10:1" in html and "S 7" in html            # échéance, levier, stop
    assert html.count('value="modify"') == 2                                          # future et CFD seulement
    assert html.count('name="leverage"') == 2                                         # CFD : ajustement et correction
    assert "taux de référence USD" in html                                            # note affichée (FRED non configuré)
    assert 'id="fund-chart"' in html


def test_panel_lists_closed_positions_and_the_order_history(client):
    sid = fs.make_strategy(client)
    pid = fs.place(client, sid, quantity=4)["preview"]["position_id"]
    client.post(f"/api/fund/strategies/{sid}/orders", json={"action": "close", "position_id": pid, "date": "2026-01-12"})
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "Positions fermées" in html and "Fermée" in html and "2026-01-07 → 2026-01-12" in html
    assert "Historique des ordres (2)" in html and "Ouverture" in html and "Clôture" in html
    assert "Aucune position ouverte." in html and 'class="fund-position"' not in html


def test_panel_flags_manual_prices_and_fees_in_the_history(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, price=650, fees_mode="manual", fees=3)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "650 *" in html.replace(" ", " ") and "3,00 € *" in html


def test_no_untranslated_key_leaks_into_the_pages_in_either_language(client):
    sid = fs.make_strategy(client)
    pid = fs.place(client, sid, instrument_kind="cfd", symbol="^GSPC", quantity=2, spec={"leverage": 10})["preview"][
        "position_id"]
    fs.place(client, sid, symbol="AAPL", quantity=5, date="2026-01-08")
    client.post(f"/api/fund/strategies/{sid}/orders", json={"action": "close", "position_id": pid, "date": "2026-01-12"})
    for lang in ("fr", "en"):
        for url in ("/simulate", "/fonds", f"/api/fund/strategies/{sid}/panel"):
            html = re.sub(r'<script id="i18n-data".*?</script>', "", client.get(f"{url}{'&' if '?' in url else '?'}lang={lang}").text,
                          flags=re.DOTALL)
            assert re.findall(r"\bfund_[a-z_]+\b", html) == [], (url, lang)


def test_dynamic_label_families_are_all_translated():
    expected = {f"fund_kind_{k}" for k in ("equity", "etf", "future", "cfd")}
    expected |= {f"fund_side_{s}" for s in ("long", "short")}
    expected |= {f"fund_status_{s}" for s in ("open", "closed", "stop", "target", "expired")}
    expected |= {f"fund_action_{a}" for a in ("open", "increase", "reduce", "close", "modify")}
    assert expected <= set(i18n_fund.FUND_STRINGS)
    for key, entry in i18n_fund.FUND_STRINGS.items():
        assert entry["fr"] and entry["en"], key
    assert set(i18n.STRINGS) >= set(i18n_fund.FUND_STRINGS)


def test_the_fund_script_uses_only_exposed_and_defined_strings(client):
    js = client.get("/static/fonds.js").text
    used = set(re.findall(r"""['"](fund_[a-z_]+)['"]""", js)) | set(re.findall(r"""I18N\.(fund_[a-z_]+)""", js))
    assert used <= set(i18n.STRINGS), used - set(i18n.STRINGS)
    assert used <= set(i18n.js_strings("fr")), used - set(i18n.js_strings("fr"))


def test_archived_strategies_are_listed_and_can_be_restored_and_archiving_asks_for_confirmation(client):
    archived = fs.make_strategy(client, "Ancienne")
    kept = fs.make_strategy(client, "Garde")
    client.patch(f"/api/fund/strategies/{archived}", json={"archived": True})
    html = client.get("/fonds").text
    assert 'class="fund-archived"' in html and "Stratégies archivées (1)" in html
    assert re.search(rf'data-act="unarchive"[^>]*data-strategy-id="{archived}"', html)
    assert f'data-strategy-id="{kept}"' in html and html.count('class="fund-row') == 1
    panel = client.get(f"/api/fund/strategies/{kept}/panel").text
    assert re.search(r'data-act="archive"[^>]*data-confirm="[^"]+"', panel)
    client.patch(f"/api/fund/strategies/{archived}", json={"archived": False})
    again = client.get("/fonds").text
    assert 'class="fund-archived"' not in again and again.count('class="fund-row') == 2


def test_the_correction_form_is_prefilled_with_the_manual_price_and_fees(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, price=650, fees_mode="manual", fees=3)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    correct = html.split('data-form="correct"')[1].split("</form>")[0]
    assert 'value="650.0"' in correct and '<option value="manual" selected>' in correct
    fs.place(client, sid, symbol="TTE.PA", quantity=2, date="2026-01-08")
    second = client.get(f"/api/fund/strategies/{sid}/panel").text.split('data-form="correct"')[2].split("</form>")[0]
    assert '<option value="estimated" selected>' in second and 'name="price" min="0" step="any" value=""' in second


def test_the_fund_header_breaks_the_total_down_by_strategy(client):
    fs.make_strategy(client, "Grande", initial_capital=75_000)
    fs.make_strategy(client, "Petite", wrapper="PEA", initial_capital=25_000)
    html = client.get("/fonds").text
    block = html.split('class="fund-breakdown"')[1].split("</ul>")[0]
    assert block.count('class="fund-share"') == 2 and "Grande" in block and "Petite" in block
    assert "width: 75.0%" in block and "width: 25.0%" in block


def test_the_positions_table_separates_the_price_effect_from_the_fx_effect(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, symbol="AAPL", quantity=3)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "dont prix €" in html and "dont change €" in html
    assert 'colspan="12"' not in html and 'colspan="13"' in html
    row = html.split('class="fund-position"')[1].split("</tr>")[0]
    assert row.count('class="num pk-mono"') >= 8


def test_the_fund_scripts_never_open_a_native_browser_dialog(client):
    native = re.compile(r"(?<![\w.])(?:window\.)?(?:confirm|prompt|alert)\(")
    for script in ("fonds.js", "simulate.js"):
        found = native.findall(client.get(f"/static/{script}").text)
        assert found == [], (script, found)


def test_the_fonds_page_ships_an_in_page_rename_dialog_and_uses_the_shared_confirmation(client):
    fs.make_strategy(client)
    html = client.get("/fonds").text
    assert '<dialog id="fund-rename-dialog" class="modal"' in html and 'id="fund-rename-form"' in html
    assert "Nouveau nom de la stratégie" in html and "fund-confirm-dialog" not in html
    assert '<dialog id="confirm-dialog" class="modal"' in html                      # boîte partagée de base_v2.html
    assert "New strategy name" in client.get("/fonds?lang=en").text
    assert "fund-rename-dialog" not in client.get("/api/fund/strategies/str_x/panel").text    # jamais dans le fragment rechargé


def test_each_strategy_row_has_its_own_delete_button_with_a_confirmation(client):
    a = fs.make_strategy(client, "Macro CTO")
    b = fs.make_strategy(client, "Actions PEA", wrapper="PEA", initial_capital=50_000)

    html = client.get("/fonds").text

    for sid in (a, b):
        assert f'data-act="delete-strategy" data-strategy-id="{sid}"' in html
    assert html.count('data-act="delete-strategy"') == 2 and "data-confirm=" in html
    assert 'class="fund-row' in html                      # le bouton est dans la ligne, sans ouvrir le panneau


def test_the_row_delete_button_is_translated(client):
    fs.make_strategy(client)
    assert "Supprimer" in client.get("/fonds").text
    assert "Delete" in client.get("/fonds?lang=en").text
