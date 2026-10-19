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
from patrick.tracking import stats as trackstats

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


FULL = ["technical", "interactions", "spike", "vol_models", "macro"]
LIGHT = ["technical", "macro"]


# Both orders: whichever side wins on the holdout, the table must end up describing the model in title.
@pytest.mark.parametrize("first_families, second_families", [(FULL, LIGHT), (LIGHT, FULL)], ids=["full-then-light", "light-then-full"])
def test_second_run_duels_the_first_on_the_same_holdout(tmp_path, monkeypatch, first_families, second_families):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    store = DataStore(root=str(tmp_path / "store"))
    store.save(f"raw_{TARGET}", _raw(), meta={"pit_version": f"{PIT_VERSION}:publication_lag"})

    first = run_pipeline(_config(tmp_path, "first", first_families),
                         store=store, db_path=db_path)
    assert first["champions"][5]["decision"] == "promoted_first"
    conn = trackdb.connect(db_path)
    first_run = champions.current(conn, TARGET, 5)["run_id"]
    drift_after_first = trackdb.get_drift_references(conn, TARGET, 5)
    conn.close()
    assert drift_after_first

    second = run_pipeline(_config(tmp_path, "second", second_families), store=store, db_path=db_path)

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

        # The drift reference (one per symbol/horizon, replaced by every export) belongs to the model that
        # stays in title, whichever run exported last.
        drift_now = trackdb.get_drift_references(conn, TARGET, 5)
        if loser == first_run:  # the challenger took the title: its export's reference stands
            assert {row[0] for row in drift_now} >= set(
                champions.model_meta(champions.best_trial(conn, in_title["run_id"])["artifact_path"])["feature_names"])
        else:  # the challenger was rejected: its export left no trace
            assert drift_now == drift_after_first
    finally:
        conn.close()


def test_every_horizon_of_a_launch_keeps_its_own_holdout(tmp_path, monkeypatch):
    """Avant, seul le gagnant global avait son holdout enregistré : sur un lancement de N horizons, N-1 runs n'en avaient aucun, alors
    que le duel des champions évaluait chaque horizon."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    store = DataStore(root=str(tmp_path / "store"))
    store.save(f"raw_{TARGET}", _raw(), meta={"pit_version": f"{PIT_VERSION}:publication_lag"})
    config = _config(tmp_path, "multi", LIGHT).model_copy(deep=True)
    config.objective.horizons = [3, 5]

    result = run_pipeline(config, store=store, db_path=db_path)

    assert set(result["champions"]) == {3, 5}
    conn = trackdb.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT run.horizon, COUNT(DISTINCT fold_metric.metric), "
            "       (SELECT COUNT(*) FROM prediction p WHERE p.trial_id = trial.trial_id AND p.split = 'holdout') "
            "FROM run JOIN trial ON trial.run_id = run.run_id AND trial.is_best = 1 "
            "LEFT JOIN fold_metric ON fold_metric.trial_id = trial.trial_id AND fold_metric.split = 'holdout' "
            "GROUP BY run.horizon, trial.trial_id").fetchall()
        by_horizon = {h: (n_metrics, n_pred) for h, n_metrics, n_pred in rows}
        assert set(by_horizon) == {3, 5}
        assert all(n_metrics > 0 and n_pred > 0 for n_metrics, n_pred in by_horizon.values()), by_horizon
        # une seule écriture par essai : pas de doublon de métriques
        dup = conn.execute("SELECT trial_id, metric, COUNT(*) FROM fold_metric WHERE split = 'holdout' "
                           "GROUP BY trial_id, metric HAVING COUNT(*) > 1").fetchall()
        assert dup == []
    finally:
        conn.close()


def _reads_by_purpose(conn, run_id=None) -> dict[str, int]:
    where, params = ("WHERE run_id = ?", (run_id,)) if run_id else ("", ())
    return dict(conn.execute(f"SELECT purpose, COUNT(*) FROM holdout_access {where} GROUP BY purpose", params))


def test_every_holdout_read_of_a_launch_is_registered_with_its_purpose_and_run(tmp_path, monkeypatch):
    """Registre d'accès (migration 0038). Un lancement à deux horizons, premier run (aucun champion à affronter) :
    - une évaluation finale, pour le gagnant global seulement ;
    - le diagnostic note TOUS les essais de la grille : une lecture par essai ;
    - le duel lit le holdout du challenger de l'AUTRE horizon (celui du gagnant global est réutilisé, pas relu)."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    store = DataStore(root=str(tmp_path / "store"))
    store.save(f"raw_{TARGET}", _raw(), meta={"pit_version": f"{PIT_VERSION}:publication_lag"})
    config = _config(tmp_path, "reads", LIGHT).model_copy(deep=True)
    config.objective.horizons = [3, 5]

    run_pipeline(config, store=store, db_path=db_path)

    conn = trackdb.connect(db_path)
    try:
        n_trials = conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0]
        assert _reads_by_purpose(conn) == {"final_eval": 1, "diagnostic": n_trials, "champion_duel_challenger": 1}
        # Chaque lecture dit quel run elle sert et quelle fenêtre elle a lue.
        rows = conn.execute("SELECT run_id, horizon, holdout_start, holdout_end, n_rows FROM holdout_access").fetchall()
        run_horizon = dict(conn.execute("SELECT run_id, horizon FROM run").fetchall())
        assert all(run_id in run_horizon and run_horizon[run_id] == horizon and start < end and n > 0
                   for run_id, horizon, start, end, n in rows)
    finally:
        conn.close()


def test_the_duel_registers_its_reads_of_the_champion_on_the_same_holdout(tmp_path, monkeypatch):
    """Le duel SÉLECTIONNE sur le holdout : la relecture du champion par chaque challenger doit être comptée, par
    cible et horizon, et rattachée au run du challenger."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    store = DataStore(root=str(tmp_path / "store"))
    store.save(f"raw_{TARGET}", _raw(), meta={"pit_version": f"{PIT_VERSION}:publication_lag"})

    run_pipeline(_config(tmp_path, "first", FULL), store=store, db_path=db_path)
    conn = trackdb.connect(db_path)
    assert trackstats.holdout_reads(conn, TARGET, 5)["by_purpose"].get("champion_duel_champion", 0) == 0
    conn.close()

    run_pipeline(_config(tmp_path, "second", LIGHT), store=store, db_path=db_path)
    conn = trackdb.connect(db_path)
    try:
        reads = trackstats.holdout_reads(conn, TARGET, 5)
        assert reads["by_purpose"]["champion_duel_champion"] == 1
        assert reads["selecting"] == 1           # le challenger, lui, a réutilisé sa lecture finale
        assert reads["n_runs"] == 2
        # La lecture du champion est portée par le run du challenger (le perdant peut être élagué ensuite : la ligne reste).
        reader = conn.execute("SELECT run_id FROM holdout_access WHERE purpose = 'champion_duel_champion'").fetchone()[0]
        assert reader.startswith("second_h5_")
    finally:
        conn.close()
