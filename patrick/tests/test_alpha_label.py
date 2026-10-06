"""Cible alpha, jalon 2b : un run alpha a une étiquette de cible distincte (`MC.PA__alpha_^GSPC`). Conséquence voulue :
champions, registre d'essais, familles DM/BH et rejeu patrimoine se séparent d'eux-mêmes, et un modèle d'alpha (qui prédit
une surperformance, pas la direction du prix) n'est jamais rejoué comme un signal de prix."""
from __future__ import annotations

import pytest
from test_fund_systematic import _model

from patrick.config import target_label as tl
from patrick.config.schema import RunConfig
from patrick.fund import systematic
from patrick.simulate import engine as sim_engine
from patrick.tracking import champions
from patrick.tracking import db as trackdb
from patrick.wealth import signal_replay


def _cfg(symbol="MC.PA", **objective) -> RunConfig:
    return RunConfig.model_validate({
        "objective": {"target_symbol": symbol, "horizons": [5], **objective},
        "universe": {"yf_tickers": ["GOOD1"], "start_date": "2015-01-01"}})


def test_labels_round_trip():
    assert tl.run_label("AAPL") == "AAPL"
    assert tl.run_label("MC.PA", "alpha", "^GSPC") == "MC.PA__alpha_^GSPC"
    assert tl.split_run_label("AAPL") == ("AAPL", "raw", None)
    assert tl.split_run_label("MC.PA__alpha_^GSPC") == ("MC.PA", "alpha", "^GSPC")
    assert tl.is_alpha_label("MC.PA__alpha_^GSPC") and not tl.is_alpha_label("AAPL")


def test_the_config_label_is_the_database_label_and_the_snapshot_key():
    raw, alpha = _cfg(), _cfg(target_kind="alpha", benchmark="^GSPC")
    assert raw.objective.run_label() == "MC.PA" and raw.objective.raw_cache_key() == "raw_MC.PA"
    assert alpha.objective.run_label() == "MC.PA__alpha_^GSPC"
    assert alpha.objective.raw_cache_key() == "raw_MC.PA__alpha_^GSPC"      # `raw_{run.target}` retrouve donc le snapshot


def _alpha_run(conn):
    """Un run alpha terminé avec un essai gagnant et des signaux holdout, à côté d'un run brut du même actif."""
    tid = _model(conn)                                                            # run1 / ^GSPC
    conn.execute("UPDATE run SET target = 'MC.PA__alpha_^GSPC', status = 'done' WHERE run_id = 'run1'")
    conn.execute("UPDATE trial SET is_best = 1, artifact_path = 'x.joblib' WHERE trial_id = ?", (tid,))
    conn.commit()
    return tid


def test_fund_rules_never_offer_an_alpha_model_as_a_price_signal(conn):
    _alpha_run(conn)
    assert systematic.available_models(conn) == []


def test_fund_rules_refuse_an_alpha_trial_even_when_its_id_is_given_directly(conn):
    from patrick.fund import store
    tid = _alpha_run(conn)
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    cfg = {"trial_id": tid, "segment": "holdout", "enter": 0.6, "exit": 0.5,
           "instrument": {"kind": "equity", "symbol": "AAPL"}, "sizing": {"amount": 5000}}
    with pytest.raises(store.FundError, match="alpha"):
        systematic.create_rule(conn, sid, "x", cfg)


def test_patrimoine_replay_never_picks_an_alpha_run_for_a_holding(conn):
    _alpha_run(conn)
    assert signal_replay._winning_trial(conn, "MC.PA") is None


def test_an_alpha_run_never_becomes_the_champion_of_the_raw_target(conn):
    tid = _alpha_run(conn)
    trackdb.create_run(conn, "raw1", target="MC.PA", horizon=5, snapshot_id="snap1", config_json="{}",
                       config_hash="h", git_sha="sha", seed=1)
    conn.execute("UPDATE run SET status = 'done', started_at = datetime('now', '-1 day') WHERE run_id = 'raw1'")
    raw_tid = trackdb.create_trial(conn, "raw1", "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
    conn.execute("UPDATE trial SET is_best = 1, artifact_path = 'raw.joblib' WHERE trial_id = ?", (raw_tid,))
    conn.commit()

    # le run alpha est plus récent : sans étiquette distincte il serait le « champion implicite » de MC.PA
    assert champions.current(conn, "MC.PA", 5)["trial_id"] == raw_tid
    assert champions.current(conn, "MC.PA__alpha_^GSPC", 5)["trial_id"] == tid


def test_the_trial_registry_counts_alpha_trials_in_their_own_family(conn):
    _alpha_run(conn)
    trackdb.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
    from patrick.tracking import stats
    assert stats.count_cumulative_trials(conn, "MC.PA__alpha_^GSPC") >= 1
    assert stats.count_cumulative_trials(conn, "MC.PA") == 0


def test_simulation_refuses_an_alpha_trial_with_an_explicit_message(conn, tmp_path, monkeypatch):
    tid = _alpha_run(conn)
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    with pytest.raises(ValueError, match="alpha"):
        sim_engine.simulate(tid, sim_engine.SimParams(), db_path=str(tmp_path / "patrick.db"))


def test_daily_prediction_never_picks_an_alpha_run(conn, tmp_path):
    """Les classes réalisées d'un signal live se jugent sur le prix brut : pour un modèle d'alpha elles seraient fausses."""
    from patrick import live_refresh
    tid = _alpha_run(conn)
    model = tmp_path / "alpha_model.joblib"
    model.write_bytes(b"x")
    conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (str(model), tid))
    conn.commit()

    assert live_refresh.find_predictable_candidates(conn) == []

    conn.execute("UPDATE run SET target = 'MC.PA' WHERE run_id = 'run1'")        # le même run, étiqueté brut
    conn.commit()
    assert [c.target for c in live_refresh.find_predictable_candidates(conn)] == ["MC.PA"]


def test_predict_live_refuses_an_alpha_run_before_loading_anything(conn, tmp_path):
    from patrick import predict
    tid = _alpha_run(conn)
    model = tmp_path / "alpha_model.joblib"
    model.write_bytes(b"not a real bundle")
    conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (str(model), tid))
    conn.commit()
    db = str(tmp_path / "patrick.db")

    with pytest.raises(ValueError, match="alpha"):
        predict.predict_live("run1", db_path=db)
