"""Les séries macro (FRED) ne sont plus des cibles : aucun modèle d'avant le 2026-10-31 qui en prédisait une n'est suivi (signal du jour,
résultat réel, santé, modèles proposés aux fonds). Leurs chiffres seraient de la fausse information."""
from __future__ import annotations

import datetime as dt

import pytest
from test_daily_predict import _make_run_with_trial
from test_fund_selection import World

from patrick import live_refresh
from patrick.config import targets
from patrick.fund import systematic
from patrick.tracking import db as trackdb
from patrick.tracking import health, live_board

NOW = dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.UTC)
DAYS = [d.isoformat() for d in (dt.date(2026, 9, 14) + dt.timedelta(days=i) for i in range(50)) if d.weekday() < 5]      # 36 séances : au-delà du seuil d'une ligne de tableau


def test_a_macro_target_is_recognised_under_every_label():
    assert targets.is_macro_target("GDP") and targets.is_macro_target("FEDFUNDS") and targets.is_macro_target("GDP__alpha_^GSPC")
    assert not targets.is_macro_target("AAPL") and not targets.is_macro_target("^GSPC") and not targets.is_macro_target("")
    assert {"GDP", "PCE", "FEDFUNDS"} <= targets.macro_symbols() and "AAPL" not in targets.macro_symbols()


def test_the_daily_predictions_skip_macro_models_and_keep_the_others(tmp_path):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    for name in ("macro", "stock"):
        (tmp_path / f"{name}.joblib").write_bytes(b"fake")
    _make_run_with_trial(conn, "run_macro", "GDP", 5, artifact_path=str(tmp_path / "macro.joblib"))
    _make_run_with_trial(conn, "run_stock", "AAPL", 5, artifact_path=str(tmp_path / "stock.joblib"))

    candidates = live_refresh.find_predictable_candidates(conn, base_dir=str(tmp_path))
    conn.close()

    assert [(c.target, c.run_id) for c in candidates] == [("AAPL", "run_stock")]


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _live(conn, trial_id: int, rows: list[tuple]) -> None:
    conn.executemany("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba, p_up) VALUES (?, ?, 'live', ?, ?, 0.6, ?)",
                     [(trial_id, day, y_true, y_pred, p_up) for day, y_pred, y_true, p_up in rows])
    conn.commit()


def test_the_live_results_page_ignores_macro_champions(conn, world):
    stock = world.cell("AAPL", 1, live=None)
    macro = [world.cell("GDP", h, live=None) for h in (1, 5)]
    _live(conn, stock, [(day, 3, 1.0, 0.6) for day in DAYS])
    for trial_id in macro:                                       # des « succès » parfaits, qui gonfleraient la moyenne
        _live(conn, trial_id, [(day, 3, 1.0, 0.97) for day in DAYS])

    board = live_board.board(conn, dt.date(2026, 11, 16))

    assert board["n_champions"] == 1 and board["total"]["n"] == len(DAYS)
    assert [r["key"] for r in board["by_class"]] == ["equities_us"] and board["by_class"][0]["n"] == len(DAYS)
    assert all(c["target"] != "GDP" for c in board["consensus"])


def test_the_health_checks_do_not_count_macro_champions(conn, world, tmp_path):
    world.cell("GDP", 1, live=("2026-11-13", 3, 0.9))              # le seul signal récent serait celui d'une série macro
    world.cell("AAPL", 1, live=("2026-10-01", 3, 0.6))
    conn.execute("INSERT INTO drift_psi_history (symbol, horizon, feature, computed_at, psi) VALUES ('GDP', 1, 'f', '2026-11-10 22:00:00', 0.1)")
    conn.commit()

    signals = health._signals(conn, NOW)
    drift = health._drift(conn)

    assert signals["value"] == "2026-10-01" and signals["detail"] == 1 and signals["status"] == "error"      # plus de signal depuis un mois
    assert (drift["value"], drift["detail"]) == (0, 1)


def test_macro_models_are_never_offered_to_a_fund_rule(conn, world):
    world.cell("GDP", 5, live=[("2026-11-12", 3, 0.6)])
    world.cell("AAPL", 5, live=[("2026-11-12", 3, 0.6)])

    assert [(m["target"], m["horizon"]) for m in systematic.available_models(conn)] == [("AAPL", 5)]
