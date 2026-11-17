"""Lecture d'un run RL (`rl.reading`) : chiffres reconstitués pour le moteur 1, verdicts, alertes, lecture SQL identique à la lecture d'un
résultat chargé."""
from __future__ import annotations

import json
import math
import sqlite3

import pytest

from patrick.rl import reading


def _v1(**strategy) -> dict:
    """Résultat du moteur 1 : ni `engine_version`, ni `excess_log_growth`, ni `agent_share`, ni `cost_ann`."""
    return {"kind": "rl", "target": "^GSPC",
            "strategy": {"sharpe": 0.8, "cagr": 0.10, "turnover": 66.0, "cost_drag": 0.92, "n": 3150, **strategy},
            "baselines": {"buy_hold": {"sharpe": 0.5, "cagr": 0.05}},
            "stats": {"vs_buy_hold": {"diff": 0.3, "p_one_sided": 0.2}}}


def _v2(**over) -> dict:
    base = {"kind": "rl", "target": "^GSPC", "engine_version": 2, "session_rule": 2,
            "strategy": {"sharpe": 0.4, "cagr": 0.06, "agent_share": 0.4, "cost_ann": 0.003, "turnover": 4.0, "n": 1000},
            "baselines": {"buy_hold": {"sharpe": 0.5, "cagr": 0.08}, "trend": {"sharpe": 0.34}},
            "stats": {"excess_log_growth": -0.013, "vs_buy_hold": {"diff": -0.1, "p_one_sided": 0.7},
                      "delay": {"gross_sharpe": 0.5, "lagged_sharpe": 0.45, "suspect": False}}}
    for key, value in over.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return base


def test_an_engine_1_run_gets_its_missing_figures_rebuilt():
    rd = reading.of_result(_v1())
    assert rd["engine"] == 1
    assert rd["excess"] == pytest.approx(math.log1p(0.10) - math.log1p(0.05))
    assert rd["agent_share"] == 1.0                                   # pas de repli au moteur 1
    assert rd["cost_ann"] == pytest.approx(0.92 * 252 / 3150)         # somme des coûts ramenée à l'année
    assert rd["verdict"] == "better" and rd["verdict_state"] == "neutral"


def test_an_engine_2_run_reads_its_own_figures():
    rd = reading.of_result(_v2())
    assert rd["engine"] == 2 and rd["excess"] == pytest.approx(-0.013) and rd["agent_share"] == 0.4
    assert rd["cost_ann"] == pytest.approx(0.003) and rd["sharpe_trend"] == pytest.approx(0.34)
    assert rd["verdict"] == "worse"


def test_only_a_significant_gap_beats_buy_and_hold():
    assert reading.of_result(_v1(sharpe=0.9))["verdict"] == "better"
    won = _v1(sharpe=0.9)
    won["stats"]["vs_buy_hold"]["p_one_sided"] = 0.01
    rd = reading.of_result(won)
    assert rd["verdict"] == "beats" and rd["verdict_state"] == "ok" and reading.is_credible_win(rd)


def test_a_fully_gated_engine_2_run_is_buy_and_hold():
    assert reading.of_result(_v2(strategy={"agent_share": 0.0}))["verdict"] == "held_bh"


def test_an_fx_pair_before_the_session_rule_is_a_leak_and_after_it_is_not():
    old = {**_v1(), "target": "EURUSD=X"}
    old["stats"]["vs_buy_hold"]["p_one_sided"] = 0.001
    rd = reading.of_result(old)
    assert rd["verdict"] == "leak" and rd["leak"] == "fx_rule1" and rd["verdict_state"] == "error" and not reading.is_credible_win(rd)
    assert reading.of_result({**_v2(), "target": "EURUSD=X"})["verdict"] != "leak"


def test_the_one_day_delay_test_flags_a_leak():
    rd = reading.of_result(_v2(stats={"delay": {"gross_sharpe": 3.5, "lagged_sharpe": -0.1, "suspect": True}}))
    assert rd["verdict"] == "leak" and rd["leak"] == "delay"


def test_a_volatility_index_is_not_tradable():
    assert reading.of_result({**_v1(), "target": "^VIX"})["verdict"] == "untradable"


def test_an_unfinished_run_has_no_verdict():
    rd = reading.derive(dict.fromkeys(reading.FIELD_KEYS), "^GSPC", done=False)
    assert rd["verdict"] is None and rd["agent_share"] is None and rd["excess"] is None and rd["engine"] == 1


def test_the_sql_columns_read_the_same_fields_as_a_loaded_result():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE job (job_id TEXT, status TEXT, result_json TEXT)")
    results = {"a": _v1(), "b": _v2(stats={"delay": {"suspect": True}})}
    for job_id, result in results.items():
        conn.execute("INSERT INTO job VALUES (?, 'done', ?)", (job_id, json.dumps(result)))
    conn.execute("INSERT INTO job VALUES ('c', 'running', ?)", (json.dumps(_v1()),))
    for job_id, *values in conn.execute(f"SELECT job_id, {reading.sql_columns()} FROM job").fetchall():
        fields = dict(zip(reading.FIELD_KEYS, values, strict=True))
        if job_id == "c":
            assert all(v is None for v in fields.values())            # rien n'est lu tant que le job n'est pas terminé
            continue
        expected = reading.from_result(results[job_id])
        assert reading.derive(fields, "^GSPC") == reading.derive(expected, "^GSPC")


def test_the_log_line_says_the_gap_the_share_the_fees_and_the_verdict():
    line = reading.log_line(_v2())
    assert "Sharpe 0.40 (acheter-garder 0.50)" in line and "-1.3 %/an" in line and "40 %" in line
    assert "frais 0.3 %/an" in line and "lecture : sous acheter-garder" in line


def _oos_csv(tmp_path, leaky: bool) -> str:
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(1)
    ret = rng.normal(0.0004, 0.01, 800)
    pos = np.sign(ret) if leaky else rng.choice([-1.0, 0.0, 1.0], 800)      # fuite : la position « connaît » le rendement qu'elle joue
    path = tmp_path / ("leaky.csv" if leaky else "honest.csv")
    pd.DataFrame({"date": pd.bdate_range("2020-01-02", periods=800), "position": pos, "buy_hold_return": ret}).to_csv(path, index=False)
    return str(path)


def test_an_engine_1_winner_replays_the_delay_test_on_its_oos_file(tmp_path):
    won = _v1(sharpe=2.0)
    won["stats"]["vs_buy_hold"]["p_one_sided"] = 0.001
    won["artifacts"] = {"oos_csv": _oos_csv(tmp_path, leaky=True)}
    rd = reading.of_result(won)
    assert rd["verdict"] == "leak" and rd["leak"] == "delay" and rd["delay"]["suspect"] is True
    listed = reading.derive(reading.from_result(won), "^GSPC")           # même verdict depuis les colonnes SQL (liste de l'Historique)
    assert listed["verdict"] == "leak"
    won["artifacts"] = {"oos_csv": _oos_csv(tmp_path, leaky=False)}
    assert reading.of_result(won)["verdict"] == "beats"


def test_a_missing_oos_file_leaves_the_verdict_alone():
    won = _v1(sharpe=2.0)
    won["stats"]["vs_buy_hold"]["p_one_sided"] = 0.001
    won["artifacts"] = {"oos_csv": "nulle/part/rl_oos.csv"}
    rd = reading.of_result(won)
    assert rd["verdict"] == "beats" and rd["delay"] is None
