"""Calendrier économique (A17) : dates FRED stockées, décisions de taux reconnues dans les titres, repères posés sur la courbe d'un actif."""
from __future__ import annotations

import datetime as dt

import pytest
import requests

from patrick.data import econ_calendar as cal
from patrick.tracking import asset_events
from patrick.tracking import db as trackdb


@pytest.fixture
def conn(tmp_path):
    c = trackdb.connect(tmp_path / "t.db")
    yield c
    c.close()


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _Session:
    """Faux client : CPI (10) et emploi (50) répondent, PIB (53) en panne, le reste vide."""

    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params["release_id"])
        rid = params["release_id"]
        if rid == 10:
            return _Resp({"release_dates": [{"date": "2026-11-10"}, {"date": "2026-12-10"}, {"date": "2026-11-10"}]})
        if rid == 50:
            return _Resp({"release_dates": [{"date": "2026-12-04"}]})
        if rid == 53:
            return _Resp({}, status=500)
        return _Resp({"release_dates": []})


def _news(conn, source, day, title):
    conn.execute("INSERT INTO news_item (source, source_kind, external_id, published_at, first_seen_at, date_only, title, "
                 "summary, url, language, content_hash) VALUES (?, 'central_bank', ?, ?, ?, 0, ?, '', '', 'en', ?)",
                 (source, f"{day}:{title}", f"{day}T18:00:00+00:00", f"{day}T18:05:00+00:00", title, title))
    conn.commit()


def test_refresh_without_key_does_nothing(conn, monkeypatch):
    monkeypatch.delenv(cal.API_KEY_ENV, raising=False)
    assert cal.refresh(conn) == {"stored": 0, "errors": [], "skipped": True}


def test_refresh_stores_dates_and_survives_a_failing_release(conn):
    session = _Session()
    report = cal.refresh(conn, api_key="k", session=session)
    assert sorted(session.calls) == sorted(cal.RELEASES)
    assert report["stored"] == 3                      # doublon de l'API dédoublonné
    assert [name for name, _msg in report["errors"]] == ["fred:release:53"]
    assert cal.releases(conn) == [{"date": "2026-11-10", "label": "IPC"}, {"date": "2026-12-04", "label": "Emploi"},
                                  {"date": "2026-12-10", "label": "IPC"}]
    cal.refresh(conn, api_key="k", session=_Session())   # idempotent
    assert len(cal.releases(conn)) == 3


def test_decisions_match_real_titles_only(conn):
    _news(conn, "rss:fed_monetary", "2026-09-16", "Federal Reserve issues FOMC statement")
    _news(conn, "rss:fed_monetary", "2026-10-07", "Minutes of the Federal Open Market Committee, September 15-16, 2026")
    _news(conn, "rss:ecb_press", "2026-10-29", "Monetary policy decisions")
    _news(conn, "rss:ecb_press", "2026-10-30", "Christine Lagarde: Acting in time")
    _news(conn, "rss:boe_news", "2026-11-05", "Bank rate increased to 4% - November 2026 Monetary Policy Summary and Minutes")
    _news(conn, "rss:boe_news", "2026-11-20", "Minutes of the Market Participants Group meeting")
    _news(conn, "rss:boc_press", "2026-10-28", "Bank of Canada raises the policy rate by 25 basis points to 2½%")
    _news(conn, "rss:boc_press", "2026-11-12", "Bank of Canada publishes its 2027 schedule for policy interest rate announcement")
    assert cal.decisions(conn) == [{"date": "2026-09-16", "label": "Fed"}, {"date": "2026-10-28", "label": "BoC"},
                                   {"date": "2026-10-29", "label": "BCE"}, {"date": "2026-11-05", "label": "BoE"}]


@pytest.mark.parametrize(("symbol", "banks"), [
    ("^GSPC", ("Fed",)), ("AAPL", ("Fed",)), ("MC.PA", ("Fed", "BCE")), ("EURUSD=X", ("Fed", "BCE")), ("^FCHI", ("Fed", "BCE")),
    ("GBPUSD=X", ("Fed", "BoE")), ("^FTSE", ("Fed", "BoE")), ("SHOP.TO", ("Fed", "BoC")), ("EURGBP=X", ("Fed", "BCE", "BoE")),
])
def test_banks_for(symbol, banks):
    assert cal.banks_for(symbol) == banks


def test_chart_events_keep_market_movers_up_to_today(conn):
    cal.refresh(conn, api_key="k", session=_Session())
    conn.execute("INSERT INTO econ_release (day, release_id, label) VALUES ('2026-11-10', 54, 'PCE')")   # pas sur la courbe
    _news(conn, "rss:fed_monetary", "2026-11-10", "Federal Reserve issues FOMC statement")
    _news(conn, "rss:ecb_press", "2026-10-29", "Monetary policy decisions")
    today = dt.date(2026, 11, 25)
    assert cal.chart_events(conn, "^GSPC", today) == [{"date": "2026-11-10", "kind": "macro", "label": "IPC·Fed"}]
    assert cal.chart_events(conn, "MC.PA", today) == [{"date": "2026-10-29", "kind": "macro", "label": "BCE"},
                                                      {"date": "2026-11-10", "kind": "macro", "label": "IPC·Fed"}]


def test_asset_events_merge_macro_and_can_skip_it(conn, monkeypatch):
    monkeypatch.setattr(cal, "chart_events", lambda c, s: [{"date": "2026-11-10", "kind": "macro", "label": "IPC"}])
    assert asset_events.events(conn, "^GSPC") == [{"date": "2026-11-10", "kind": "macro", "label": "IPC"}]
    assert asset_events.events(conn, "^GSPC", macro=False) == []


def test_agenda_upcoming_and_recent_decisions(conn):
    assert cal.agenda(conn, dt.date(2026, 11, 25))["has_releases"] is False
    cal.refresh(conn, api_key="k", session=_Session())
    _news(conn, "rss:boe_news", "2026-11-05", "Bank rate increased to 4% - November 2026 Monetary Policy Summary and Minutes")
    _news(conn, "rss:boe_news", "2026-07-30", "Bank Rate maintained at 3.75% - July 2026 Monetary Policy Summary")   # trop ancien
    ag = cal.agenda(conn, dt.date(2026, 11, 25))
    assert ag["has_releases"] is True
    assert [(e["date"], e["label"], e["in_days"]) for e in ag["upcoming"]] == [("2026-12-04", "Emploi", 9), ("2026-12-10", "IPC", 15)]
    assert ag["decisions"] == [{"date": "2026-11-05", "label": "BoE"}]


def test_news_refresh_skips_calendar_when_a_fetcher_is_injected(conn, monkeypatch):
    from patrick.text import service

    called = []
    monkeypatch.setattr(cal, "refresh", lambda *a, **k: called.append(1) or {"stored": 0, "errors": [], "skipped": False})
    report = service.refresh(conn, feeds=[], fetch=lambda url: b"", bodies=False, score=False, settings={})
    assert called == [] and report["calendar"]["skipped"] is True
