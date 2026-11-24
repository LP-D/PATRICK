"""D2 : fiabilité des probabilités d'un essai au holdout (Brier skill contre le taux de hausse)."""
from __future__ import annotations

import pytest

from patrick.tracking import db as trackdb
from patrick.tracking import history


def _trial(conn, run_id, rows):
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    trackdb.create_run(conn, run_id, target="AAPL", horizon=1, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 3, "shap")
    conn.executemany("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, p_up) VALUES (?, ?, 'holdout', ?, ?, ?)",
                     [(tid, f"2025-{1 + i // 28:02d}-{i % 28 + 1:02d}", yt, 3 if p >= 0.5 else 0, p) for i, (yt, p) in enumerate(rows)])
    conn.commit()
    return tid


def test_informed_probabilities_have_a_positive_skill_and_overconfident_noise_a_negative_one(conn):
    good = _trial(conn, "good", [(3, 0.7), (0, 0.3)] * 20)              # dit juste avec 0,7 : Brier 0,09 contre 0,25
    bad = _trial(conn, "bad", [(3, 0.05), (0, 0.95)] * 20)              # sûr de lui et faux
    few = _trial(conn, "few", [(3, 0.7)] * 10)

    out = history.holdout_brier_skill(conn, [good, bad, few])

    assert out[good]["skill"] == pytest.approx(1 - 0.09 / 0.25) and out[good]["n"] == 40
    assert out[bad]["skill"] < 0 and few not in out
