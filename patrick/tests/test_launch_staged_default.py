"""`/launch`: the staged-screening box is checked by default, with ONE
finalist per horizon (the best candidate alone goes on to the complete
period and to Optuna)."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp.app import app


def _input_tag(html: str, name: str) -> str:
    return next(t for t in re.findall(r"<input\b[^>]*>", html) if f'name="{name}"' in t)


def test_launch_page_checks_staged_screening_with_one_finalist(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()

    resp = TestClient(app).get("/ml")

    assert resp.status_code == 200
    assert "checked" in _input_tag(resp.text, "staged_screening")
    assert 'value="1"' in _input_tag(resp.text, "screening_finalists_per_group")
    assert 'value="1"' in _input_tag(resp.text, "top_k")
