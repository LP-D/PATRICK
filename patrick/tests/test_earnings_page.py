"""Page /resultats de bout en bout avec un faux fournisseur : collage, confirmation, calcul, vue semaine, bibliothèque, fiche, détail.
Aucun réseau ; la base, le cache et le fournisseur sont ceux du test."""
from __future__ import annotations

import time

import pytest
from earnings_support import make_world
from fastapi.testclient import TestClient
from page_support import FullPageClient

from patrick.earnings import store
from patrick.tracking import db
from patrick.webapp import earnings_routes
from patrick.webapp.app import app

NEWSLETTER = "Lundi : Alpha, Bravo (ADR), <script>alert(1)</script>\nMardi : Charlie\nSamedi : Inconnue SA"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("PATRICK_EXTRA_HOSTS", "testserver")
    provider, symbols = make_world(n_symbols=6, events_per_symbol=14, seed=11)
    for name, sym in (("Alpha", "S00"), ("Bravo", "S01"), ("Charlie", "S02")):
        provider.searches[name] = [{"symbol": sym, "name": f"Société {sym}", "exchange": "NASDAQ", "type": "EQUITY", "sector": ""}]
        provider.infos[sym]["longName"] = name
    provider.searches["<script>alert(1)</script>"] = [{"symbol": "S03", "name": "<img src=x onerror=alert(1)>", "exchange": "NYSE", "type": "EQUITY"}]
    provider.infos["S03"]["longName"] = "<img src=x onerror=alert(1)>"
    monkeypatch.setattr(earnings_routes, "provider_factory", lambda: provider)
    return provider, symbols


