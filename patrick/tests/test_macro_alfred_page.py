"""Page Macro : tableau FRED contre ALFRED (`tracking/alfred_report.py`, `/fragments/macro-alfred`). Lecture du cache local
uniquement ; le calcul réseau est lancé par un bouton et testé ici avec un faux comparateur."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from patrick.cache_manager import LocalCache
from patrick.tracking import alfred_report
from patrick.webapp.app import app

ROWS = [
    {"series": "NFCI", "label": "NFCI", "section": "credit", "mode": "hybrid", "first_vintage": "2011-05-25", "n_compared": 802,
     "share_revised": 0.998, "mean_abs_revision": 0.156, "max_abs_revision": 0.536, "revision_vs_move": 4.875,
     "lag_real_days": 5.0, "lag_assumed_days": 7.0, "lost_years_if_alfred_only": 11.4},
    {"series": "SP500", "label": "SP500", "section": "markets", "mode": "fred", "n_compared": 0, "note": "absente d'ALFRED"},
    {"series": "GDP", "label": "GDP", "section": "key", "mode": "alfred", "first_vintage": "1991-12-04", "n_compared": 106,
     "share_revised": 1.0, "mean_abs_revision": 408.7, "revision_vs_move": 1.35, "lag_real_days": 119.0,
     "lag_assumed_days": 120.0, "lost_years_if_alfred_only": 0.0},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setattr(alfred_report, "_state", {"running": False, "done": 0, "total": 0, "error": None, "started_at": None})
    return TestClient(app, base_url="http://127.0.0.1:8000")


def _store_report():
    LocalCache().save_json(alfred_report.CACHE_KEY, {"computed_at": "2026-10-10T08:00:00+00:00", "start": "2000-01-01",
                                                       "rows": ROWS, "summary": alfred_report.summarize(ROWS)})


def test_the_macro_page_hosts_the_alfred_block(client):
    html = client.get("/macro").text
    assert "/fragments/macro-alfred" in html and "macro_alfred.js" in html


def test_the_fragment_without_a_report_invites_to_compute_it(client, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    html = client.get("/fragments/macro-alfred").text
    assert "Rapport pas encore calculé" in html and 'id="alfred-refresh"' in html and "disabled" not in html.split('id="alfred-refresh"')[1][:200]


def test_the_fragment_warns_and_disables_the_button_without_a_fred_key(client, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    html = client.get("/fragments/macro-alfred").text
    assert "FRED_API_KEY est absente" in html and "disabled" in html.split('id="alfred-refresh"')[1][:260]


def test_the_fragment_shows_modes_revisions_and_the_summary(client, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    _store_report()
    html = client.get("/fragments/macro-alfred").text
    assert "ALFRED + FRED avant" in html and "FRED seul" in html
    assert "100 %" in html and "4.88" in html                         # GDP entièrement révisé ; NFCI : 4,9 fois un mouvement
    assert "Calculé le 2026-10-10 08:00" in html
    assert "11.4" in html                                              # années d'historique perdues si ALFRED seul (NFCI)


def test_the_english_fragment_is_translated(client, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    _store_report()
    html = client.get("/fragments/macro-alfred?lang=en").text
    assert "FRED vs ALFRED" in html and "Real / assumed lag" in html and "ALFRED + FRED before" in html


def test_refresh_requires_a_fred_key(client, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert client.post("/api/macro/alfred-refresh").status_code == 409


def test_refresh_runs_in_the_background_one_at_a_time(client, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr(alfred_report.alfred, "compare_with_fred",
                        lambda sid, start, key, refresh=False: (time.sleep(0.02), {"series": sid, "mode": "fred", "n_compared": 0})[1])
    monkeypatch.setattr(alfred_report, "series_to_compare", lambda: [("A", "A", "key"), ("B", "B", "key"), ("C", "C", "key")])
    first = client.post("/api/macro/alfred-refresh").json()
    assert first["started"] is True and first["total"] == 3
    deadline = time.time() + 5
    while client.get("/api/macro/alfred-status").json()["running"] and time.time() < deadline:
        time.sleep(0.05)
    state = client.get("/api/macro/alfred-status").json()
    assert state["running"] is False and state["done"] == 3 and state["error"] is None
    assert [r["series"] for r in alfred_report.load_report()["rows"]] == ["A", "B", "C"]


def test_summary_counts_modes_and_ranks_the_most_revised():
    sm = alfred_report.summarize(ROWS)
    assert sm["n"] == 3 and sm["modes"] == {"alfred": 1, "hybrid": 1, "fred": 1} and sm["n_revised"] == 2
    assert [r["series"] for r in sm["most_revised"]] == ["NFCI", "GDP"]


def test_the_macro_page_title_is_clean_and_the_script_is_in_the_body(client):
    html = client.get("/macro").text
    title = html.split("<title>")[1].split("</title>")[0]
    assert "<script" not in title and "Macro (FRED)" in title
    assert html.count("macro_alfred.js") == 1 and html.index("macro_alfred.js") > html.index("</main>") - 4000


def test_a_rebased_series_is_labelled_and_counted(client, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    rows = [*ROWS, {"series": "PCEPI", "label": "PCE_Price_Index", "section": "inflation", "mode": "fred", "level_break": 8.2,
                    "first_vintage": "1999-01-29", "n_compared": 314, "share_revised": 1.0, "mean_abs_revision": 12.0,
                    "revision_vs_move": 81.0}]
    LocalCache().save_json(alfred_report.CACHE_KEY, {"computed_at": "2026-10-10T08:00:00+00:00", "start": "2000-01-01",
                                                       "rows": rows, "summary": alfred_report.summarize(rows)})
    html = client.get("/fragments/macro-alfred").text
    assert "FRED seul (niveau rebasé)" in html and "1 au niveau rebasé" in html
    assert alfred_report.summarize(rows)["n_rebased"] == 1
