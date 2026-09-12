"""Route tests for `/data-freshness` (feature/data-freshness): fraîcheur des
données ingérées par ticker/série, lue depuis le data lake local. Style
`test_history_webapp_smoke.py` -- pas de DB pipeline seedée ici (cette page
lit `data/store.py`, pas `patrick.db`), on isole via `PATRICK_STORE_ROOT`
(comme `data/store.py::_default_store_dir` le documente) pour ne jamais
toucher au vrai cache."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.webapp.app import app


def _seed_store(tmp_path: Path, symbol: str, date_max: str) -> None:
    """Ecrit directement un `_index.json` minimal -- pas besoin de vrai
    parquet pour ces tests de route, `freshness_overview` ne lit que
    l'index (`store.list_snapshots`)."""
    store_dir = tmp_path / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    index = {
        f"raw_{symbol}": {
            "snapshots": [
                {"snapshot_id": f"2026-09-01__raw_{symbol}__abc", "date_max": date_max,
                 "date_min": "2000-01-01", "content_hash": "abc",
                 "path": str(store_dir / "x.parquet"), "created_at": "2026-09-01T00:00:00+00:00"}
            ]
        }
    }
    (store_dir / "_index.json").write_text(json.dumps(index), encoding="utf-8")


def test_data_freshness_page_returns_200_on_empty_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    client = TestClient(app)
    resp = client.get("/data-freshness")
    assert resp.status_code == 200


def test_data_freshness_page_shows_never_cached_state_for_uncached_ticker(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    client = TestClient(app)
    resp = client.get("/data-freshness")
    assert resp.status_code == 200
    assert "jamais mis en cache" in resp.text


def test_data_freshness_page_shows_cached_ticker_freshness(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    _seed_store(tmp_path, "^GSPC", date_max="2026-09-04")
    client = TestClient(app)
    resp = client.get("/data-freshness")
    assert resp.status_code == 200
    assert "^GSPC" in resp.text
    assert "2026-09-04" in resp.text


def test_data_freshness_page_groups_match_default_target_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    client = TestClient(app)
    resp = client.get("/data-freshness")
    for group_name in D.DEFAULT_TARGET_GROUPS:
        assert group_name in resp.text


def test_data_freshness_page_translates_every_group_label(tmp_path, monkeypatch):
    """fix/cleanup-dead-references : meme defaut que /universe -- le fallback
    f"group_{nom}" pour "Devises"/"Matieres premieres (futures)" (absents de
    i18n.py::TARGET_GROUP_LABEL_KEYS) s'affichait litteralement."""
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    client = TestClient(app)
    resp = client.get("/data-freshness")
    assert resp.status_code == 200
    assert "group_" not in resp.text


def test_data_freshness_reachable_from_nav():
    client = TestClient(app)
    resp = client.get("/")
    assert 'href="/data-freshness"' in resp.text
