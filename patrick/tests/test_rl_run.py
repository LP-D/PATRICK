"""Un run RL complet (`rl/run.py`) sur données synthétiques, sans réseau : seul `ingest()` est remplacé ; la construction des variables,
la sélection par pli, l'entraînement SB3, l'évaluation, les tests statistiques et l'écriture des fichiers tournent pour de vrai."""
from __future__ import annotations

import importlib.util
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

for _module in ("torch", "gymnasium", "stable_baselines3"):
    if importlib.util.find_spec(_module) is None:
        pytest.skip(f"{_module} non installé (extra optionnel rl)", allow_module_level=True)

from patrick.data.store import DataStore
from patrick.rl import data as rl_data
from patrick.rl import run as rl_run
from patrick.rl.config import RLRunConfig


def _raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    market = np.cumsum(rng.normal(0.0004, 0.01, n))
    df = pd.DataFrame({"IDX_TEST": 50 * np.exp(market + np.cumsum(rng.normal(0, 0.004, n)))}, index=idx)
    df["SPX_LIKE"] = 3000 * np.exp(market)
    return df


def _config(tmp_path, **rl) -> RLRunConfig:
    return RLRunConfig.model_validate({
        "name": "rl_smoke", "objective": {"target_symbol": "^TEST"},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {}, "start_date": "2015-01-01"},
        "features": {"families": ["technical"]},
        "rl": {"n_folds": 2, "min_train_frac": 0.5, "max_features": 6, "total_timesteps": 1500, "n_steps": 64, "batch_size": 32,
               "n_epochs": 2, "policy_units": 16, "policy_layers": 1, "episode_length": 100, "bootstrap_samples": 300, **rl},
        "output": {"dir": str(tmp_path / "runs" / "rl_smoke"), "seed": 11}})


def test_a_full_run_writes_its_result_and_every_metric_is_finite_or_none(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_run, "ingest", lambda *a, **k: _raw())
    lines: list[str] = []
    result = rl_run.run_rl(_config(tmp_path), store=DataStore(root=str(tmp_path / "store")), progress=lines.append)

    assert result["kind"] == "rl" and result["algo"] == "PPO" and result["n_folds"] == 2
    assert len(result["folds"]) == 2 and result["strategy"]["n"] == sum(f["n_test"] for f in result["folds"])
    for leg in ("buy_hold", "momentum", "flat"):
        assert leg in result["baselines"]
    assert {"vs_buy_hold", "vs_momentum", "psr", "dsr", "n_trials"} <= set(result["stats"]) and result["stats"]["n_trials"] == 1
    assert result["curves"]["dates"] and len(result["curves"]["strategy"]) == len(result["curves"]["buy_hold"]) == len(result["curves"]["position"])
    assert result["config"]["kind"] == "rl" and "oos" not in result
    json.dumps(result, allow_nan=False)                                       # aucun NaN : JSON strict pour le navigateur

    out = tmp_path / "runs" / "rl_smoke"
    assert (out / "rl_result.json").exists() and (out / "rl_oos.csv").exists()
    assert list((out / "models").glob("*.zip"))
    saved = json.loads((out / "rl_result.json").read_text(encoding="utf-8"))
    assert saved["strategy"] == result["strategy"]
    oos = pd.read_csv(out / "rl_oos.csv")
    assert len(oos) == result["strategy"]["n"] and oos["position"].between(-1, 1).all()
    assert any(line.startswith("[RL-PROGRESS] 2/2") for line in lines)


def test_the_run_is_reproducible(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_run, "ingest", lambda *a, **k: _raw())
    cfg = _config(tmp_path)
    a = rl_run.run_rl(cfg, store=DataStore(root=str(tmp_path / "s1")), progress=lambda line: None)
    b = rl_run.run_rl(cfg, store=DataStore(root=str(tmp_path / "s2")), progress=lambda line: None)
    assert a["strategy"] == b["strategy"] and a["curves"]["position"] == b["curves"]["position"]


def test_a_continuous_sac_run_and_a_two_seed_ensemble_work_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_run, "ingest", lambda *a, **k: _raw())
    cfg = _config(tmp_path, algo="SAC", action_space="continuous", n_seeds=2, n_folds=1, total_timesteps=1200, learning_starts=100,
                  buffer_size=2000)
    result = rl_run.run_rl(cfg, store=DataStore(root=str(tmp_path / "store")), progress=lambda line: None)
    assert len(result["seeds"]) == 2 and result["n_folds"] == 1


def test_prior_runs_on_the_same_target_count_as_trials(tmp_path):
    db = tmp_path / "patrick.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE job (job_id TEXT, status TEXT, config_json TEXT)")
    rl = '{"kind":"rl","objective":{"target_symbol":"^TEST","target_source":"yfinance"}}'
    ml = '{"objective":{"target_symbol":"^TEST","target_kind":"raw"}}'
    other = '{"kind":"rl","objective":{"target_symbol":"AAPL"}}'
    conn.executemany("INSERT INTO job VALUES (?, ?, ?)", [("1", "done", rl), ("2", "error", rl), ("3", "queued", rl), ("4", "done", ml), ("5", "done", other)])
    conn.commit()
    conn.close()
    assert rl_run.count_prior_rl_runs(str(db), "^TEST") == 2                  # ni les runs ML, ni les autres cibles, ni les jobs en attente
    assert rl_run.count_prior_rl_runs(str(tmp_path / "absent.db"), "^TEST") == 0 and rl_run.count_prior_rl_runs(None, "^TEST") == 0


def test_a_target_with_too_little_history_is_refused_before_any_training(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_run, "ingest", lambda *a, **k: _raw(n=300))
    with pytest.raises(rl_data.RLDataError, match="trop court"):
        rl_run.run_rl(_config(tmp_path), store=DataStore(root=str(tmp_path / "store")), progress=lambda line: None)


def test_a_non_positive_price_is_refused(tmp_path, monkeypatch):
    raw = _raw()
    raw.iloc[100, 0] = -1.0
    monkeypatch.setattr(rl_run, "ingest", lambda *a, **k: raw)
    with pytest.raises(rl_data.RLDataError, match="négatif"):
        rl_run.run_rl(_config(tmp_path), store=DataStore(root=str(tmp_path / "store")), progress=lambda line: None)


def test_raw_price_levels_are_never_part_of_the_state(tmp_path):
    raw = _raw()
    data = rl_data.build_rl_data(raw, _config(tmp_path), "IDX_TEST")
    assert not set(raw.columns) & set(data.features.columns)
    assert data.price.index[0] == data.dates[0] and len(data.price) == data.n + 1
    assert np.allclose(data.fwd_ret, (data.price.shift(-1) / data.price - 1).iloc[:-1].to_numpy())
