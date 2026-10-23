"""Carte « en cours et file d'attente » (identique sur /ml, /dl, /rl) et bandeau défilant des plus fortes variations (toutes les pages)."""
from __future__ import annotations

import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import db, jobs
from patrick.webapp import alerts, i18n
from patrick.webapp.app import app

LAUNCH_PAGES = ("/ml", "/dl", "/rl")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    return TestClient(app)


def _machine_section(html: str) -> str:
    start = html.index('<section class="dash-panel dash-machine"')
    return html[start:html.index("</section>", start) + len("</section>")]


def _section_with_class(html: str, css_class: str) -> str:
    start = html.index(f'<section class="dash-panel {css_class}"')
    return html[start:html.index("</section>", start)]


# ---------------------------------------------------------------- carte en cours + file d'attente

def test_the_machine_card_is_identical_on_the_three_launch_pages(client):
    cards = {path: _machine_section(client.get(path).text) for path in LAUNCH_PAGES}
    assert cards["/ml"] == cards["/dl"] == cards["/rl"]
    for element in ('id="queue-panel"', 'id="queue-list"', 'id="clear-queue-btn"'):
        assert element in cards["/ml"]
    for element in ('id="pause-run-btn"', 'id="stop-run-btn"', 'id="machine-current"', 'id="machine-progress-fill"'):
        assert element not in cards["/ml"]                           # le run en cours se montre dans « Avancement », pas dans la file


@pytest.mark.parametrize("path", LAUNCH_PAGES)
def test_the_queue_follows_the_progress_panel_and_the_run_controls_live_in_it(client, path):
    html = client.get(path).text
    progress = _section_with_class(html, "dash-progress")
    assert 'id="queue-panel"' not in progress                        # la file est sa propre carte
    assert 'id="pause-run-btn"' in progress and 'id="stop-run-btn"' in progress   # pause / arrêt : dans « Avancement »
    assert html.count('id="queue-panel"') == 1 and html.count('id="stop-run-btn"') == 1   # un seul exemplaire par page
    assert html.index('class="dash-panel dash-progress"') < html.index('class="dash-panel dash-machine"')


@pytest.mark.parametrize("path", LAUNCH_PAGES)
def test_the_right_column_is_its_own_stack_not_rows_shared_with_the_settings_cell(client, path):
    """Posés dans la grille, les cadres de droite partageaient les rangées de la cellule de gauche (très haute) et s'écartaient."""
    html = client.get(path).text
    side = html.index('<div class="station-side">')
    assert html.index('class="dash-panel dash-settings"') < side < html.index('class="dash-panel dash-progress"')
    assert side < html.index('class="dash-panel dash-machine"')
    css = client.get("/static/patrick.css").text
    assert ".station-side { grid-column: 2; display: flex; flex-direction: column;" in css


@pytest.mark.parametrize("path", LAUNCH_PAGES)
def test_each_launch_page_loads_the_shared_machine_script(client, path):
    html = client.get(path).text
    assert '<script src="/static/machine.js?v=' in html
    if path != "/rl":                                                 # app.js s'y abonne pour suivre le run actif (ML et DL)
        assert html.index("/static/machine.js") < html.index("/static/app.js")
    assert "window.PatrickMachine" in client.get("/static/machine.js").text


def test_the_old_movers_panel_is_gone_from_the_launch_pages(client):
    for path in LAUNCH_PAGES:
        html = client.get(path).text
        assert "movers-columns" not in html and "dash-movers" not in html


def test_run_state_tells_the_family_and_the_target_of_each_job(client, tmp_path):
    ml_cfg = {"name": "GSPC_1", "objective": {"target_symbol": "^GSPC"}, "models": {"algos": ["XGBoost", "RandomForest"]}}
    dl_cfg = {"name": "GSPC_2", "objective": {"target_symbol": "^GSPC"}, "models": {"algos": ["MLP", "GRU"]}}
    rl_cfg = {"name": "NDX_rl_1", "kind": "rl", "objective": {"target_symbol": "^NDX"}}
    conn = db.connect()
    running = jobs.enqueue_job(conn, json.dumps(ml_cfg))
    jobs.claim_next_job(conn, os.getpid())                            # un worker vivant : un faux numéro passerait pour un worker disparu
    jobs.enqueue_job(conn, json.dumps(dl_cfg))
    jobs.enqueue_job(conn, json.dumps(rl_cfg))
    conn.close()

    state = client.get("/api/run-state").json()
    assert state["active_run"]["id"] == running
    assert (state["active_run"]["kind"], state["active_run"]["target"]) == ("ml", "^GSPC")
    assert [(q["name"], q["kind"], q["target"]) for q in state["queue"]] == [("GSPC_2", "dl", "^GSPC"), ("NDX_rl_1", "rl", "^NDX")]


def test_a_job_with_an_unreadable_config_still_shows_up_in_the_queue(client):
    conn = db.connect()
    jobs.enqueue_job(conn, "pas du json")
    conn.close()
    queued = client.get("/api/run-state").json()["queue"]
    assert len(queued) == 1 and queued[0]["kind"] == "ml" and queued[0]["target"] is None


