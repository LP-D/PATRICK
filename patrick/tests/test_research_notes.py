"""Carnet de recherche (`patrick/tracking/research_notes.py`, migration 0041, `/carnet`, section « Carnet » d'un run)."""
from __future__ import annotations

import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import registry
from patrick.tracking import db as trackdb
from patrick.tracking import research_notes as rn
from patrick.webapp.app import app


@pytest.fixture
def conn(tmp_path):
    return trackdb.connect(str(tmp_path / "patrick.db"))


def test_create_normalizes_and_validates(conn):
    nid = rn.create(conn, "hypothesis", "  Le momentum bat la persistance sur GC=F  ", "texte", "Momentum, GC=F ; momentum,  énergie", "GC=F", "5", "r1")
    n = rn.list_notes(conn)[0]
    assert n["note_id"] == nid and n["title"] == "Le momentum bat la persistance sur GC=F" and n["horizon"] == 5
    assert n["tags"] == ["momentum", "gcf", "énergie"] and n["status"] == "open" and n["revisions"] == 0
    for bad, code in (({"kind": "x", "title": "t"}, "bad_kind"), ({"kind": "note", "title": "  "}, "title_required"), ({"kind": "note", "title": "t", "horizon": "abc"}, "bad_horizon")):
        with pytest.raises(rn.NoteError, match=code):
            rn.create(conn, **bad)


def test_update_changes_status_and_counts_revisions_but_keeps_creation_date(conn):
    nid = rn.create(conn, "hypothesis", "H1")
    created = rn.list_notes(conn)[0]["created_at"]
    rn.update(conn, nid, status="confirmed")
    rn.update(conn, nid, status="confirmed")                     # inchangé : pas de révision de plus
    rn.update(conn, nid, body="vu sur 3 plis", tags="a,b")
    n = rn.list_notes(conn)[0]
    assert n["status"] == "confirmed" and n["revisions"] == 2 and n["created_at"] == created and n["tags"] == ["a", "b"]
    with pytest.raises(rn.NoteError, match="bad_status"):
        rn.update(conn, nid, status="deleted")
    with pytest.raises(rn.NoteError, match="not_found"):
        rn.update(conn, 999, status="open")
    with pytest.raises(rn.NoteError, match="title_required"):
        rn.update(conn, nid, title=" ")


def test_filters_search_tags_and_archive_visibility(conn):
    a = rn.create(conn, "note", "Données FRED en retard", "ALFRED décale de 2 jours", "data", "DGS10", 1)
    rn.create(conn, "result", "XGBoost 0,52", "", "ml", "MAR", 2)
    rn.create(conn, "hypothesis", "H sur MAR", "", "ml,mar", "MAR", 2)
    assert len(rn.list_notes(conn)) == 3
    assert [n["title"] for n in rn.list_notes(conn, target="MAR", kind="result")] == ["XGBoost 0,52"]
    assert [n["note_id"] for n in rn.list_notes(conn, q="ALFRED")] == [a] and len(rn.list_notes(conn, tag="ml")) == 2 and len(rn.list_notes(conn, tag="m")) == 0
    rn.update(conn, a, status="archived")
    assert len(rn.list_notes(conn)) == 2 and len(rn.list_notes(conn, include_archived=True)) == 3 and len(rn.list_notes(conn, status="archived")) == 1
    assert rn.list_notes(conn, q="%") == []                       # les jokers LIKE ne sont pas interprétés


def test_hypothesis_is_flagged_before_or_after_the_run(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    conn.execute("UPDATE run SET started_at = '2027-06-01 12:00:00' WHERE run_id = ?", (info["run_id"],))
    conn.commit()
    early = rn.create(conn, "hypothesis", "avant", run_id=info["run_id"])
    late = rn.create(conn, "hypothesis", "après", run_id=info["run_id"])
    conn.execute("UPDATE research_note SET created_at = '2027-05-30 08:00:00' WHERE note_id = ?", (early,))
    conn.execute("UPDATE research_note SET created_at = '2027-06-02 08:00:00' WHERE note_id = ?", (late,))
    conn.commit()
    by = {n["note_id"]: n for n in rn.list_notes(conn)}
    assert by[early]["before_run"] is True and by[late]["before_run"] is False
    assert rn.list_notes(conn, include_archived=True)[0]["before_run"] in (True, False)
    registry.clear_cache()


def test_stats_confirmation_rate(conn):
    for status in ("confirmed", "confirmed", "refuted", "open"):
        nid = rn.create(conn, "hypothesis", "h " + status, tags="x,y")
        rn.update(conn, nid, status=status)
    s = rn.stats(conn)
    assert s["hypotheses"] == {"confirmed": 2, "refuted": 1, "open": 1} and s["decided"] == 3 and s["confirmation_rate"] == pytest.approx(2 / 3)
    assert dict(s["tags"]) == {"x": 4, "y": 4}


def test_pages_api_and_run_section(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    conn.close()
    c = TestClient(app)
    assert c.get("/carnet").status_code == 200 and 'href="/carnet"' in c.get("/").text
    r = c.post("/api/carnet/notes", json={"kind": "hypothesis", "title": "<script>x</script>", "body": "b", "tags": "t1", "target": "TST", "horizon": 2, "run_id": info["run_id"]})
    assert r.status_code == 200
    nid = r.json()["note_id"]
    assert c.post("/api/carnet/notes", json={"kind": "bad", "title": "t"}).json()["detail"] == "bad_kind"
    assert c.post("/api/carnet/notes", json={"kind": "note", "title": ""}).status_code == 400
    assert c.post(f"/api/carnet/notes/{nid}", json={"status": "refuted"}).status_code == 200
    assert c.post("/api/carnet/notes/9999", json={"status": "open"}).status_code == 404
    listed = c.get("/api/carnet/notes?kind=hypothesis").json()["notes"]
    assert listed[0]["status"] == "refuted" and listed[0]["title"] == "<script>x</script>"      # stocké tel quel, affiché par textContent
    assert c.get("/api/carnet/stats").json()["hypotheses"] == {"refuted": 1}
    sec = c.get(f"/api/runs/{info['run_id']}/analysis/notes").json()
    assert sec["available"] and sec["notes"][0]["note_id"] == nid and sec["related"] == []
    html = c.get(f"/runs/{info['run_id']}/analyse").text
    assert 'data-ra-mount="notes"' in html and "/static/carnet.js" in html
    registry.clear_cache()
