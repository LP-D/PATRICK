"""Champion / challenger, end to end: two real `run_pipeline` runs on the
same synthetic data, with different feature settings. The first is crowned
directly; the second duels it on the SAME holdout (the champion's pool
rebuilt from its own feature settings), exactly one model stays in title,
the loser is archived with its duel then pruned."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.publication_lag import PIT_VERSION
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import champions
from patrick.tracking import db as trackdb

pytestmark = pytest.mark.slow

TARGET = "^TEST"


def _raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    df = pd.DataFrame({"IDX_TEST": 100 + np.cumsum(rng.normal(0, 0.5, n))}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _config(tmp_path, name: str, families: list[str]) -> RunConfig:
    return RunConfig.model_validate({
        "name": name,
        "objective": {"target_symbol": TARGET, "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
                     "start_date": "2015-01-01"},
        "features": {"families": families, "interact_top_base": 15, "interact_top_pairs": 8,
                     "interact_final_n": 6, "pool_prefilter": 60},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "runs" / name), "seed": 42},
    })


def test_second_run_duels_the_first_on_the_same_holdout(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    store = DataStore(root=str(tmp_path / "store"))
    store.save(f"raw_{TARGET}", _raw(), meta={"pit_version": f"{PIT_VERSION}:publication_lag"})

    first = run_pipeline(_config(tmp_path, "first", ["technical", "interactions", "spike", "vol_models", "macro"]),
                         store=store, db_path=db_path)
    assert first["champions"][5]["decision"] == "promoted_first"
    conn = trackdb.connect(db_path)
    first_run = champions.current(conn, TARGET, 5)["run_id"]
    conn.close()

    second = run_pipeline(_config(tmp_path, "second", ["technical", "macro"]), store=store, db_path=db_path)

    decision = second["champions"][5]
    assert decision["decision"] in ("challenger_wins", "champion_wins"), decision
    conn = trackdb.connect(db_path)
    try:
        in_title = champions.current(conn, TARGET, 5)
        assert not in_title["implicit"]
        archived = champions.list_archive(conn, TARGET, 5)
        assert len(archived) == 1
        loser = archived[0]["run_id"]
        assert loser == decision["pruned_run"] != in_title["run_id"]
        assert first_run in (loser, in_title["run_id"])
        assert conn.execute("SELECT COUNT(*) FROM run WHERE run_id = ?", (loser,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM run WHERE run_id = ?", (in_title["run_id"],)).fetchone()[0] == 1
        duel = json.loads(archived[0]["duel_json"])
        assert duel["champion_pool"] == "rebuilt"
        assert duel["champion"]["f1_dir"] == pytest.approx(decision["champion_f1_dir"])
        assert duel["challenger"]["f1_dir"] == pytest.approx(decision["challenger_f1_dir"])
        assert duel["holdout_start"] < duel["holdout_end"]
        assert conn.execute("SELECT COUNT(*) FROM trial_registry WHERE run_id = ?", (loser,)).fetchone()[0] > 0
    finally:
        conn.close()
