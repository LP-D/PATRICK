"""Positions live d'un agent RL (ADR 0029) : rejeu du dernier pli sur les données du jour. Faux modèle, fausses données : ni réseau ni PyTorch."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json

import numpy as np
import pandas as pd
import pytest

from patrick.rl import live
from patrick.rl.data import RLData

# Le rejeu passe par `rl/env.py` (traduction action -> position), qui importe gymnasium : extra optionnel, absent de la CI rapide.
needs_gym = pytest.mark.skipif(importlib.util.find_spec("gymnasium") is None, reason="gymnasium non installé (extra optionnel rl)")

DATES = pd.bdate_range("2025-01-01", periods=300)
TRAIN, FIT_END, TEST, END = DATES[0], DATES[150], DATES[200], DATES[260]   # le run s'arrête le 260e jour ; la suite est « live »


class Model:
    """Agent discret à trois niveaux (0, ½, 1) : pleinement acheteur quand la première variable mise à l'échelle est positive, sinon `low`."""

    def __init__(self, low: int = 2):
        self.low = low

    def predict(self, obs, deterministic=True):
        assert deterministic
        return np.array([2 if obs[0] > 0 else self.low]), None


def _data(config=None) -> RLData:
    rng = np.random.default_rng(3)
    features = pd.DataFrame({"f1": rng.normal(size=len(DATES)), "f2": rng.normal(size=len(DATES))}, index=DATES)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(DATES) + 1))))
    return RLData(dates=DATES, features=features, fwd_ret=np.zeros(len(DATES)), price=price, target_col="^TEST")


def _job(tmp_path, *, gated=False, oos_position=1.0, features=("f1", "f2"), models=True, oos_file=True) -> dict:
    model = tmp_path / "model_seed0.zip"
    model.write_bytes(b"x")
    oos = tmp_path / "rl_oos.csv"
    window = DATES[190:261]
    pd.DataFrame({"date": window, "position": [oos_position] * len(window)}).to_csv(oos, index=False)
    config = {"name": "rl_live", "objective": {"target_symbol": "^TEST"},
              "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {}, "start_date": "2015-01-01"},
              "features": {"families": ["technical"]}, "rl": {"n_seeds": 1}, "output": {"dir": str(tmp_path / "out"), "seed": 1}}
    fold = {"train_start": f"{TRAIN:%Y-%m-%d}", "fit_end": f"{FIT_END:%Y-%m-%d}", "test_start": f"{TEST:%Y-%m-%d}", "features": list(features),
            "gated": gated}
    artifacts = {**({"oos_csv": str(oos)} if oos_file else {}), **({"model_seed0": str(model)} if models else {})}
    return {"job_id": "job_rl", "config": config,
            "result": {"folds": [fold], "config": config, "artifacts": artifacts, "end": f"{END:%Y-%m-%d}", "target": "^TEST", "engine_version": 2}}


def _compute(job, model=None):
    return live.compute(job, build_data=_data, load_model=lambda path: model or Model())


@needs_gym
def test_the_last_fold_agent_is_replayed_after_the_run_and_its_position_is_scaled_by_the_leverage(tmp_path):
    res = _compute(_job(tmp_path))

    assert res.status == "ok" and res.agreement == 1.0
    assert res.positions.index[0] == DATES[261] and res.positions.index[-1] == DATES[-1]       # rien avant la fin du run
    assert set(res.positions.round(6)) == {1.0}


def test_a_gated_fold_has_no_opinion_and_nothing_is_replayed(tmp_path):
    def boom(config):
        raise AssertionError("aucune donnée ne doit être recalculée")

    res = live.compute(_job(tmp_path, gated=True), build_data=boom, load_model=lambda p: Model())

    assert res.status == "gated" and res.positions.empty


@needs_gym
def test_a_replay_that_no_longer_finds_the_original_positions_is_discarded(tmp_path):
    res = _compute(_job(tmp_path, oos_position=0.0))                  # le run était à plat, le rejeu est acheteur : le monde a changé

    assert res.status == "drift" and res.positions.empty and res.agreement == 0.0


