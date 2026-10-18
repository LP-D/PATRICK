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
