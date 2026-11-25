"""A25 : export Excel en un clic -- dernières prédictions des champions, champions, fonds."""
from __future__ import annotations

import io

import fund_support as fs
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from patrick.fund import store
from patrick.tracking import db as trackdb
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_the_workbook_has_one_sheet_per_subject_with_real_numbers(client, tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    trackdb.create_run(conn, "r1", target="AAPL", horizon=1, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "none", 3, "shap")
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, reason) VALUES ('AAPL', 1, 'r1', ?, 'first')", (tid,))
    conn.execute("INSERT INTO prediction (trial_id, ts, split, y_pred, y_proba, p_up) VALUES (?, '2026-01-15', 'live', 3, 0.41, 0.63)", (tid,))
    conn.commit()
    store.create_strategy(conn, "Fonds A", "CTO", 100_000, "2026-01-05")
    conn.close()

    resp = client.get("/api/export/patrick.xlsx")

    assert resp.status_code == 200 and "spreadsheetml" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    book = load_workbook(io.BytesIO(resp.content))
    assert book.sheetnames == ["Prédictions", "Champions", "Fonds", "À propos"]
    pred = list(book["Prédictions"].iter_rows(values_only=True))
    assert pred[1][:7] == ("AAPL", 1, "2026-01-15", "hausse forte", "hausse", 0.41, 0.63)
    fonds = list(book["Fonds"].iter_rows(values_only=True))
    assert fonds[1][0] == "Fonds A" and fonds[1][3] == 100_000
