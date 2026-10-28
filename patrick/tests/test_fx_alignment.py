"""Alignement des cibles de change (ADR 0007).

Les barres Yahoo `=X` datées d portent le cours du DÉBUT de la journée d : le label d'une ligne (prix d+1 / prix d) est le
mouvement réel de la journée d, que les clôtures du jour d (or, S&P 500) expliquent par simple corrélation. Placebo EURUSD h=1 :
exactitude 70,8 % -> 45,8 % quand les variables sont retardées d'un jour de plus. La règle 2 retarde d'une barre toute série
cotée qui n'est pas une paire `=X` face à une cible `=X` ; la règle 1 (tout run enregistré avant le champ) est inchangée.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import ObjectiveConfig, RunConfig
from patrick.data.ingest import _apply_session_lag
from patrick.data.session_calendar import (
    CURRENT_SESSION_RULE,
    session_lag_days,
    session_rule_tag,
)
from patrick.pipeline import engine
from patrick.tracking import db as trackdb
from patrick.validation import suspicion


def test_current_rule_is_two():
    assert CURRENT_SESSION_RULE == 2


@pytest.mark.parametrize("feature", ["GC=F", "SI=F", "^GSPC", "AAPL", "DX-Y.NYB", "BTC-USD", "^FCHI", "^N225"])
def test_rule_two_delays_every_non_fx_series_for_a_fx_target(feature):
    assert session_lag_days(feature, "yfinance", "EURUSD=X", "yfinance", rule=2) == 1


def test_rule_two_leaves_other_fx_pairs_aligned_with_a_fx_target():
    assert session_lag_days("GBPUSD=X", "yfinance", "EURUSD=X", "yfinance", rule=2) == 0


def test_rule_one_is_the_original_rule_for_a_fx_target():
    # règle d'origine : le change « clôture à 22 h UTC », donc l'or (21 h) et le S&P 500 (20 h) n'étaient pas retardés
    assert session_lag_days("GC=F", "yfinance", "EURUSD=X", "yfinance") == 0
    assert session_lag_days("^GSPC", "yfinance", "EURUSD=X", "yfinance") == 0
    assert session_lag_days("BTC-USD", "yfinance", "EURUSD=X", "yfinance") == 1


@pytest.mark.parametrize("target", ["^GSPC", "AAPL", "GC=F", "BTC-USD", "^FCHI", "^N225"])
def test_rule_two_changes_nothing_for_a_target_that_is_not_a_fx_pair(target):
    for feature in ("EURUSD=X", "GC=F", "^GSPC", "BNP.PA", "7203.T"):
        assert session_lag_days(feature, "yfinance", target, "yfinance", rule=2) == session_lag_days(
            feature, "yfinance", target, "yfinance", rule=1)


def test_a_fred_target_is_still_never_lagged_here():
    assert session_lag_days("GC=F", "yfinance", "DGS10", "fred", rule=2) == 0


def test_apply_session_lag_delays_gold_and_the_index_but_not_another_pair():
    idx = pd.bdate_range("2020-01-01", periods=6)
    frame = pd.DataFrame({"GC_F": np.arange(6, dtype=float), "IDX_GSPC": np.arange(10, 16, dtype=float),
                          "GBPUSD=X": np.arange(20, 26, dtype=float)}, index=idx)
    tickers = ["GC=F", "^GSPC", "GBPUSD=X"]
    new = _apply_session_lag(frame, tickers, ObjectiveConfig(target_symbol="EURUSD=X", session_rule=2))
    assert np.isnan(new["GC_F"].iloc[0]) and new["GC_F"].iloc[1] == frame["GC_F"].iloc[0]
    assert np.isnan(new["IDX_GSPC"].iloc[0]) and new["IDX_GSPC"].iloc[3] == frame["IDX_GSPC"].iloc[2]
    pd.testing.assert_series_equal(new["GBPUSD=X"], frame["GBPUSD=X"])
    old = _apply_session_lag(frame, tickers, ObjectiveConfig(target_symbol="EURUSD=X"))
    pd.testing.assert_series_equal(old["GC_F"], frame["GC_F"])                    # règle 1 : aucun retard sur l'or


def test_the_snapshot_cache_version_only_changes_for_a_fx_target_under_rule_two():
    assert session_rule_tag("EURUSD=X", "yfinance", 2) == ":fx-start-of-day"
    assert session_rule_tag("EURUSD=X", "yfinance", 1) == ""
    assert session_rule_tag("^GSPC", "yfinance", 2) == ""
    assert session_rule_tag("EURUSD=X", "fred", 2) == ""


def _config(target: str, rule: int) -> RunConfig:
    return RunConfig.model_validate({"name": "t", "objective": {"target_symbol": target, "session_rule": rule},
                                     "output": {"dir": "out"}})


def test_the_config_hash_moves_for_a_fx_target_only():
    assert engine._config_hash(_config("EURUSD=X", 2)) != engine._config_hash(_config("EURUSD=X", 1))
    assert engine._config_hash(_config("^GSPC", 2)) == engine._config_hash(_config("^GSPC", 1))


def test_a_stored_config_without_the_field_reads_as_rule_one():
    data = json.loads(_config("EURUSD=X", 2).model_dump_json())
    del data["objective"]["session_rule"]
    assert RunConfig.model_validate_json(json.dumps(data)).objective.session_rule == 1
    assert RunConfig.from_stored_json(json.dumps(data)).objective.session_rule == 1


def test_a_new_run_gets_the_current_rule_and_a_resume_keeps_its_own(monkeypatch):
    seen: list[int] = []

    def spy(objective, *args, **kwargs):
        seen.append(objective.session_rule)
        raise RuntimeError("stop")

    monkeypatch.setattr(engine, "ingest", spy)
    monkeypatch.setattr(engine, "load_snapshot", lambda objective, *a, **k: spy(objective))
    for snapshot_id in (None, "snap-1"):
        with pytest.raises(RuntimeError, match="stop"):
            engine.run_pipeline(_config("EURUSD=X", 1), snapshot_id=snapshot_id)
    assert seen == [CURRENT_SESSION_RULE, 1]


def test_alignment_reason_flags_a_fx_run_trained_under_rule_one_only():
    legacy = json.loads(_config("EURUSD=X", 1).model_dump_json())
    current = json.loads(_config("EURUSD=X", 2).model_dump_json())
    assert suspicion.alignment_reason("EURUSD=X", legacy)
    assert suspicion.alignment_reason("EURUSD=X", {})                              # config illisible : règle 1
    assert suspicion.alignment_reason("EURUSD=X", current) is None
    assert suspicion.alignment_reason("^GSPC", legacy) is None
    assert suspicion.alignment_reason("AAPL__alpha_EURUSD=X", legacy) is None     # le benchmark n'est pas la cible
    assert suspicion.alignment_reason(None, legacy) is None


def test_alignment_reasons_lists_the_legacy_fx_runs(tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "snap", "hash", 0, 1, "api")
    for run_id, target, rule in (("fx_old", "EURUSD=X", 1), ("fx_new", "EURUSD=X", 2), ("eq", "^GSPC", 1)):
        trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="snap",
                           config_json=_config(target, rule).model_dump_json(), config_hash="x", git_sha="x", seed=1)
    reasons = trackdb.alignment_reasons(conn, ["fx_old", "fx_new", "eq"])
    assert set(reasons) == {"fx_old"}
    assert {r["run_id"]: r["suspect"] for r in trackdb.list_all_runs(conn)}["fx_old"]
    assert not {r["run_id"]: r["suspect"] for r in trackdb.list_all_runs(conn)}["fx_new"]
    conn.close()
