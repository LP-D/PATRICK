"""Alertes de prix et de signal (FO16 du 25/11)."""
from __future__ import annotations

from patrick.tracking import alert_rules
from patrick.tracking import db as trackdb


def test_price_alerts_ring_once_per_session_and_are_remembered():
    alert_rules.save_rules([{"symbol": "^GSPC", "kind": "above", "level": 6000}, {"symbol": "EURUSD=X", "kind": "below", "level": 1.05}])
    quotes = {"^GSPC": ("2026-11-25", 6010.0), "EURUSD=X": ("2026-11-25", 1.06)}
    sent = []
    conn = trackdb.connect()
    try:
        fired = alert_rules.check(conn, quotes.get, notify=lambda title, body: sent.append(body) or True)
        assert [f["rule"]["symbol"] for f in fired] == ["^GSPC"] and "au-dessus de 6000" in sent[0]
        assert alert_rules.check(conn, quotes.get, notify=lambda t, b: sent.append(b) or True) == []   # même séance : silence
        assert alert_rules.load_rules()[0]["last_fired"] == "2026-11-25"
    finally:
        conn.close()


def test_a_flip_of_the_champion_direction_rings():
    conn = trackdb.connect()
    try:
        trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
        trackdb.create_run(conn, "r1", "GC=F", 5, "snap", "{}", "cfg", "sha", 1)
        trial = trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "none", 8, "shap")
        trackdb.add_predictions(conn, trial, fold_index=None, split="live", ts=["2026-11-24", "2026-11-25"], y_true=[None, None],
                                y_pred=[3, 0], y_proba=[0.6, 0.6])
        conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, reason) VALUES ('GC=F', 5, 'r1', ?, 't')", (trial,))
        conn.commit()
        fired = alert_rules.evaluate(conn, [{"symbol": "GC=F", "kind": "flip", "horizon": 5}], lambda s: None)
        assert len(fired) == 1 and "baisse" in fired[0]["message"]
    finally:
        conn.close()


def test_invalid_rules_are_refused():
    import pytest
    with pytest.raises(ValueError):
        alert_rules.save_rules([{"symbol": "^GSPC", "kind": "above"}])