def test_missing_features_or_models_stop_the_replay(tmp_path):
    assert _compute(_job(tmp_path, features=("f1", "disparue"))).status == "drift"
    assert _compute(_job(tmp_path, models=False)).status == "no_models"


@needs_gym
def test_the_replay_reads_the_features_of_the_fold_and_holds_between_two_decisions(tmp_path):
    res = _compute(_job(tmp_path, oos_file=False), model=Model(low=0))       # à plat quand f1 (mise à l'échelle) est négative ; sans fichier hors
                                                                             # échantillon, pas de contrôle d'accord
    assert res.status == "ok" and res.agreement is None
    assert set(res.positions.round(6)) == {0.0, 1.0}
    changes = np.flatnonzero(np.diff(res.positions.to_numpy()) != 0) + 1 + 261 - 200   # rang dans le pli : une décision toutes les 5 barres
    assert all(c % 5 == 0 for c in changes)


def test_a_recorded_session_is_never_rewritten_and_late_sessions_are_marked_as_backfill(conn):
    first = live.LiveResult("job_rl", "ok", pd.Series([1.0, 0.0], index=pd.DatetimeIndex(["2026-01-05", "2026-01-15"])), 0.95)
    again = live.LiveResult("job_rl", "ok", pd.Series([0.0, 1.0, 1.0], index=pd.DatetimeIndex(["2026-01-05", "2026-01-15", "2026-01-16"])), 0.9)

    assert live.record(conn, first, dt.date(2026, 1, 16)) == 2
    assert live.record(conn, again, dt.date(2026, 1, 16)) == 1

    assert live.positions(conn, "job_rl").tolist() == [1.0, 0.0, 1.0]
    rows = conn.execute("SELECT ts, backfill FROM rl_live_position ORDER BY ts").fetchall()
    assert rows == [("2026-01-05", 1), ("2026-01-15", 0), ("2026-01-16", 0)]
    assert live.record(conn, live.LiveResult("job_rl", "drift", pd.Series(dtype=float)), dt.date(2026, 1, 16)) == 0


@pytest.mark.parametrize("position, direction", [(None, None), (float("nan"), None), (0.9, 1), (0.5, 0), (0.0, 0), (-0.8, -1)])
def test_direction_of_a_position(position, direction):
    assert live.direction(position) == direction


def _insert_job(conn, job_id: str, job: dict) -> None:
    conn.execute("INSERT INTO job (job_id, config_json, status, phase, result_json) VALUES (?, ?, 'done', 'done', ?)",
                 (job_id, json.dumps(job["config"]), json.dumps(job["result"])))
    conn.commit()


def test_refresh_reports_each_agent_and_an_error_never_stops_the_others(conn, tmp_path):
    _insert_job(conn, "job_gated", _job(tmp_path, gated=True))
    conn.execute("INSERT INTO job (job_id, config_json, status, phase, result_json) VALUES ('job_bad', '{}', 'done', 'done', '{\"folds\": [{}]}')")
    conn.execute("INSERT INTO job (job_id, config_json, status, phase, result_json) VALUES ('job_gone', '{}', 'done', 'deleted', '{}')")
    conn.commit()

    out = live.refresh(conn, ["job_bad", "job_gated", "job_gone", "job_gated"], today=dt.date(2026, 1, 16), build_data=_data,
                       load_model=lambda p: Model())

    assert [(o["job_id"], o["status"]) for o in out] == [("job_bad", "error"), ("job_gated", "gated"), ("job_gone", "missing")]
    assert out[1]["written"] == 0 and live.positions(conn, "job_gated").empty


@needs_gym
def test_refresh_writes_the_live_positions_of_a_replayed_agent(conn, tmp_path):
    _insert_job(conn, "job_rl", _job(tmp_path))

    (done,) = live.refresh(conn, ["job_rl"], today=dt.date(2026, 1, 16), build_data=_data, load_model=lambda p: Model())

    assert done["status"] == "ok" and done["written"] == len(DATES) - 261 and len(live.positions(conn, "job_rl")) == len(DATES) - 261
