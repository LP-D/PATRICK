"""Avantage prédictif live (`tracking/live_edge.py`) : statistiques pures et lecture des signaux jugés."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from patrick.tracking import db, live_edge


def _days(n: int, start: date = date(2026, 9, 1)) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def test_perfect_signals_are_a_probable_edge():
    # Une hausse un jour sur deux, toujours bien prédite : 100 % de réussite, la règle naïve plafonne à 50 %.
    obs = [(d, i % 2 == 0, i % 2 == 0) for i, d in enumerate(_days(30))]
    s = live_edge.edge_stats(obs, horizon=1)
    assert s["n"] == 30 and s["days"] == 30 and s["n_eff"] == 30.0
    assert s["hit_rate"] == 1.0 and s["naive"] == 0.5 and s["edge_naive"] == pytest.approx(0.5)
    assert s["p_value"] < 1e-6
    assert live_edge.verdicts({"c": s})["c"] == live_edge.EDGE


def test_overlapping_horizons_divide_the_independent_observations():
    obs = [(d, True, True) for d in _days(30)]
    assert live_edge.edge_stats(obs, horizon=1)["n_eff"] == 30.0
    assert live_edge.edge_stats(obs, horizon=10)["n_eff"] == 3.0


def test_same_day_assets_count_once_per_day():
    # 40 actifs qui se trompent ensemble le même jour : une seule observation indépendante, pas 40.
    s = live_edge.edge_stats([("2026-09-01", True, False)] * 40, horizon=1)
    assert s["n"] == 40 and s["days"] == 1 and s["n_eff"] == 1.0
    assert s["p_value"] is None
    assert live_edge.verdicts({"c": s})["c"] == live_edge.EARLY


def test_too_few_independent_observations_is_early_even_when_perfect():
    obs = [(d, True, True) for d in _days(30)]
    s = live_edge.edge_stats(obs, horizon=10)       # 30 jours / 10 = 3 observations indépendantes < 8
    assert s["hit_rate"] == 1.0
    assert live_edge.verdicts({"c": s})["c"] == live_edge.EARLY


def test_coin_flip_is_none_and_systematic_error_is_below():
    flip = [(d, True, i % 2 == 0) for i, d in enumerate(_days(40))]             # un jour sur deux juste
    wrong = [(d, True, False) for d in _days(40)]                                # toujours faux
    out = live_edge.verdicts({"flip": live_edge.edge_stats(flip, 1), "wrong": live_edge.edge_stats(wrong, 1)})
    assert out == {"flip": live_edge.NONE, "wrong": live_edge.BELOW}


def test_always_up_in_a_rising_market_is_not_an_edge():
    # Le marché monte 80 % du temps ; prédire « hausse » partout donne 80 % sans rien prédire : égal à la règle naïve.
    obs = [(d, True, i % 5 != 0) for i, d in enumerate(_days(50))]
    s = live_edge.edge_stats(obs, horizon=1)
    assert s["hit_rate"] == pytest.approx(0.8) and s["naive"] == pytest.approx(0.8)
    assert s["edge_naive"] == pytest.approx(0.0)
    assert live_edge.verdicts({"c": s})["c"] != live_edge.EDGE


def test_empty_cell_has_no_numbers():
    s = live_edge.edge_stats([], horizon=5)
    assert s["n"] == 0 and s["hit_rate"] is None
    assert live_edge.verdicts({"c": s})["c"] == live_edge.EARLY


def test_build_groups_by_class_with_an_all_row():
    judged = []
    for i, day in enumerate(_days(20)):
        up = i % 2 == 0
        judged.append(("SPY", 1, day, up, up))          # actions : toujours juste
        judged.append(("BTC-USD", 1, day, up, not up))  # crypto : toujours faux
    out = live_edge.build(judged, {"SPY": "etfs", "BTC-USD": "crypto"}, [1])
    assert set(out["classes"]) == {"etfs", "crypto"}
    assert out["matrix"]["etfs"][1]["verdict"] == live_edge.EDGE
    assert out["matrix"]["crypto"][1]["verdict"] == live_edge.BELOW
    assert out["matrix"][live_edge.ALL_KEY][1]["n"] == 40
    assert out["assets"][("SPY", 1)]["hit_rate"] == 1.0
    assert out["first_day"] == "2026-09-01" and out["n_judged"] == 40


# ------------------------------------------------------------------ lecture en base


def _seed(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    ids = {}
    for run_id, target in (("r_old", "SPY"), ("r_new", "SPY")):
        db.create_run(conn, run_id, target, 1, "snap1", "{}", run_id, "sha", 1)
        ids[run_id] = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, ids[run_id])
        db.finish_run(conn, run_id, status="done", n_trials=1)
    return conn, ids


def test_fetch_judged_keeps_real_live_signals_only(tmp_path):
    conn, ids = _seed(tmp_path)
    # 3 jours : un vrai signal (juste), une barre reconstituée, un signal contradictoire (classe haussière, sens réalisé baissier).
    db.add_predictions(conn, ids["r_new"], None, "live", ts=["2026-09-01", "2026-09-02", "2026-09-03"],
                       y_true=[1.0, 1.0, 0.0], y_pred=[3, 3, 3], y_proba=[0.7, 0.7, 0.7])
    conn.execute("UPDATE prediction SET live_backfill = 1 WHERE trial_id = ? AND ts = '2026-09-02'", (ids["r_new"],))
    conn.execute("UPDATE prediction SET y_class = 3 WHERE trial_id = ? AND ts = '2026-09-03'", (ids["r_new"],))
    conn.commit()
    judged, excluded = live_edge.fetch_judged(conn, ["SPY"], [1])
    assert excluded == 1
    assert judged == [("SPY", 1, "2026-09-01", True, True)]
    judged_all, _ = live_edge.fetch_judged(conn, ["SPY"], [1], include_backfill=True)
    assert {j[2] for j in judged_all} == {"2026-09-01", "2026-09-02"}


def test_fetch_judged_counts_a_day_once_when_two_models_wrote_it(tmp_path):
    conn, ids = _seed(tmp_path)
    db.add_predictions(conn, ids["r_old"], None, "live", ts=["2026-09-01"], y_true=[1.0], y_pred=[0], y_proba=[0.6])   # ancien : faux
    db.add_predictions(conn, ids["r_new"], None, "live", ts=["2026-09-01"], y_true=[1.0], y_pred=[3], y_proba=[0.6])   # récent : juste
    judged, _ = live_edge.fetch_judged(conn, ["SPY"], [1])
    assert judged == [("SPY", 1, "2026-09-01", True, True)]


def test_fetch_judged_on_empty_inputs(tmp_path):
    conn, _ = _seed(tmp_path)
    assert live_edge.fetch_judged(conn, [], [1]) == ([], 0)
    assert live_edge.fetch_judged(conn, ["SPY"], []) == ([], 0)
    assert live_edge.fetch_judged(conn, ["UNKNOWN"], [1]) == ([], 0)
