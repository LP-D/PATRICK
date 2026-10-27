"""`patrick news refresh|summary` : collecte et lecture du magasin de nouvelles, sans réseau dans les tests."""
from __future__ import annotations

import pandas as pd
from typer.testing import CliRunner

from patrick.cli import app
from patrick.text import sources
from patrick.tracking import db as trackdb

FRESH = pd.Timestamp.now(tz="UTC").strftime("%a, %d %b %Y %H:%M:%S GMT")
RSS = ('<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>'
       f"<item><title>Apple shares surge as profit beats forecasts</title><link>https://x.example/1</link><pubDate>{FRESH}</pubDate></item>"
       "</channel></rss>")


def test_refresh_collects_scores_and_reports(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    monkeypatch.setattr(sources, "fetch_url", lambda url, timeout=20.0: RSS)
    monkeypatch.setattr(sources, "DEFAULT_FEEDS", (sources.Feed("press", "https://press.example/rss", "news"),))
    result = CliRunner().invoke(app, ["news", "refresh"])
    assert result.exit_code == 0, result.output
    assert "1 nouvelle(s) ajoutée(s)" in result.output and "1 notée(s)" in result.output
    conn = trackdb.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM news_item").fetchone()[0] == 1
        assert conn.execute("SELECT symbol FROM news_link").fetchall() == [("AAPL",)]
    finally:
        conn.close()


def test_refresh_reports_failing_sources_and_still_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))

    def boom(url, timeout=20.0):
        raise OSError("hors ligne")

    monkeypatch.setattr(sources, "fetch_url", boom)
    monkeypatch.setattr(sources, "DEFAULT_FEEDS", (sources.Feed("press", "https://press.example/rss", "news"),))
    result = CliRunner().invoke(app, ["news", "refresh"])
    assert result.exit_code == 0 and "press" in result.output and "hors ligne" in result.output


def test_summary_prints_the_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setattr(sources, "fetch_url", lambda url, timeout=20.0: RSS)
    monkeypatch.setattr(sources, "DEFAULT_FEEDS", (sources.Feed("press", "https://press.example/rss", "news"),))
    CliRunner().invoke(app, ["news", "refresh"])
    out = CliRunner().invoke(app, ["news", "summary"]).output
    assert "Nouvelles en base : 1" in out and "Rattachées à un actif : 1" in out


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(sources, "fetch_url", lambda url, timeout=20.0: RSS)
    monkeypatch.setattr(sources, "DEFAULT_FEEDS", (sources.Feed("press", "https://press.example/rss", "news"),))


def test_readiness_says_how_far_the_history_is(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    empty = CliRunner().invoke(app, ["news", "readiness"])
    assert empty.exit_code == 0 and "Aucune nouvelle utilisable" in empty.output
    CliRunner().invoke(app, ["news", "refresh"])
    out = CliRunner().invoke(app, ["news", "readiness"]).output
    assert "1 séance(s) d'historique sur 250 requises" in out and "Il manque 249 séance(s)" in out
    assert "pour AAPL" in CliRunner().invoke(app, ["news", "readiness", "--symbol", "AAPL"]).output


def test_lexicon_command_plugs_validates_and_clears_a_dictionary(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    CliRunner().invoke(app, ["news", "refresh"])
    shown = CliRunner().invoke(app, ["news", "lexicon"]).output
    assert "Lexique actif : builtin-fr-en-reduced-2" in shown and "1 / 1" in shown

    bad = tmp_path / "bad.csv"
    bad.write_text("Mot,Autre\nx,1\n", encoding="utf-8")
    refused = CliRunner().invoke(app, ["news", "lexicon", str(bad)])
    assert refused.exit_code == 1 and "Dictionnaire refusé" in refused.output
    assert not (tmp_path / "settings.json").exists()

    lm = tmp_path / "lm.csv"
    lm.write_text("Word,Negative,Positive,Uncertainty,Litigious\nSURGE,0,2009,0,0\nPROFIT,0,2009,0,0\nBEATS,0,0,0,0\n", encoding="utf-8")
    plugged = CliRunner().invoke(app, ["news", "lexicon", str(lm)])
    assert plugged.exit_code == 0, plugged.output
    assert "Dictionnaire branché : lm:lm.csv (2 mots positifs, 0 négatifs)" in plugged.output
    assert "Lexique actif : lm:lm.csv" in plugged.output
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM news_score WHERE scorer = 'lexicon' AND version = 'lm:lm.csv'").fetchone()[0] == 1
    finally:
        conn.close()

    cleared = CliRunner().invoke(app, ["news", "lexicon", "--clear"])
    assert "Lexique intégré rétabli" in cleared.output and "Lexique actif : builtin" in cleared.output


def test_refresh_reports_the_central_bank_pages_it_read(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    fed_rss = RSS.replace("https://x.example/1", "https://www.federalreserve.gov/newsevents/pressreleases/monetary1.htm")
    page = '<div id="article"><p>The Committee decided to raise the target range. Inflation remains elevated.</p></div>'
    monkeypatch.setattr(sources, "DEFAULT_FEEDS", (sources.Feed("fed", "https://www.federalreserve.gov/feeds/f.xml", "central_bank"),))
    monkeypatch.setattr(sources, "fetch_url", lambda url, timeout=20.0: page if url.endswith(".htm") else fed_rss)

    out = CliRunner().invoke(app, ["news", "refresh"]).output

    assert "Pages de banque centrale lues : 1 (0 échec(s), 0 ignorée(s))" in out
