"""Classification quant / réel des fonds (ADR 0026) : arbre de `overview`, page /fonds, filtre, API de création des fonds réels. Aucun réseau."""
from __future__ import annotations

import re

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.fund import service, store
from patrick.tracking import db as trackdb
from patrick.webapp import i18n, i18n_fund
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def _html(client, query: str = "") -> str:
    """La page /fonds et son fragment (le tableau arrive par `/fragments/fund-overview`)."""
    return client.get("/fonds" + query).text + client.get("/fragments/fund-overview" + query).text


def _plain(html: str) -> str:
    """Le HTML avec des espaces ordinaires (les montants portent des espaces insécables)."""
    return html.replace(" ", " ").replace(" ", " ")


def _make_real(client) -> None:
    resp = client.post("/api/fund/real", json={})
    assert resp.status_code == 200, resp.text


def test_overview_groups_the_strategies_by_category_with_separate_totals(conn):
    quant = store.create_strategy(conn, "Quant A", "CTO", 10_000_000, "2026-01-05")
    pea = store.create_strategy(conn, "Réel PEA", "PEA", 5_000, "2026-01-05", category="real", fee_flat=1.0)
    cto = store.create_strategy(conn, "Réel CTO", "CTO", 5_000, "2026-01-05", category="real", fee_flat=1.0)

    out = service.overview(conn, fs.TODAY)

    assert [c["category"] for c in out["categories"]] == ["quant", "real"]
    quant_cat, real_cat = out["categories"]
    assert quant_cat["fund"]["capital"] == 10_000_000 and real_cat["fund"]["capital"] == 10_000 and real_cat["fund"]["n_strategies"] == 2
    assert [g["wrapper"] for g in real_cat["groups"]] == ["PEA", "CTO"] and [g["wrapper"] for g in quant_cat["groups"]] == [None]
    assert [[s["strategy"]["strategy_id"] for s in g["strategies"]] for g in real_cat["groups"]] == [[pea], [cto]]
    assert [r["share"] for r in real_cat["breakdown"]] == [pytest.approx(0.5), pytest.approx(0.5)]    # parts relatives à la catégorie
    assert out["fund"]["capital"] == 10_010_000 and out["strategies"][0]["strategy"]["strategy_id"] == quant


def test_overview_leaves_out_an_empty_category(conn):
    store.create_strategy(conn, "Seul", "CTO", 1_000, "2026-01-05")

    assert [c["category"] for c in service.overview(conn, fs.TODAY)["categories"]] == ["quant"]


def test_the_columns_arrive_with_a_default_on_a_database_that_already_has_strategies(tmp_path):
    path = str(tmp_path / "old.db")
    conn = trackdb.connect(path)
    conn.execute("ALTER TABLE fund_strategy DROP COLUMN category")          # simule une base dont la migration 0053 manque : la réparation recrée les colonnes
    conn.execute("ALTER TABLE fund_strategy DROP COLUMN fee_flat")
    conn.execute("INSERT INTO fund_strategy (strategy_id, name, wrapper, base_currency, initial_capital, opened_on) "
                 "VALUES ('str_old', 'Ancien', 'CTO', 'EUR', 1000, '2026-01-05')")
    conn.commit()
    conn.close()
    trackdb._DRIFT_CHECKED.discard(path)

    conn = trackdb.connect(path)

    strategy = store.get_strategy(conn, "str_old")
    assert (strategy["category"], strategy["fee_flat"]) == ("quant", None)


def test_the_page_offers_the_category_tabs_and_the_real_funds_card(client):
    page = client.get("/fonds").text

    assert 'class="exp-tabs fund-cat-tabs"' in page
    assert 'href="/fonds?categorie=quant"' in page and 'href="/fonds?categorie=real"' in page
    assert page.count('aria-selected="true"') == 1 and 'href="/fonds" aria-selected="true"' in page
    assert 'id="fund-real"' in page and 'data-act="real-create"' in page and "5 000 €" in page.replace(" ", " ").replace("\xa0", " ")
    assert 'data-lazy-url="/fragments/fund-overview"' in page


def test_the_filter_travels_to_the_lazy_fragment_and_marks_the_tab(client):
    page = client.get("/fonds?categorie=real&strategy=str_x").text

    assert 'data-lazy-url="/fragments/fund-overview?strategy=str_x&amp;categorie=real"' in page
    assert 'href="/fonds?categorie=real" aria-selected="true"' in page
    assert 'data-lazy-url="/fragments/fund-overview?categorie=quant"' in client.get("/fonds?categorie=quant").text
    assert 'data-lazy-url="/fragments/fund-overview"' in client.get("/fonds?categorie=nimporte").text         # valeur inconnue : tout


def test_the_overview_shows_one_section_per_category_and_the_filter_keeps_one(client):
    fs.make_strategy(client, "Quant A")
    _make_real(client)

    both = client.get("/fragments/fund-overview").text
    real = client.get("/fragments/fund-overview?categorie=real").text
    quant = client.get("/fragments/fund-overview?categorie=quant").text

    assert both.count('class="fund-category"') == 2 and both.index('data-category="quant"') < both.index('data-category="real"')
    assert real.count('class="fund-category"') == 1 and 'data-category="real"' in real and "Systematic PEA" in real and "Quant A" not in real
    assert quant.count('class="fund-category"') == 1 and "Quant A" in quant and "Systematic CTO" not in quant
    assert real.count('class="fund-row') == 2 and 'data-wrapper="PEA"' in real and 'data-wrapper="CTO"' in real
    assert "Fonds réels" in real and "Fonds quant" in quant
    assert _plain(real).count("1,00 € / ordre") >= 2                                 # le forfait est visible sur chaque ligne d'un fonds réel