# ---------------------------------------------------------------- bandeau des plus fortes variations

@pytest.fixture
def movers_cache(monkeypatch):
    snapshot = {
        "gainers": [{"symbol": "NVDA", "label": "NVIDIA", "pct": 12.3456}, {"symbol": "^N225", "label": "Nikkei 225", "pct": 3.1}],
        "losers": [{"symbol": "GC=F", "label": "Or (futures)", "pct": -4.5}],
        "updated_at": "2026-10-11 09:30", "error": None, "n_ranked": 3, "n_requested": 3,
    }
    monkeypatch.setattr(alerts, "_cache", snapshot)
    return snapshot


@pytest.mark.parametrize("path", ["/", "/ml", "/dl", "/rl", "/exploration", "/runs", "/vocabulary", "/reglages"])
def test_the_ticker_sits_at_the_top_of_every_page(client, movers_cache, path):
    response = client.get(path)
    assert response.status_code == 200
    html = response.text
    assert 'id="market-ticker"' in html and "/static/ticker.js" in html
    assert html.index('id="market-ticker"') < html.index('class="topbar"')       # au-dessus de la barre du haut


def test_the_ticker_lists_gainers_then_losers_with_a_non_colour_cue(client, movers_cache):
    html = client.get("/ml").text
    ticker = html[html.index('id="market-ticker"'):html.index('class="topbar"')]
    assert "hidden" not in ticker.split(">", 1)[0]
    assert re.search(r'data-symbol="NVDA".*?▲ \+12\.35%', ticker, re.DOTALL)
    assert re.search(r'data-symbol="GC=F".*?▼ -4\.50%', ticker, re.DOTALL)
    assert ticker.index("NVDA") < ticker.index("^N225") < ticker.index("GC=F")
    assert 'href="/targets/%5EN225"' in ticker                                   # lien vers la fiche de la cible
    assert "2026-10-11 09:30" in ticker                                          # fraîcheur lisible au survol


def test_the_ticker_is_hidden_until_the_ranking_exists(client, monkeypatch):
    monkeypatch.setattr(alerts, "_cache", {"gainers": [], "losers": [], "updated_at": None, "error": None, "n_ranked": 0, "n_requested": 0})
    html = client.get("/ml").text
    assert re.search(r'<div class="ticker" id="market-ticker"[^>]*\bhidden\b', html)


def test_pages_still_render_when_the_server_predates_the_ticker(client, monkeypatch):
    """Un serveur lancé avant la fusion relit les gabarits à chaud mais garde son ancien Python : sans `movers_snapshot`, la page doit
    s'afficher quand même (bandeau masqué), pas répondre 500."""
    from patrick.webapp.app import templates
    monkeypatch.delitem(templates.env.globals, "movers_snapshot")
    for path in ("/ml", "/runs", "/exploration"):
        response = client.get(path)
        assert response.status_code == 200
        assert re.search(r'<div class="ticker" id="market-ticker"[^>]*\bhidden\b', response.text)


def test_the_ticker_animation_stops_on_hover_and_for_reduced_motion(client):
    css = client.get("/static/patrick.css").text
    assert "@keyframes ticker-scroll" in css and "animation-play-state: paused" in css
    assert re.search(r"prefers-reduced-motion: reduce\)\s*\{\s*\.ticker-track\s*\{\s*animation:\s*none", css)
    assert "--ticker-dir: reverse" in css                                         # gauche -> droite, inversable en une ligne


def test_the_ticker_stays_on_screen_while_the_page_scrolls(client):
    """Collé en haut, sur toutes les pages : la barre du haut et tout ce qui se colle dessous se décalent de sa hauteur."""
    css = client.get("/static/patrick.css").text
    ticker_rule = css[css.index("\n.ticker {"):css.index("\n.ticker[hidden]")]
    assert "position: sticky" in ticker_rule and "top: 0" in ticker_rule
    assert ":root:has(.ticker:not([hidden])) { --ticker-h: 33px; }" in css
    topbar_rule = css[css.index("\n.topbar {"):css.index("\n.topbar-crumbs")]
    assert "top: var(--ticker-h)" in topbar_rule
    # plus aucun élément collé ne se cale sur la barre du haut seule : il passerait sous le bandeau
    assert not re.findall(r"(?:^|[^-a-z])top:[^;}]*--topbar-h", css, re.MULTILINE)
    assert len(re.findall(r"(?:^|[^-a-z])top:[^;}]*--stick-top", css, re.MULTILINE)) >= 3                 # section-index, run-panel, fund-preview


# ---------------------------------------------------------------- textes

@pytest.mark.parametrize("key", ["machine_title", "machine_idle", "movers_title", "movers_updated_at"])
def test_new_strings_exist_in_both_languages(key):
    assert i18n.translator("fr")(key) != key and i18n.translator("en")(key) != key
    assert i18n.translator("fr")(key) != i18n.translator("en")(key)


def test_browser_strings_for_the_card_reach_every_page():
    for path in ("/ml", "/dl", "/rl", "/runs"):
        keys = i18n.js_strings("fr", path)
        assert keys["machine_idle"] and keys["rlp_phase_rl_train"] and keys["queue_summary"]
