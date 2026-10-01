from __future__ import annotations

from types import SimpleNamespace

from patrick.config.schema import RunConfig
from patrick.pipeline.engine import _select_screening_finalists, _tuning_candidates
from patrick.pipeline.leaderboard import Leaderboard
from patrick.tracking import db as trackdb


def test_default_optuna_candidates_are_one_best_scan_model_per_horizon():
    config = RunConfig.model_validate({
        "objective": {"target_symbol": "^VIX", "horizons": [1, 5]},
    })
    board = Leaderboard()
    board.rows = [
        {"horizon": 1, "regime": "GLOBAL", "N": 5, "sampler": "SMOTE",
         "algo": "RandomForest", "F1_dir": 0.61},
        {"horizon": 1, "regime": "GLOBAL", "N": 8, "sampler": "SMOTE",
         "algo": "XGBoost", "F1_dir": 0.64},
        {"horizon": 5, "regime": "GLOBAL", "N": 5, "sampler": "SMOTE",
         "algo": "RandomForest", "F1_dir": 0.58},
        {"horizon": 5, "regime": "GLOBAL", "N": 8, "sampler": "SMOTE",
         "algo": "XGBoost", "F1_dir": 0.56},
    ]

    candidates = _tuning_candidates(SimpleNamespace(config=config, board=board))

    assert {(row["horizon"], row["algo"]) for row in candidates} == {
        (1, "XGBoost"), (5, "RandomForest"),
    }


def test_screening_keeps_top_first_fold_candidates_and_persists_all_decisions(conn):
    config = RunConfig.model_validate({
        "name": "screening_test", "objective": {"target_symbol": "^VIX", "horizons": [5]},
        "selection": {"screening_mode": "staged", "screening_finalists_per_group": 1},
    })
    trackdb.upsert_snapshot(conn, "screen", "screen-hash", None, None, None)
    trackdb.create_run(conn, "screen-run", "^VIX", 5, "screen", config.model_dump_json(), "hash", "sha", 42)
    board = Leaderboard()
    board.rows = [
        {"horizon": 5, "fold": 1, "regime": "GLOBAL", "N": 5, "sampler": "SMOTE",
         "algo": "RandomForest", "F1_dir": 0.61},
        {"horizon": 5, "fold": 1, "regime": "GLOBAL", "N": 8, "sampler": "SMOTE",
         "algo": "XGBoost", "F1_dir": 0.64},
    ]
    trial_ids = {
        (5, "GLOBAL", 5, "SMOTE", "RandomForest"): 1,
        (5, "GLOBAL", 8, "SMOTE", "XGBoost"): 2,
    }
    state = SimpleNamespace(config=config, board=board, conn=conn, trial_ids=trial_ids, screening_finalists={})

    _select_screening_finalists(state, 5, "GLOBAL", "screen-run")

    assert state.screening_finalists[(5, "GLOBAL")] == {(8, "SMOTE", "XGBoost")}
    assert len(board.rows) == 1 and board.rows[0]["algo"] == "XGBoost"
    assert len(state.trial_ids) == 1
    rows = trackdb.list_screening_decisions(conn, "screen-run")
    assert [(row["algo"], row["decision"], row["rank"]) for row in rows] == [
        ("XGBoost", "finalist", 1), ("RandomForest", "screened_out", None),
    ]