def test_a_filter_that_keeps_nothing_says_so_and_offers_the_way_back(client):
    fs.make_strategy(client, "Quant A")

    html = client.get("/fragments/fund-overview?categorie=real").text

    assert "Aucun fonds dans cette catégorie." in html and 'class="fund-category"' not in html and 'href="/fonds"' in html


def test_the_real_funds_listing_ignores_a_quant_strategy_that_has_the_same_name(client):
    fs.make_strategy(client, "Systematic PEA", wrapper="PEA", initial_capital=50_000)

    funds = client.get("/api/fund/real").json()["funds"]

    assert [(f["kind"], f["strategy_id"]) for f in funds] == [("PEA", None), ("CTO", None)]
    assert client.post("/api/fund/real", json={}).status_code == 400            # le nom est pris par un fonds quant : refus, pas de reprise


def test_the_overview_is_available_in_english(client):
    _make_real(client)

    html = client.get("/fragments/fund-overview?lang=en").text

    assert "Real funds" in html and "/ order" in html and "Fonds réels" not in html


def test_the_panel_of_a_real_fund_shows_its_category_fee_and_pilot_settings(client):
    _make_real(client)
    rows = client.get("/api/fund/real").json()["funds"]
    pea_id = next(r["strategy_id"] for r in rows if r["kind"] == "PEA")

    panel = client.get(f"/api/fund/strategies/{pea_id}/panel").text

    assert "1,00 € / ordre" in _plain(panel) and ">réel<" in panel
    assert 'name="min_position"' in panel and 'value="200"' in panel
    assert re.search(r'<option value="auc" selected>', panel) and 'name="allow_short"' not in panel         # un PEA n'a pas de vente à découvert


def test_the_api_lists_the_real_funds_with_their_defaults_and_the_pea_scope(client):
    before = client.get("/api/fund/real").json()

    assert [(f["kind"], f["strategy_id"]) for f in before["funds"]] == [("PEA", None), ("CTO", None)]
    assert before["defaults"]["capital"] == 5_000 and before["defaults"]["fee_flat"] == 1.0 and before["defaults"]["tier"] == "auc"
    assert ".PA" in before["pea"]["euro_suffixes"] and ".ST" in before["pea"]["non_euro_suffixes"] and "Actions Allemagne" in before["pea"]["groups"]


def test_the_api_creates_then_reuses_the_real_funds(client):
    created = client.post("/api/fund/real", json={})
    again = client.post("/api/fund/real", json={"run": False})

    assert created.status_code == 200 and [r["created"] for r in created.json()["rows"]] == [True, True]
    assert [r["created"] for r in again.json()["rows"]] == [False, False] and again.json()["cycle_started"] is False
    assert [f["strategy_id"] is not None for f in client.get("/api/fund/real").json()["funds"]] == [True, True]


def test_the_api_dry_run_writes_nothing_and_bad_input_is_a_400(client):
    preview = client.post("/api/fund/real", json={"dry_run": True, "run": True})

    assert preview.status_code == 200 and preview.json()["cycle_started"] is False
    assert [f["strategy_id"] for f in client.get("/api/fund/real").json()["funds"]] == [None, None]
    for body in ({"capital": 500_000}, {"only": "PEA"}, {"fee_flat": -2}, {"tier": "x"}):
        resp = client.post("/api/fund/real", json=body)
        assert resp.status_code == 400, (body, resp.text)


def test_a_strategy_can_also_be_created_as_a_real_fund_through_the_api(client):
    resp = client.post("/api/fund/strategies", json={"name": "À la main", "wrapper": "PEA", "initial_capital": 5_000, "opened_on": "2026-01-05",
                                                     "category": "real", "fee_flat": 1})
    assert resp.status_code == 200
    detail = client.get(f"/api/fund/strategies/{resp.json()['strategy_id']}/detail").json()
    assert detail["strategy"]["category"] == "real" and detail["strategy"]["fee_flat"] == 1.0
    assert client.post("/api/fund/strategies", json={"name": "X", "wrapper": "CTO", "initial_capital": 1_000, "opened_on": "2026-01-05",
                                                     "category": "bizarre"}).status_code == 400


def test_the_preview_query_accepts_the_new_pilot_settings(client):
    pea_id = next(r["strategy_id"] for r in (client.post("/api/fund/real", json={}), client.get("/api/fund/real"))[1].json()["funds"]
                  if r["kind"] == "PEA")

    ok = client.get(f"/api/fund/strategies/{pea_id}/autopilot/preview.html?tier=auc&min_position=300&auc_floor=0.55")
    none = client.get(f"/api/fund/strategies/{pea_id}/autopilot/preview.html?tier=auc&min_position=")
    bad = client.get(f"/api/fund/strategies/{pea_id}/autopilot/preview.html?min_position=-1")

    assert ok.status_code == 200 and none.status_code == 200 and bad.status_code == 400


def test_every_new_string_exists_in_both_languages_and_the_server_codes_are_translated():
    new = [k for k in i18n_fund.FUND_STRINGS if k.startswith(("fund_cat_", "fund_real_", "fund_grp_", "fund_flat_fee"))
           or k in ("fund_auto_tier_auc", "fund_auto_min_position", "fund_auto_min_position_none", "fund_auto_col_auc", "fund_auto_col_evidence")]
    assert len(new) > 20
    for key in new:
        assert i18n_fund.FUND_STRINGS[key]["fr"].strip() and i18n_fund.FUND_STRINGS[key]["en"].strip(), key
        assert key in i18n.STRINGS
    from patrick.fund import autopilot, selection
    for code in (*autopilot.LABELS, *(c for c in selection.LABELS if c in ("auc", "no_auc"))):
        assert f"fund_auto_code_{code}" in i18n.STRINGS, code
