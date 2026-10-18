"""Page /news : cadre immédiat (chiffres de tête, fenêtre, bouton), tableaux par fragments, collecte en arrière-plan, étude
d'événement textuelle à la demande — sans réseau ni écriture dans le vrai cache."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from page_support import FullPageClient

from patrick.text import service, sources, store
from patrick.tracking import db
from patrick.webapp import news_routes
from patrick.webapp.app import app

NOW = pd.Timestamp.now(tz="UTC").floor("s")


def _rss(*entries):
    items = "".join(f"<item><title>{t}</title><link>https://x.example/{i}</link><description>{d}</description>"
                    f"<pubDate>{p}</pubDate></item>" for i, (t, d, p) in enumerate(entries))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{items}</channel></rss>'


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    stamp = (NOW - pd.Timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    press = _rss(("Apple shares surge as profit beats forecasts", "Strong demand", stamp),
                 ("Oil prices plunge after sanctions are lifted", "Brent falls", stamp))
    fed = _rss(("FOMC statement", "Further rate hikes may be appropriate; inflation remains elevated.", stamp))
    conn = db.connect(path)
    service.refresh(conn, feeds=[sources.Feed("press", "https://press.example/rss", "news"),
                                 sources.Feed("fedx", "https://fed.example/rss", "central_bank")],
                    fetch=lambda u: press if "press" in u else fed, now=NOW, with_gdelt=False)
    conn.close()
    return path


def test_the_frame_opens_with_figures_and_lazy_blocks(seeded):
    resp = TestClient(app).get("/news")
    assert resp.status_code == 200
    for needle in ("News et sentiment", "/fragments/news-assets", "/fragments/news-feed", "/fragments/news-central",
                   "Actualiser", "Méthode et limites"):
        assert needle in resp.text
    assert "Sentiment par actif" in resp.text and "surge as profit" not in resp.text      # les titres arrivent par fragment


def test_an_empty_database_still_renders_the_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    resp = TestClient(app).get("/news")
    assert resp.status_code == 200 and "Nouvelles en base" in resp.text


def test_assets_fragment_lists_sentiment_per_linked_asset(seeded):
    resp = TestClient(app).get("/fragments/news-assets", params={"window": 7})
    assert resp.status_code == 200
    assert "AAPL" in resp.text and "CL=F" in resp.text
    assert "/news?symbol=AAPL" in resp.text


def test_feed_fragment_shows_scores_events_and_filters_by_symbol(seeded):
    client = TestClient(app)
    everything = client.get("/fragments/news-feed").text
    assert "Apple shares surge" in everything and "Oil prices plunge" in everything
    assert "sanction" in everything
    only = client.get("/fragments/news-feed", params={"symbol": "AAPL"}).text
    assert "Apple shares surge" in only and "Oil prices plunge" not in only


def test_central_bank_fragment_shows_the_hawkish_tone(seeded):
    text = TestClient(app).get("/fragments/news-central").text
    assert "FOMC statement" in text and "+1.00" in text


def test_full_page_shows_every_block(seeded):
    resp = FullPageClient(app).get("/news")
    assert "Apple shares surge" in resp.text and "FOMC statement" in resp.text and "AAPL" in resp.text


def test_bad_parameters_are_refused(seeded):
    client = TestClient(app)
    assert client.get("/fragments/news-assets", params={"window": 999}).status_code == 400
    assert client.get("/fragments/news-feed", params={"symbol": "<script>"}).status_code == 400
    assert client.get("/fragments/news-event-study", params={"symbol": "../x"}).status_code == 400


def test_refresh_runs_in_the_background_and_reports_its_result(seeded, monkeypatch):
    gate = {"go": False}

    def runner():
        while not gate["go"]:
            time.sleep(0.01)
        return {"added": 4, "scored": 4, "errors": [("down", "hors ligne")], "skipped_without_date": 0}

    monkeypatch.setattr(news_routes, "refresh_runner", runner)
    client = TestClient(app)
    first = client.post("/api/newsflow/refresh").json()
    again = client.post("/api/newsflow/refresh").json()
    assert first["started"] is True and again["started"] is False                      # une seule collecte à la fois
    assert client.get("/api/newsflow/status").json()["running"] is True
    gate["go"] = True
    for _ in range(200):
        status = client.get("/api/newsflow/status").json()
        if not status["running"]:
            break
        time.sleep(0.01)
    assert status["running"] is False and status["result"]["added"] == 4 and status["error"] is None


def test_a_failing_collection_is_reported_not_raised(seeded, monkeypatch):
    def runner():
        raise OSError("réseau coupé")

    monkeypatch.setattr(news_routes, "refresh_runner", runner)
    client = TestClient(app)
    client.post("/api/newsflow/refresh")
    for _ in range(200):
        status = client.get("/api/newsflow/status").json()
        if not status["running"]:
            break
        time.sleep(0.01)
    assert "réseau coupé" in status["error"]


# --- étude d'événement textuelle --------------------------------------------------------------------------------------------

def _prices_with_jumps(days, jump_days, size=0.03, seed=1):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0002, 0.01, len(days))
    for d in jump_days:
        r[days.get_loc(d)] += size
    return pd.Series(100 * np.exp(np.cumsum(r)), index=days)


def test_event_study_asks_for_an_asset_first(seeded):
    assert "Choisis un actif" in TestClient(app).get("/fragments/news-event-study").text


def test_event_study_does_not_download_missing_prices(seeded, monkeypatch):
    monkeypatch.setattr(news_routes, "price_loader", lambda symbol: None)
    assert "absents du cache" in TestClient(app).get("/fragments/news-event-study", params={"symbol": "AAPL"}).text


def test_event_study_needs_enough_strong_stories(seeded, monkeypatch):
    days = pd.bdate_range("2018-01-01", periods=1500)
    monkeypatch.setattr(news_routes, "price_loader", lambda symbol: _prices_with_jumps(days, []))
    text = TestClient(app).get("/fragments/news-event-study", params={"symbol": "AAPL"}).text
    assert "minimum" in text and "Nouvelles positives" not in text


def test_event_study_reports_the_reaction_when_there_are_enough_events(seeded, monkeypatch):
    days = pd.bdate_range("2018-01-01", periods=1500)
    jumps = list(days[300:1400:50])
    monkeypatch.setattr(news_routes, "price_loader", lambda symbol: _prices_with_jumps(days, jumps))
    conn = db.connect(seeded)
    items = [store.NewsItem("rss:t", "news", f"e{i}", (d + pd.Timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            f"Distinct headline number {i} about Apple {'x' * i}", first_seen_at=(d + pd.Timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ"))
             for i, d in enumerate(jumps)]
    store.add_items(conn, items)
    rows = conn.execute("SELECT item_id FROM news_item WHERE source = 'rss:t'").fetchall()
    store.save_scores(conn, service.LEXICON, service.lexicon_version(), {r[0]: (0.8, None) for r in rows})
    store.save_scores(conn, service.NOVELTY, service.VERSION, {r[0]: (1.0, None) for r in rows})
    store.save_links(conn, [(r[0], "AAPL", "name") for r in rows])
    conn.close()
    text = TestClient(app).get("/fragments/news-event-study", params={"symbol": "AAPL"}).text
    assert "Nouvelles positives" in text and "Rendement anormal cumulé" in text
    assert "Moins de 30 événements" in text
