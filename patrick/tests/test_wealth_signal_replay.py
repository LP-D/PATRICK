"""Roadmap bloc 4 -- replaying the models' signals on a patrimoine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.data.store import DataStore
from patrick.simulate import engine as sim_engine
from patrick.tracking import db as trackdb
from patrick.wealth import signal_replay

TARGET = "^TEST"


@pytest.fixture
def modeled(tmp_path):
    db_path, store_root = str(tmp_path / "patrick.db"), str(tmp_path / "store")
    n, horizon = 300, 5
    idx = pd.bdate_range("2020-01-01", periods=n)
    price = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, n))
    snapshot_id = DataStore(root=store_root).save(f"raw_{TARGET}", pd.DataFrame({"IDX_TEST": price}, index=idx))
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, snapshot_id, data_hash="x", n_tickers=0, n_fred_series=0, fred_source="api")
    trackdb.create_run(conn, "r", target=TARGET, horizon=horizon, snapshot_id=snapshot_id, config_json="{}",
                        config_hash="h", git_sha="s", seed=0)
    trial_id = trackdb.create_trial(conn, "r", regime="GLOBAL", algo="X", sampler="none", n_features=1,
                                     selector="shap")
    trackdb.mark_best_trial(conn, trial_id)
    ts = [str(idx[i]) for i in range(20, n - horizon, horizon)]
    ups = [price[i + horizon] > price[i] for i in range(20, n - horizon, horizon)]
    trackdb.add_predictions(conn, trial_id, fold_index=0, split="holdout", ts=ts,
                            y_true=[3 if u else 0 for u in ups], y_pred=[3 if u else 0 for u in ups],
                            y_proba=[0.8] * len(ts))
    trackdb.finish_run(conn, "r", "done", n_trials=1)
    conn.close()
    return db_path, store_root, trial_id


def _holdings(rows):
    total = sum(r["value"] for r in rows)
    return {"total": total, "rows": rows}


def test_modeled_positions_are_replayed_the_others_listed_with_their_reason(modeled):
    db_path, store_root, trial_id = modeled
    holdings = _holdings([
        {"symbol": TARGET, "value": 6000.0, "is_term_deposit": False},
        {"symbol": "MC.PA", "value": 3000.0, "is_term_deposit": False},
        {"symbol": "DAT:2024", "value": 1000.0, "is_term_deposit": True},
    ])
    params = sim_engine.SimParams()
    alone = sim_engine.simulate(trial_id, params, db_path=db_path, store_root=store_root, segment="holdout")
    out = signal_replay.replay_account(holdings, params, db_path=db_path, store_root=store_root)
    assert [c["symbol"] for c in out["covered"]] == [TARGET]
    assert out["covered_weight"] == pytest.approx(0.6)
    reasons = {s["symbol"]: s["reason"] for s in out["skipped"]}
    assert "aucun run" in reasons["MC.PA"] and "dépôt à terme" in reasons["DAT:2024"]
    eq = [p["v"] for p in alone["equity_curve"]]
    assert out["strategy_return"] == pytest.approx(eq[-1] / eq[0] - 1.0, rel=1e-6)
    assert out["segment"] == "holdout"


def test_each_replayed_asset_is_logged_as_a_simulation(modeled):
    db_path, store_root, _ = modeled
    holdings = _holdings([{"symbol": TARGET, "value": 1000.0, "is_term_deposit": False}])
    conn = trackdb.connect(db_path)
    before = sim_engine.count_simulations_for_target(conn, TARGET)
    conn.close()
    signal_replay.replay_account(holdings, sim_engine.SimParams(), db_path=db_path, store_root=store_root)
    conn = trackdb.connect(db_path)
    assert sim_engine.count_simulations_for_target(conn, TARGET) == before + 1
    conn.close()


def test_no_modeled_position_gives_an_empty_replay_not_an_error(modeled):
    db_path, store_root, _ = modeled
    out = signal_replay.replay_account(_holdings([{"symbol": "AAPL", "value": 10.0, "is_term_deposit": False}]),
                                       sim_engine.SimParams(), db_path=db_path, store_root=store_root)
    assert out["covered"] == [] and out["portfolio"] == [] and out["covered_weight"] == 0.0


def test_replay_api_end_to_end(modeled, monkeypatch):
    from fastapi.testclient import TestClient

    from patrick.wealth import performance
    from patrick.webapp import wealth_routes
    from patrick.webapp.app import app

    db_path, store_root, _ = modeled
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", store_root)
    px = pd.Series(np.linspace(100, 120, 300), index=pd.bdate_range("2020-01-01", periods=300))
    monkeypatch.setattr(wealth_routes, "price_provider", lambda: performance.dict_price_provider({TARGET: px}))
    client = TestClient(app)
    acc = client.post("/api/wealth/accounts", json={"name": "CTO", "kind": "CTO"}).json()["account_id"]
    client.post(f"/api/wealth/accounts/{acc}/movements",
                json={"kind": "buy", "ts": "2020-02-03", "symbol": TARGET, "quantity": "10", "price": "100"})
    resp = client.post(f"/api/wealth/accounts/{acc}/replay", json={"segment": "holdout", "params": {}})
    assert resp.status_code == 200, resp.text
    assert [c["symbol"] for c in resp.json()["covered"]] == [TARGET]
    assert client.post(f"/api/wealth/accounts/{acc}/replay", json={"segment": "pooled"}).status_code == 400
    assert client.get("/patrimoine-simulation").status_code == 200
