"""Affichages des runs RL après la refonte (ADR 0022) : chaque page montre la lecture du run (`rl.reading`) -- verdict, moteur, écart
annuel avec acheter-garder, part de l'agent, frais -- et, pour un run du moteur 2, la tendance 200 j, l'agent sans repli et les plis
repliés."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.analysis import hub, rl_sections
from patrick.rl.config import RLRunConfig
from patrick.tracking import db
from patrick.tracking import jobs as jobs_db
from patrick.webapp.app import app


def _summary(sharpe, total=0.1, mdd=-0.2, **extra):
    return {"sharpe": sharpe, "total_return": total, "max_drawdown": mdd, **extra}


def _fold(i, gated, val_score, start, end):
    return {"fold": i, "train_start": "2015-01-02", "train_end": f"{start[:4]}-01-01", "fit_end": f"{int(start[:4]) - 1}-06-30",
            "val_start": f"{int(start[:4]) - 1}-07-02", "test_start": start, "test_end": end, "n_train": 1250, "n_fit": 1000, "n_val": 120,
            "n_test": 250, "val_score": val_score, "gated": gated, "strategy": _summary(0.3), "agent": _summary(0.1),
            "buy_hold": _summary(0.6), "features": ["vix_ret_1d"]}


def _v2_result(csv_path: str | None = None) -> dict:
    dates = list(pd.bdate_range("2020-01-02", periods=4).strftime("%Y-%m-%d"))
    return {
        "kind": "rl", "name": "agent_v2", "target": "^GSPC", "algo": "PPO", "engine_version": 2, "session_rule": 2, "n_folds": 2,
        "elapsed_s": 60.0, "start": "2015-01-02", "end": "2021-12-31", "n_rows": 1750, "n_features_pool": 40,
        "strategy": _summary(0.4, cagr=0.03, agent_share=0.5, cost_ann=0.003, turnover=4.0, n=500, gross_return_ann=0.033,
                             long_contrib_ann=0.033, short_contrib_ann=0.0, cost_drag=0.006),
        "agent_ungated": _summary(0.2, cagr=0.01),
        "baselines": {"buy_hold": _summary(0.6, 0.2, -0.3, cagr=0.05), "trend": _summary(0.34), "momentum": _summary(-0.2),
                      "flat": _summary(0.0, 0.0, 0.0)},
        "stats": {"excess_log_growth": -0.02, "psr": 0.7, "dsr": {"dsr": 0.3}, "n_trials": 2,
                  "vs_buy_hold": {"diff": -0.2, "ci_low": -0.5, "ci_high": 0.1, "p_one_sided": 0.8, "n": 500, "block": 5},
                  "vs_trend": {"diff": 0.06, "ci_low": -0.3, "ci_high": 0.4, "p_one_sided": 0.4, "n": 500, "block": 5},
                  "vs_momentum": {"diff": 0.6, "ci_low": 0.1, "ci_high": 1.0, "p_one_sided": 0.01, "n": 500, "block": 5},
                  "delay": {"gross_sharpe": 0.5, "lagged_sharpe": 0.45, "suspect": False}},
        "folds": [_fold(1, True, -0.01, "2020-01-02", "2020-12-31"), _fold(2, False, 0.02, "2021-01-04", "2021-12-31")],
        "curves": {"dates": dates, "strategy": [1.0, 1.01, 1.0, 1.02], "buy_hold": [1.0, 1.02, 1.01, 1.03], "momentum": [1, 1, 1, 1],
                   "trend": [1.0, 1.01, 1.01, 1.02], "agent": [1.0, 0.99, 0.98, 1.0], "position": [1, 1, 0.5, 1]},
        "seeds": [{"seed": 1, "sharpe": 0.4, "total_return": 0.1, "ruined": False}],
        "warnings": [], "artifacts": {"oos_csv": csv_path} if csv_path else {},
    }


def _v1_result() -> dict:
    return {"kind": "rl", "name": "agent_v1", "target": "^GSPC", "algo": "PPO", "n_folds": 4, "elapsed_s": 120.0,
            "strategy": _summary(0.8, 0.2, -0.1, cagr=0.10, cost_drag=0.05, n=1260, turnover=60.0),
            "baselines": {"buy_hold": _summary(0.5, 0.12, -0.25, cagr=0.05), "momentum": _summary(0.3), "flat": _summary(0.0, 0.0, 0.0)},
            "stats": {"psr": 0.91, "dsr": {"dsr": 0.64}, "n_trials": 3, "vs_buy_hold": {"diff": 0.3, "ci_low": -0.1, "ci_high": 0.7, "p_one_sided": 0.2}},
            "folds": [{"fold": 1, "train_start": "2015-01-02", "train_end": "2019-12-31", "test_start": "2020-01-02", "test_end": "2020-12-31",
                       "n_train": 1250, "n_test": 250, "strategy": _summary(0.8), "buy_hold": _summary(0.5), "features": ["a"]}],
            "seeds": [{"seed": 1, "sharpe": 0.8}], "curves": {"dates": ["2020-01-02", "2020-01-03"], "strategy": [1.0, 1.01]}}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    c = db.connect(db.default_db_path())
    yield c
    c.close()


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _add(conn, name: str, result: dict, target: str = "^GSPC") -> str:
    cfg = RLRunConfig.model_validate({"name": name, "objective": {"target_symbol": target}, "rl": {"algo": "PPO"}})
    job_id = jobs_db.enqueue_job(conn, cfg.model_dump_json())
    jobs_db.claim_next_job(conn, 123)
    jobs_db.finish_job(conn, job_id, "done", result_json=json.dumps(result))
    return job_id


def _csv(tmp_path) -> str:
    n = 300
    rng = np.random.default_rng(0)
    controls = np.r_[np.zeros(150), np.ones(150)].astype(int)            # premier pli replié, second tenu par l'agent
    agent_pos = rng.choice([0.0, 0.5, 1.0], n)
    path = tmp_path / "rl_oos.csv"
    pd.DataFrame({"date": pd.bdate_range("2020-01-02", periods=n), "position": np.where(controls, agent_pos, 1.0),
                  "net_return": rng.normal(0, 0.01, n), "cost": np.zeros(n), "buy_hold_return": rng.normal(0, 0.01, n),
                  "momentum_return": rng.normal(0, 0.01, n), "trend_return": rng.normal(0, 0.01, n), "agent_position": agent_pos,
                  "agent_net_return": rng.normal(0, 0.01, n), "agent_controls": controls}).to_csv(path, index=False)
    return str(path)


def test_the_side_panel_of_an_engine_2_run_shows_its_fallback(conn, client):
    job = _add(conn, "agent_v2", _v2_result())
    text = client.get(f"/runs/{job}/panel").text
    assert "Moteur 2" in text and "Sous acheter-garder" in text and "-2.0 %" in text and ">50 %<" in text and ">0.3 %<" in text
    assert "Agent sans repli" in text and "Tendance 200 j" in text and "Momentum" not in text     # la tendance remplace le momentum
    assert "1 repliés" in text and "+0.06" in text                                                 # plis repliés, écart contre la tendance


def test_the_rl_page_lists_recent_runs_with_their_reading(conn, client):
    _add(conn, "agent_v2", _v2_result())
    runs = client.get("/api/rl/runs").json()["runs"]
    assert runs[0]["verdict"] == "worse" and runs[0]["engine"] == 2 and runs[0]["excess"] == pytest.approx(-0.02)


def test_the_results_of_an_rl_run_carry_its_reading(conn, client):
    job = _add(conn, "agent_v1", _v1_result())
    reading = client.get(f"/runs/{job}/results").json()["reading"]
    assert reading["engine"] == 1 and reading["verdict"] == "better" and reading["agent_share"] == 1.0


def test_the_comparison_starts_with_the_reading(conn, client):
    old, new = _add(conn, "agent_v1", _v1_result()), _add(conn, "agent_v2", _v2_result())
    text = client.get("/compare-runs", params=[("run_ids", old), ("run_ids", new)]).text
    assert text.index("Lecture") < text.index("Résultats hors échantillon")
    assert "Moteur 1" in text and "Moteur 2" in text and "Au-dessus, sans preuve" in text and "Sous acheter-garder" in text
    assert "Plis repliés sur acheter et garder" in text and "+4.7 %" in text and "-2.0 %" in text


def test_the_analysis_sections_of_an_engine_2_run(conn, tmp_path):
    job = _add(conn, "agent_v2", _v2_result(_csv(tmp_path)))
    overview = rl_sections.build(conn, job, "overview")
    assert overview["reading"]["verdict"] == "worse" and overview["reading"]["engine"] == 2 and overview["agent_ungated"]["sharpe"] == 0.2
    folds = rl_sections.build(conn, job, "folds")
    assert folds["n_gated"] == 1 and folds["folds"][0]["gated"] is True and folds["folds"][1]["val_score"] == 0.02
    equity = rl_sections.build(conn, job, "equity")
    assert {"agent", "agent_raw", "buy_hold", "trend", "momentum", "flat"} <= set(equity["curves"])
    assert equity["agent_share"] == pytest.approx(0.5) and "agent_raw" in equity["stats"] and "trend" in equity["stats"]
    assert rl_sections.build(conn, job, "stats")["reading"]["verdict"] == "worse"


def test_an_engine_1_analysis_has_no_engine_2_extras(conn):
    job = _add(conn, "agent_v1", _v1_result())
    folds = rl_sections.build(conn, job, "folds")
    assert folds["n_gated"] is None and folds["folds"][0]["gated"] is None
    assert rl_sections.build(conn, job, "overview")["reading"]["engine"] == 1


def test_the_analyses_hub_marks_alerts_and_engines(conn):
    _add(conn, "agent_v2", _v2_result())
    _add(conn, "agent_fx", {**_v1_result(), "target": "EURUSD=X"}, target="EURUSD=X")
    rows = {r["name"]: r for r in hub._rl_rows(conn)}
    assert rows["agent_v2"]["verdict"] == "worse" and rows["agent_v2"]["engine"] == 2
    assert rows["agent_fx"]["verdict"] == "leak" and rows["agent_fx"]["engine"] == 1