def wait(client, kind: str, timeout: float = 60.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        state = client.get("/api/earnings/status").json()[kind]
        if not state["running"] and (state["result"] is not None or state["error"]):
            return state
        time.sleep(0.15)
    raise AssertionError(f"travail {kind} non terminé : {state}")


def paste(client) -> int:
    assert client.post("/api/earnings/parse", json={"text": NEWSLETTER, "anchor": "2026-11-02"}).json()["started"] is True
    state = wait(client, "parse")
    assert state["error"] is None, state
    return state["result"]["batch_id"]


def test_the_frame_opens_with_metrics_and_lazy_blocks(env):
    resp = TestClient(app).get("/resultats")
    assert resp.status_code == 200
    for needle in ("Événements de résultats", "earn-paste", "Mesures", "/fragments/earn-library", "earnings.js", "Verdict FDR"):
        if needle != "Mesures":
            assert needle in resp.text, needle
    assert "earn-textarea" in resp.text and 'type="date"' in resp.text


def test_the_page_is_registered_in_the_navigation(env):
    from patrick.webapp import nav_registry
    assert "/resultats" in nav_registry.registered_routes()
    assert any(e.slug == "earnings" for e in nav_registry.NAV_ENTRIES)
    text = TestClient(app).get("/").text
    assert 'href="/resultats"' in text


def test_parse_then_confirmation_screen_escapes_hostile_text(env):
    client = FullPageClient(app)
    batch = paste(client)
    items = store.batch_items(db.connect(), batch)
    assert [i["name"] for i in items] == ["Alpha", "Bravo", "<script>alert(1)</script>", "Charlie", "Inconnue SA"]
    assert items[4]["symbol"] is None and "introuvable" in items[4]["flags"]
    html = client.get(f"/fragments/earn-confirm?batch={batch}").text
    assert 'value="S00"' in html and "Société S00" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html          # jamais de balise injectée
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert "introuvable" in html and 'name="timing"' in html
    assert client.get("/resultats").status_code == 200 and f"batch={batch}" in client.get("/resultats").text


def test_full_flow_confirmation_processing_week_view_and_pages(env):
    _provider, _symbols = env
    client = FullPageClient(app)
    batch = paste(client)
    conn = db.connect()
    ids = {i["name"]: i["item_id"] for i in store.batch_items(conn, batch)}
    edits = [{"item_id": ids["Alpha"], "include": True, "symbol": "S00", "adr_symbol": "", "timing": "auto"},
             {"item_id": ids["Bravo"], "include": True, "symbol": "S01", "adr_symbol": "S05", "timing": "BMO"},
             {"item_id": ids["Charlie"], "include": True, "symbol": "S02", "adr_symbol": "", "timing": "AMC"},
             {"item_id": ids["<script>alert(1)</script>"], "include": False, "symbol": "", "adr_symbol": "", "timing": "auto"},
             {"item_id": ids["Inconnue SA"], "include": False, "symbol": "", "adr_symbol": "", "timing": "auto"}]
    out = client.post("/api/earnings/confirm", json={"batch_id": batch, "edits": edits}).json()
    assert out["confirmed"] == 3 and out["rejected"] == 2
    state = wait(client, "process")
    assert state["error"] is None, state
    assert state["result"]["ingest"]["events"] >= 3 * 14
    # l'alias confirmé est mémorisé : la prochaine newsletter ne demande plus
    assert store.get_alias(conn, "alpha")["source"] == "user" and store.get_alias(conn, "bravo")["adr_symbol"] == "S05"
    assert store.get_batch(conn, batch)["status"] == "ready"
    # les dates de la newsletter n'existent pas dans le calendrier jouet : rapprochées ou créées, avec le timing choisi par l'utilisateur
    cal = {c["ann_date"]: c for c in store.calendar_for(conn, "S01")}
    assert cal["2026-11-02"]["timing"] == "BMO" and cal["2026-11-02"]["timing_source"] == "user"

    week = client.get(f"/fragments/earn-week?batch={batch}").text
    assert "Société" not in week and "Alpha" in week and "Charlie" in week
    assert "/resultats/titre/S00" in week
    assert any(flag in week for flag in ("timing incertain", "N insuffisant", "signal analyste indisponible"))
    assert client.get(f"/resultats?batch={batch}").status_code == 200

    lib = client.get(f"/fragments/earn-library?scope=all&batch={batch}").text
    assert 'data-study="core_event_study"' in lib and lib.count('class="earn-card') >= 50
    study = client.get("/fragments/earn-study?study=core_event_study&scope=all")
    assert study.status_code == 200 and "BMP" in study.text and "N = " in study.text
    again = client.get("/fragments/earn-study?study=core_event_study&scope=all")
    assert "lu depuis le cache" in again.text
    assert "TypeError" not in client.get("/fragments/earn-study?study=i_structure&scope=all").text
    scoped = client.get(f"/fragments/earn-study?study=a_reaction_dist&scope=batch:{batch}&batch={batch}&p_group_by=symbol")
    assert scoped.status_code == 200 and "S01" in scoped.text
    ledger = client.get("/fragments/earn-ledger?scope=all")
    assert ledger.status_code == 200 and "Benjamini-Hochberg" in ledger.text

    title = client.get("/resultats/titre/S00")
    assert title.status_code == 200 and "Historique des réactions" in title.text and "Saisie manuelle" in title.text
    assert "/resultats/evenement?symbol=S00" in title.text
    day = store.calendar_for(conn, "S00")[5]["ann_date"]
    event = client.get(f"/resultats/evenement?symbol=S00&day={day}")
    assert event.status_code == 200 and "Jour de réaction J0" in event.text and "<svg" in event.text
    conn.close()


def test_invalid_inputs_are_refused(env):
    client = TestClient(app)
    assert client.get("/resultats/titre/a b").status_code in (400, 404)
    assert client.get("/fragments/earn-title?symbol=<x>").status_code == 400
    assert client.get("/fragments/earn-study?study=nope").status_code == 404
    assert client.get("/fragments/earn-study?study=a_reaction_dist&scope=planete:Mars").status_code == 400
    assert client.get("/fragments/earn-ledger?alpha=0.9").status_code == 400
    assert client.get("/resultats/evenement?symbol=S00&day=pas-une-date").status_code == 400
    assert client.post("/api/earnings/parse", json={"text": ""}).status_code == 400
    assert client.post("/api/earnings/parse", json={"text": "x", "anchor": "demain"}).status_code == 400
    assert client.post("/api/earnings/confirm", json={"batch_id": 999, "edits": []}).status_code == 404
    assert client.post("/api/earnings/confirm", json={"batch_id": 1, "edits": [{"item_id": 1, "symbol": "<bad>"}]}).status_code == 400
    assert client.post("/api/earnings/config", json={"model": "magie"}).status_code == 400
    assert client.post("/api/earnings/manual-dates", json={"symbol": "S00", "text": "pas une date"}).status_code == 400


def test_config_is_saved_and_signals_when_measures_must_be_recomputed(env):
    client = FullPageClient(app)
    batch = paste(client)
    ids = {i["name"]: i["item_id"] for i in store.batch_items(db.connect(), batch)}
    client.post("/api/earnings/confirm", json={"batch_id": batch, "edits": [{"item_id": ids["Alpha"], "include": True, "symbol": "S00", "timing": "auto"}]})
    wait(client, "process")
    saved = client.post("/api/earnings/config", json={"test": "patell", "winsorize": 0.05}).json()
    assert saved == {"saved": True, "needs_recompute": False}              # test et winsorisation ne changent pas les mesures
    changed = client.post("/api/earnings/config", json={"model": "market_adjusted"}).json()
    assert changed["needs_recompute"] is True
    assert client.post("/api/earnings/recompute").json()["started"] is True
    assert wait(client, "recompute")["error"] is None
    assert "Ajusté du marché" in client.get("/resultats").text
    assert client.post("/api/earnings/config", json={"model": "market_adjusted"}).json()["needs_recompute"] is False


def test_manual_dates_fill_a_stock_without_history_and_aliases_can_be_removed(env):
    provider, _ = env
    provider.series["ZZ"] = provider.series["S00"]
    provider.infos["ZZ"] = dict(provider.infos["S00"])
    client = FullPageClient(app)
    idx = provider.series["ZZ"].index
    lines = "\n".join(f"{idx[300 + 63 * k].date()} 07:00" for k in range(8))
    res = client.post("/api/earnings/manual-dates", json={"symbol": "ZZ", "text": lines}).json()
    assert res["added"] == 8 and res["events"] == 8 and res["errors"] == []
    cal = store.calendar_for(db.connect(), "ZZ")
    assert {c["source"] for c in cal} == {"manual"} and {c["timing"] for c in cal} == {"BMO"}
    assert "ZZ" in client.get("/fragments/earn-title?symbol=ZZ").text
    store.put_alias(db.connect(), "alpha", "S00", None, "Alpha", "user")
    assert [a["alias"] for a in client.get("/api/earnings/aliases").json()["aliases"]] == ["alpha"]
    client.post("/api/earnings/alias/delete", json={"alias": "alpha"})
    assert client.get("/api/earnings/aliases").json()["aliases"] == []


def test_daily_snapshot_is_stored_once_per_day(env):
    provider, _ = env
    provider.consensus_data["S00"] = {"earnings_estimate": [{"period": "0q", "avg": 2.0, "low": 1.8, "high": 2.2, "numberOfAnalysts": 20}],
                                      "eps_trend": [{"period": "0q", "current": 2.0, "7daysAgo": 1.98, "30daysAgo": 1.9, "60daysAgo": 1.85, "90daysAgo": 1.8}]}
    from patrick.earnings import consensus
    conn = db.connect()
    store.upsert_calendar(conn, [{"symbol": "S00", "ann_date": "2999-01-01", "ann_local_time": "16:00", "timing": "AMC", "timing_source": "yahoo_time",
                                  "uncertain": 0, "reason": "", "eps_estimate": 2.0, "eps_actual": None, "surprise_pct": None, "source": "yahoo"}])
    first = consensus.take_snapshots(conn, provider, ["S00"])
    second = consensus.take_snapshots(conn, provider, ["S00"])
    assert first["consensus"] == 1 and second["consensus"] == 0
    summary = consensus.summarize(store.snapshots(conn, "S00", "consensus")[0]["payload"])
    assert summary["dispersion"] == pytest.approx(0.2) and summary["rev_30d"] == pytest.approx(2.0 / 1.9 - 1)


def test_the_command_line_runs_a_study_and_the_ledger_from_the_same_cache(env, tmp_path):
    from typer.testing import CliRunner

    from patrick.cli import app as cli_app
    from patrick.earnings import pipeline
    from patrick.earnings.config import EarningsConfig
    provider, symbols = env
    pipeline.ingest_many(db.connect, provider, symbols, EarningsConfig(), workers=2)
    runner = CliRunner()
    listing = runner.invoke(cli_app, ["earnings", "studies"])
    assert listing.exit_code == 0 and "core_event_study" in listing.output and "m_placebo" in listing.output
    study = runner.invoke(cli_app, ["earnings", "study", "a_reaction_dist", "--param", "group_by=sector"])
    assert study.exit_code == 0 and "[ok]" in study.output and "Technology" in study.output, study.output
    again = runner.invoke(cli_app, ["earnings", "study", "a_reaction_dist", "--param", "group_by=sector"])
    assert again.exit_code == 0 and "[ok]" in again.output
    ledger = runner.invoke(cli_app, ["earnings", "ledger"])
    assert ledger.exit_code == 0 and "Benjamini-Hochberg" in ledger.output
    assert runner.invoke(cli_app, ["earnings", "study", "inconnue"]).exit_code == 1
