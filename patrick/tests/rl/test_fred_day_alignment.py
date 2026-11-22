"""Fuite des séries FRED du jour pour une cible d'Asie d'avant l'alignement version 2 (ADR 0007, complément du 2026-11-21).

La valeur FRED quotidienne datée d (VIX de clôture, écarts de crédit) se fixe à New York vers 20 h UTC, après la clôture de Tokyo, Séoul ou
Bombay : jointe à la date d, elle annonçait la séance asiatique suivante (corrélation de rang du VIX FRED avec le rendement du lendemain
-0,195 sur ^N225). Depuis le 28/10 l'alignement la retarde d'un jour ; les runs d'avant sont marqués non crédibles, comme les runs de
change sous la règle 1."""
from __future__ import annotations

import json

import pytest

from patrick.config.schema import RunConfig
from patrick.data.freshness import fred_periodicity
from patrick.rl import reading
from patrick.rl.history import FRED_DAY_WARNING, FX_ALIGNMENT_WARNING, display_warnings
from patrick.tracking import db as trackdb
from patrick.validation import suspicion


def _config(target: str, version: int = 1, mode: str = "alfred", series: dict | None = None) -> dict:
    cfg = RunConfig.model_validate({
        "name": "t", "output": {"dir": "out"},
        "objective": {"target_symbol": target, "session_rule": 2, "alignment": {"version": version}},
        "universe": {"fred_point_in_time": mode, "fred_series": {"VIX": "VIXCLS"} if series is None else series}})
    return json.loads(cfg.model_dump_json())


def test_the_fixture_series_have_the_expected_periodicity():
    assert fred_periodicity("VIXCLS") == "daily" and fred_periodicity("CPIAUCSL") != "daily"


@pytest.mark.parametrize("target", ["^N225", "^KS11", "^NSEI", "7203.T", "0700.HK"])
def test_an_asian_target_before_alignment_v2_with_a_daily_fred_series_is_flagged(target):
    reason = suspicion.alignment_reason(target, _config(target))
    assert reason == suspicion.FRED_DAY_REASON and reason.startswith(suspicion.FRED_DAY_LABEL)


def test_the_flag_needs_every_condition():
    assert suspicion.alignment_reason("^N225", _config("^N225", version=2)) is None              # alignement actuel : séries retardées
    assert suspicion.alignment_reason("^N225", _config("^N225", mode="publication_lag")) is None  # datée de sa publication (J+1)
    assert suspicion.alignment_reason("^N225", _config("^N225", mode="reference_date")) == suspicion.FRED_DAY_REASON
    assert suspicion.alignment_reason("^N225", _config("^N225", series={"CPI": "CPIAUCSL"})) is None  # aucune série quotidienne
    assert suspicion.alignment_reason("^N225", _config("^N225", series={})) is None
    assert suspicion.alignment_reason("^FCHI", _config("^FCHI")) is None      # Europe : sous le seuil d'audit, non marquée
    assert suspicion.alignment_reason("^GSPC", _config("^GSPC")) is None
    assert suspicion.alignment_reason("AAPL", _config("AAPL")) is None


def test_a_config_without_alignment_counts_as_version_zero():
    cfg = _config("^N225")
    del cfg["objective"]["alignment"]
    assert suspicion.alignment_reason("^N225", cfg) == suspicion.FRED_DAY_REASON


def test_alignment_reasons_lists_the_legacy_asian_runs(tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "snap", "hash", 0, 1, "api")
    runs = (("asia_old", "^N225", 1), ("asia_new", "^N225", 2), ("eu_old", "^FCHI", 1), ("jp_old", "7203.T", 1))
    for run_id, target, version in runs:
        trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="snap", config_json=json.dumps(_config(target, version)),
                           config_hash="x", git_sha="x", seed=1)
    reasons = trackdb.alignment_reasons(conn, [r[0] for r in runs])
    assert set(reasons) == {"asia_old", "jp_old"} and reasons["asia_old"] == suspicion.FRED_DAY_REASON
    suspects = {r["run_id"]: r["suspect"] for r in trackdb.list_all_runs(conn)}
    assert suspects["asia_old"] and not suspects["asia_new"] and not suspects["eu_old"]
    conn.close()


def _rl_result(target: str, version: int) -> dict:
    return {"kind": "rl", "target": target, "config": _config(target, version), "warnings": [],
            "strategy": {"sharpe": 1.8, "cagr": 0.2}, "baselines": {"buy_hold": {"sharpe": 0.7, "cagr": 0.05}},
            "stats": {"vs_buy_hold": {"diff": 1.1, "p_one_sided": 0.002}}}


def test_an_rl_run_on_an_asian_index_before_alignment_v2_reads_as_a_leak():
    rd = reading.of_result(_rl_result("^N225", 1))
    assert rd["verdict"] == "leak" and rd["leak"] == "fred_day"
    listed = reading.derive(json.loads(json.dumps(reading.from_result(_rl_result("^N225", 1)))), "^N225")
    assert listed["leak"] == "fred_day"
    as_sql = reading.from_result(_rl_result("^N225", 1))
    as_sql["fred_series"] = json.dumps(as_sql["fred_series"])            # `json_extract` rend un objet en texte JSON
    assert reading.derive(as_sql, "^N225")["leak"] == "fred_day"
    assert reading.of_result(_rl_result("^N225", 2))["verdict"] == "beats"


def test_the_rl_warning_names_the_right_leak():
    assert display_warnings(_rl_result("^N225", 1))["warnings"] == [FRED_DAY_WARNING]
    assert display_warnings(_rl_result("^N225", 2))["warnings"] == []
    fx = _rl_result("EURUSD=X", 2)
    fx["config"]["objective"]["session_rule"] = 1
    assert display_warnings(fx)["warnings"] == [FX_ALIGNMENT_WARNING]
