"""Recherche d'actifs de la palette (Ctrl K) : `/api/asset-index` et branchement sur `shell.js`."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp import forms
from patrick.webapp.app import app

STATIC = Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "static"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    return TestClient(app)


def test_asset_index_lists_every_asset_that_has_a_page(tmp_path, monkeypatch):
    rows = _client(tmp_path, monkeypatch).get("/api/asset-index").json()
    symbols = [r["s"] for r in rows]
    assert len(symbols) == len(set(symbols)) == len(forms.TARGET_SOURCE_BY_SYMBOL)
    assert {"s", "n", "c", "g"} == set(rows[0])
    by_symbol = {r["s"]: r for r in rows}
    assert by_symbol["^GSPC"]["c"] == "indices" and "S&P 500" in by_symbol["^GSPC"]["n"]
    assert by_symbol["BTC-USD"]["c"] == "crypto"
    assert by_symbol["GC=F"]["c"] == "commodities"


def test_asset_index_follows_the_language(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    fr = {r["s"]: r for r in client.get("/api/asset-index").json()}
    en = {r["s"]: r for r in client.get("/api/asset-index", cookies={"patrick_lang": "en"}).json()}
    assert fr["GC=F"]["g"] != en["GC=F"]["g"]      # « Matières premières » / « Commodities »
    assert fr["GC=F"]["n"] != en["GC=F"]["n"]      # « Future · Or » / « Future · Gold »


def test_every_indexed_asset_has_a_working_page_link(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for symbol in ("^GSPC", "BTC-USD", "GC=F"):
        assert client.get(f"/targets/{symbol}").status_code == 200


def test_palette_now_says_pages_and_assets(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/predictions").text
    assert "Rechercher une page ou un actif" in html


def test_palette_script_opens_the_asset_page_and_keeps_pages_first_without_a_query():
    js = (STATIC / "shell.js").read_text(encoding="utf-8")
    assert '"/targets/" + encodeURIComponent' in js           # l'entrée ouvre la fiche
    assert "/api/asset-index" in js
    assert "(q && assets)" in js                                # sans saisie, uniquement les pages
