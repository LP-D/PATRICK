from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.phase9 import (
    DecisionJournal,
    ExecutionOrder,
    StrategyEngine,
    aggregate_signals,
    build_event_calendar,
    classify_regime_daily,
    compare_test_holdout,
    credit_risk_regime,
    p_value_histogram,
    reduce_correlated_signals,
    regime_alignment_score,
    regime_summary,
    risk_parity_weights,
    signal_dm_summary,
    simulate_execution,
)


def test_signal_dm_summary_returns_valid_selection_frame():
    actual = np.array([0, 1, 0, 1, 0, 1, 0, 1], dtype=int)
    signal_a = actual.copy()
    signal_b = np.array([1, 1, 1, 1, 1, 1, 1, 1], dtype=int)

    frame = signal_dm_summary({"A": signal_a, "B": signal_b}, actual, baseline={"A": actual, "B": actual}, alpha=0.10)

    assert {"signal", "p_value", "adjusted_p_value", "selected"}.issubset(frame.columns)
    assert set(frame["signal"]) == {"A", "B"}
    assert frame["p_value"].notna().all()


def test_reduce_correlated_signals_keeps_single_representation_per_cluster():
    signal_matrix = pd.DataFrame(
        {
            "sig_a": [0, 1, 0, 1, 0, 1, 0, 1],
            "sig_b": [0, 1, 0, 1, 0, 1, 0, 1],
            "sig_c": [1, 0, 1, 0, 1, 0, 1, 0],
        }
    )
    signal_frame = pd.DataFrame(
        [
            {"signal": "sig_a", "p_value": 0.01, "adjusted_p_value": 0.015, "significant": True},
            {"signal": "sig_b", "p_value": 0.02, "adjusted_p_value": 0.03, "significant": True},
            {"signal": "sig_c", "p_value": 0.7, "adjusted_p_value": 0.9, "significant": False},
        ]
    )

    reduced = reduce_correlated_signals(signal_frame, signal_matrix, corr_threshold=0.70)

    assert set(reduced["signal"]).issubset({"sig_a", "sig_c"})
    assert "sig_b" not in set(reduced["signal"])


def test_regime_classification_and_holdout_diagnostic_are_covered():
    vix = np.array([10.0, 18.0, 30.0, 60.0])
    vix_pct = np.array([15.0, 45.0, 80.0, 98.0])
    ret = np.array([0.015, -0.01, -0.03, -0.12])
    vol = np.array([0.08, 0.16, 0.25, 0.42])

    labels, confidence = classify_regime_daily(vix, vix_pct, ret, vol)
    assert set(labels) <= {"CALM", "NORMAL", "STRESS", "CRASH"}
    assert confidence.shape == labels.shape
    assert confidence.min() >= 0.0 and confidence.max() <= 1.0

    summary = regime_summary(labels)
    assert summary["n_days"] == 4
    assert summary["counts"]["CALM"] + summary["counts"]["NORMAL"] + summary["counts"]["STRESS"] + summary["counts"]["CRASH"] == 4

    hist = p_value_histogram({"a": 0.01, "b": 0.2, "c": 0.5, "d": 0.9})
    assert hist["n_values"] == 4
    assert "histogram" in hist

    cmp = compare_test_holdout(
        pd.DataFrame([{"signal": "s1"}, {"signal": "s2"}]),
        {"s1": 1.4, "s2": 0.8},
        {"s1": 1.0, "s2": 1.0},
    )
    assert set(cmp.columns) >= {"signal", "test_sharpe", "holdout_sharpe", "relative_gap"}


def test_phase9_aggregation_and_execution_supports_all_blocks():
    signal_frame = pd.DataFrame(
        [
            {"signal": "s1", "prediction": 1.0, "selected": True, "asset_class": "equity"},
            {"signal": "s2", "prediction": -0.8, "selected": True, "asset_class": "fx"},
            {"signal": "s3", "prediction": 0.2, "selected": False, "asset_class": "equity"},
        ]
    )
    verdict = aggregate_signals(signal_frame)
    assert verdict["verdict"] in {"BULLISH", "NEUTRAL", "BEARISH"}
    assert regime_alignment_score(verdict, "STRESS")["status"] in {"warning", "divergent", "aligned"}
    assert credit_risk_regime(0.30, 0.10)["state"] == "STRESS"

    cal = build_event_calendar([
        {"date": "2024-01-10", "event_type": "FOMC", "asset": "USD", "source": "manual", "description": "meeting"},
    ])
    assert not cal.empty

    w = risk_parity_weights(pd.DataFrame({"a": [0.01, -0.02, 0.01], "b": [0.00, 0.02, -0.01]}))
    assert set(w.index) == {"a", "b"}
    assert np.isclose(w.sum(), 1.0)

    journal = DecisionJournal(author="operator")
    journal.record("override", before={"signal": "s1"}, after={"signal": "s2"}, reason="manual")
    assert journal.export().shape[0] == 1

    orders = [ExecutionOrder(symbol="AAPL", side="BUY", quantity=10, price=100.0), ExecutionOrder(symbol="MSFT", side="HOLD", quantity=0, price=50.0)]
    exec_df = simulate_execution(orders, {"AAPL": 100.0})
    assert set(exec_df["status"]).issubset({"executed", "rejected"})

    engine = StrategyEngine()
    engine.add_strategy_version("operator", "v1", strategy=None, results={"sharpe": 1.2})
    snapshot = engine.snapshot_state({"snapshot": "phase9"}, "baseline")
    assert snapshot["snapshot_name"] == "baseline"
    assert engine.journal.export().shape[0] >= 2


def test_phase9_tracking_persistence_and_overview_route(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "phase9.db"))
    from fastapi.testclient import TestClient

    from patrick.tracking import db as trackdb
    from patrick.webapp.app import app

    conn = trackdb.connect()
    trackdb.save_phase9_journal_entry(conn, "override", "operator", {"signal": "A"}, {"signal": "B"}, "manual override")
    trackdb.save_phase9_snapshot(conn, "baseline", {"state": "ready"})
    conn.close()

    client = TestClient(app)
    response = client.get("/phase9")
    assert response.status_code == 200
    assert "Plateforme de trading" in response.text

    journal = client.get("/api/phase9/journal").json()
    assert journal["entries"]

    created = client.post(
        "/api/phase9/journal",
        json={"action": "manual_review", "actor": "operator", "before": {"signal": "A"}, "after": {"signal": "C"}, "reason": "watchlist"},
    )
    assert created.status_code == 200
    assert created.json()["entry"]["action"] == "manual_review"
