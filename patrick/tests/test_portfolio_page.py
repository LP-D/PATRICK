"""Route tests for `/portfolio` (feature/portfolio-view): cross-asset
aggregated synthesis (bullish/bearish counts per `DEFAULT_TARGET_GROUPS`
category + correlated-pair contradiction detection). Same style as
`test_predictions_page.py` -- real Jinja templates through a real FastAPI
route, DB seeded directly via `PATRICK_DB_PATH`, no pipeline run, no
network."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.tracking import db
from patrick.webapp.app import app


def _seed_run_with_prediction(conn, run_id: str, target: str, horizon: int,
                                direction_class: int, snapshot_id: str = "snap1") -> None:
    """Minimal run + best trial + one `split='live'` prediction resolving to
    `direction_class` (see `history._CLASS_DIRECTION`: 0/1 -> DOWN, 2/3 ->
    UP) -- just enough for `latest_predictions_by_target_and_horizon` to
    resolve a direction for `(target, horizon)`."""
    db.create_run(conn, run_id, target, horizon, snapshot_id, "{}", f"cfg-{run_id}", "sha", 1)
    trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_predictions(conn, trial_id, fold_index=None, split="live",
                        ts=["2024-06-01T00:00:00"], y_true=[None],
                        y_pred=[direction_class], y_proba=[0.8])
    db.finish_run(conn, run_id, status="done", n_trials=1)


def _seed_db_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()


def _seed_db_with_dxy_eurusd_contradiction(tmp_path, monkeypatch) -> None:
    """DXY (DX-Y.NYB) and EUR/USD both signal UP (class 3) at horizon=5 --
    a fabricated contradiction (negative-correlation pair, same direction)
    the page must surface."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    _seed_run_with_prediction(conn, "run_dxy", "DX-Y.NYB", 5, 3)
    _seed_run_with_prediction(conn, "run_eurusd", "EURUSD=X", 5, 3)
    conn.close()


def test_portfolio_page_returns_200_on_empty_db(tmp_path, monkeypatch):
    _seed_db_empty(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/portfolio")
    assert resp.status_code == 200


def test_portfolio_page_shows_all_target_groups(tmp_path, monkeypatch):
    _seed_db_empty(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/portfolio")
    for group_name in D.DEFAULT_TARGET_GROUPS:
        assert group_name in resp.text


def test_portfolio_page_reachable_from_nav():
    client = TestClient(app)
    resp = client.get("/")
    assert 'href="/portfolio"' in resp.text


def test_portfolio_page_flags_dxy_eurusd_contradiction(tmp_path, monkeypatch):
    _seed_db_with_dxy_eurusd_contradiction(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    assert "DX-Y.NYB" in resp.text
    assert "EURUSD=X" in resp.text
    # Both resolve to class 3 -> UP (see history._CLASS_DIRECTION).
    assert "UP" in resp.text


def test_portfolio_page_shows_no_contradiction_when_none_detected(tmp_path, monkeypatch):
    _seed_db_empty(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    # Explicit empty state for the contradictions section on a DB with no
    # predictions at all -- never a silently-empty section.
    assert "aucune contradiction" in resp.text.lower()


# flexibility-gaps Gap 6: ?pairs= overrides tracking.portfolio.CORRELATED_PAIRS.

def test_portfolio_page_default_pairs_prefill_the_textarea(tmp_path, monkeypatch):
    _seed_db_empty(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    assert "DX-Y.NYB:EURUSD=X:negative" in resp.text
    assert "CL=F:BZ=F:positive" in resp.text
    assert "^GSPC:^VIX:negative" in resp.text


def test_portfolio_page_custom_pairs_flag_a_non_default_contradiction(tmp_path, monkeypatch):
    """GC=F/SI=F (gold/silver) is deliberately absent from CORRELATED_PAIRS
    (see its own comment) -- with the default pairs it must never be
    flagged, but a user-supplied ?pairs= override must be able to add it
    and see the contradiction it implies."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    _seed_run_with_prediction(conn, "run_gc", "GC=F", 5, 3)   # UP
    _seed_run_with_prediction(conn, "run_si", "SI=F", 5, 0)   # DOWN
    conn.close()

    client = TestClient(app)
    resp_default = client.get("/portfolio")
    assert resp_default.status_code == 200
    assert "Aucune contradiction" in resp_default.text or "aucune contradiction" in resp_default.text.lower()

    resp_custom = client.get("/portfolio", params={"pairs": "GC=F:SI=F:positive"})
    assert resp_custom.status_code == 200
    assert "GC=F" in resp_custom.text
    assert "SI=F" in resp_custom.text
    # And the textarea now reflects the custom set, not the 3 defaults.
    assert "GC=F:SI=F:positive" in resp_custom.text


def test_portfolio_page_rejects_malformed_pairs():
    client = TestClient(app)
    resp = client.get("/portfolio", params={"pairs": "GC=F:SI=F"})
    assert resp.status_code == 400


def test_portfolio_page_rejects_unknown_correlation_sense():
    client = TestClient(app)
    resp = client.get("/portfolio", params={"pairs": "GC=F:SI=F:sideways"})
    assert resp.status_code == 400
