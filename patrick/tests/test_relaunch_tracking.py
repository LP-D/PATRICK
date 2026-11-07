"""Suivi des relances conseillées (2026-11-07) : quelle suggestion a produit quel job, ce que le duel en a fait, quels modèles ne savent plus prédire, et
l'observation sans effet de l'arrêt anticipé du scan. Tout cela est de la mesure : rien de tout cela ne doit jamais faire échouer un lancement ou un run."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from patrick.features import pool_cache
from patrick.pipeline import champion_duel, early_stop_shadow
from patrick.pipeline.leaderboard import Leaderboard
from patrick.tracking import db, relaunch_stats, retrain_advisor


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "t.db"))
    connection.execute("PRAGMA foreign_keys = OFF")
    yield connection
    connection.close()


def _duel(conn, job_id, decision, run_id="r"):
    return relaunch_stats.record_duel(conn, job_id=job_id, run_id=run_id, target="X", horizon=1, decision={"decision": decision, "criterion": "AUC_dir",
                                                                                                         "challenger_score": 0.52, "champion_score": 0.51})


# -- quelle suggestion a produit quel job, et ce que le duel en a fait -----------------------------------------------

def test_stats_count_only_decided_duels_of_jobs_launched_from_a_suggestion(conn):
    for i, decision in enumerate(["challenger_wins", "champion_wins", "champion_wins", "promoted_first"]):
        relaunch_stats.record_relaunch(conn, f"j{i}", f"parent{i}", "overfit", "batch")
        _duel(conn, f"j{i}", decision)
    _duel(conn, "jamais_conseille", "challenger_wins")                       # un job lancé à la main ne compte pas
    stats = relaunch_stats.suggestion_stats(conn)
    assert stats["by_key"]["overfit"] == {"n": 3, "wins": 1, "win_rate": pytest.approx(1 / 3)}
    assert stats["total"] == {"n": 3, "wins": 1}


def test_the_factor_stays_neutral_until_the_measure_is_solid():
    thin = {"total": {"n": 500, "wins": 250}, "by_key": {"overfit": {"n": 29, "wins": 0, "win_rate": 0.0}}}
    assert relaunch_stats.suggestion_factor(thin, "overfit") == 1.0           # 29 duels < 30 pour cette clé
    few = {"total": {"n": 99, "wins": 50}, "by_key": {"overfit": {"n": 99, "wins": 0, "win_rate": 0.0}}}
    assert relaunch_stats.suggestion_factor(few, "overfit") == 1.0            # 99 duels < 100 au total
    assert relaunch_stats.suggestion_factor(None, "overfit") == 1.0
    assert relaunch_stats.suggestion_factor({"total": {"n": 500, "wins": 250}, "by_key": {}}, "inconnue") == 1.0


def test_the_factor_is_shrunk_and_bounded():
    stats = {"total": {"n": 1000, "wins": 480}, "by_key": {"good": {"n": 100, "wins": 90, "win_rate": 0.9}, "bad": {"n": 100, "wins": 0, "win_rate": 0.0},
                                                            "average": {"n": 100, "wins": 48, "win_rate": 0.48}}}
    assert relaunch_stats.suggestion_factor(stats, "good") == relaunch_stats.FACTOR_MAX
    assert relaunch_stats.suggestion_factor(stats, "bad") == relaunch_stats.FACTOR_MIN
    assert relaunch_stats.suggestion_factor(stats, "average") == pytest.approx(1.0, abs=0.01)


def test_the_advisor_scales_a_score_only_with_enough_duels():
    diag = retrain_advisor.Diagnosis(run_id="r", target="X", horizon=1, auc_test=0.50, f1_test=0.40, auc_holdout=0.50, f1_holdout=0.40)
    plain = {s.key: s.score for s in retrain_advisor.advise(diag, limit=20)}
    assert plain
    key = next(iter(plain))
    stats = {"total": {"n": 1000, "wins": 480}, "by_key": {key: {"n": 100, "wins": 0, "win_rate": 0.0}}}
    scaled = {s.key: s.score for s in retrain_advisor.advise(diag, limit=20, stats=stats)}
    assert scaled[key] == pytest.approx(plain[key] * relaunch_stats.FACTOR_MIN)
    assert all(scaled[k] == plain[k] for k in plain if k != key)


def test_writing_never_raises_when_the_table_is_missing(tmp_path):
    import sqlite3

    bare = sqlite3.connect(str(tmp_path / "bare.db"))
    assert relaunch_stats.record_relaunch(bare, "j", "p", "overfit", "batch") is False
    assert _duel(bare, "j", "champion_wins") is False
    assert relaunch_stats.record_live_failure(bare, "r", "boom") is False
    assert relaunch_stats.suggestion_stats(bare)["total"]["n"] == 0
    assert relaunch_stats.live_failure(bare, "r") is None
    bare.close()


def test_the_duel_note_survives_the_pruning_of_the_challenger(conn):
    conn.execute("INSERT INTO run(run_id, started_at, status, target, horizon, snapshot_id, config_json, config_hash, git_sha, seed, lib_versions, job_id) "
                 "VALUES ('chal', '2026-11-07', 'done', 'X', 3, 'snap', '{}', 'c', 's', 1, '{}', 'job9')")
    st = SimpleNamespace(conn=conn, run_ids={3: "chal"}, config=SimpleNamespace(objective=SimpleNamespace(run_label=lambda: "X")),
                         early_stop_shadow={3: {"stop_fold": 2, "best": 0.49, "champion": 0.54, "n_folds": 4}})
    job_id = champion_duel._job_of(st, 3)
    conn.execute("DELETE FROM run WHERE run_id = 'chal'")                         # le challenger battu est élagué
    champion_duel._note_duel(st, 3, job_id, {"decision": "champion_wins", "criterion": "AUC_dir", "challenger_score": 0.5, "champion_score": 0.55}, 12.0)
    row = conn.execute("SELECT job_id, decision, shadow_stop_fold, shadow_best, shadow_champion, n_folds, duration_s FROM duel_outcome").fetchone()
    assert row == ("job9", "champion_wins", 2, 0.49, 0.54, 4, 12.0)


# -- modèles qui ne savent plus prédire ------------------------------------------------------------------------------

MISSING = "Training pool columns missing from the fresh data: ['DBC_heston_theta', 'XLE'] -- the config may have changed since export."


def test_a_missing_column_failure_counts_days_not_attempts(conn):
    relaunch_stats.record_live_failure(conn, "r1", MISSING)
    relaunch_stats.record_live_failure(conn, "r1", MISSING)                       # l'application relance les prédictions plusieurs fois par jour
    assert conn.execute("SELECT n FROM live_failure WHERE run_id = 'r1'").fetchone()[0] == 1
    for days_ago in (2, 1):
        conn.execute("UPDATE live_failure SET last_at = datetime('now', ?) WHERE run_id = 'r1'", (f"-{days_ago} days",))
        relaunch_stats.record_live_failure(conn, "r1", MISSING)
    assert conn.execute("SELECT n FROM live_failure WHERE run_id = 'r1'").fetchone()[0] == 3


def test_only_repeated_missing_column_failures_raise_the_signal(conn):
    relaunch_stats.record_live_failure(conn, "a", MISSING)
    assert relaunch_stats.live_failure(conn, "a") is None                         # un seul jour : peut-être une panne de réseau
    conn.execute("UPDATE live_failure SET n = 3 WHERE run_id = 'a'")
    failure = relaunch_stats.live_failure(conn, "a")
    assert failure["n"] == 3 and failure["missing"] == ["DBC_heston_theta", "XLE"]
    relaunch_stats.record_live_failure(conn, "b", "HTTP Error 404")
    conn.execute("UPDATE live_failure SET n = 9 WHERE run_id = 'b'")
    assert relaunch_stats.live_failure(conn, "b") is None                         # un autre type d'échec : pas de série perdue
    relaunch_stats.clear_live_failure(conn, "a")
    assert relaunch_stats.live_failure(conn, "a") is None


def test_the_advisor_proposes_a_rebuild_when_input_series_are_gone():
    base = {"run_id": "r", "target": "X", "horizon": 1, "auc_test": 0.56, "f1_test": 0.55, "auc_holdout": 0.55, "f1_holdout": 0.54}
    none = retrain_advisor.advise(retrain_advisor.Diagnosis(**base), limit=20)
    assert "inputs_lost" not in [s.key for s in none]
    lost = retrain_advisor.Diagnosis(**base, live_failure={"reason": "missing_columns", "n": 5, "since": "2026-11-02 08:00:00", "missing": ["DBC_heston_theta"]})
    first = retrain_advisor.advise(lost, limit=20)[0]
    assert first.key == "inputs_lost" and first.score >= 90 and first.patch == {} and first.available and not first.manual
    assert first.facts["days"] == "5" and "DBC_heston_theta" in first.facts["missing"]


def test_the_texts_of_the_new_suggestion_exist_in_both_languages():
    from patrick.webapp import i18n

    for lang in ("fr", "en"):
        t = i18n.translator(lang)
        for part in ("title", "why", "try"):
            assert t(f"adv_inputs_lost_{part}") != f"adv_inputs_lost_{part}"


def test_daily_predictions_note_and_clear_failures(tmp_path):
    from patrick import live_refresh

    db_path = str(tmp_path / "live.db")
    db.connect(db_path).close()
    cand = live_refresh.PredictCandidate(target="X", horizon=1, run_id="r1", trial_id=1, artifact_path="a")

    def failing(run_id, db_path=None):
        raise ValueError(MISSING)

    live_refresh.run_daily_predictions([cand], predict_live_fn=failing, db_path=db_path, track_failures=True)
    conn = db.connect(db_path)
    assert conn.execute("SELECT reason, n FROM live_failure WHERE run_id = 'r1'").fetchone() == ("missing_columns", 1)
    live_refresh.run_daily_predictions([cand], predict_live_fn=lambda run_id, db_path=None: {"y_pred": 1}, db_path=db_path, track_failures=True)
    assert conn.execute("SELECT COUNT(*) FROM live_failure").fetchone()[0] == 0
    conn.close()


def test_the_failure_tracker_never_holds_the_write_lock_between_predictions(tmp_path):
    """Régression : `clear_live_failure` sur un modèle sans note (le cas courant) laissait une transaction d'écriture ouverte sur la connexion
    de suivi ; le worker et le serveur recevaient « database is locked » tant que la boucle des prédictions du jour tournait."""
    import sqlite3

    from patrick import live_refresh

    db_path = str(tmp_path / "lock.db")
    db.connect(db_path).close()
    cands = [live_refresh.PredictCandidate(target="X", horizon=1, run_id=f"r{i}", trial_id=i, artifact_path="a") for i in range(3)]
    locked: list[bool] = []

    def predict(run_id, db_path=None):
        other = sqlite3.connect(db_path, timeout=0.2, isolation_level=None)       # un autre processus (worker, serveur) veut écrire
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
            locked.append(False)
        except sqlite3.OperationalError:
            locked.append(True)
        finally:
            other.close()
        return {"y_pred": 1}

    live_refresh.run_daily_predictions(cands, predict_live_fn=predict, db_path=db_path, track_failures=True)
    assert locked == [False, False, False]


def test_an_injected_prediction_function_never_writes_to_the_database(tmp_path):
    from patrick import live_refresh

    db_path = str(tmp_path / "never.db")
    cand = live_refresh.PredictCandidate(target="X", horizon=1, run_id="r1", trial_id=1, artifact_path="a")
    live_refresh.run_daily_predictions([cand], predict_live_fn=lambda run_id, db_path=None: {}, db_path=db_path)
    import os

    assert not os.path.exists(db_path)


# -- arrêt anticipé : observé, jamais appliqué -------------------------------------------------------------------------

def _stub_state(conn):
    conn.execute("INSERT INTO champion(target, horizon, run_id, trial_id, promoted_at, reason, holdout_f1_dir) VALUES ('X', 1, 'champ', 7, '2026-11-01', 'first', 0.5)")
    for fold in range(3):
        conn.execute("INSERT INTO fold_metric(trial_id, split, fold_index, metric, value) VALUES (7, 'test', ?, 'AUC_dir', 0.56)", (fold,))
    return SimpleNamespace(conn=conn, run_ids={1: "new"}, early_stop_shadow={}, config=SimpleNamespace(objective=SimpleNamespace(run_label=lambda: "X")))


def _board(values_by_fold):
    board = Leaderboard()
    for fold, value in enumerate(values_by_fold):
        board.add(horizon=1, regime="GLOBAL", N=8, sampler="SMOTE", algo="XGBoost", fold=fold, AUC_dir=value)
    return board


def test_a_clearly_trailing_challenger_is_noted_at_the_second_fold(conn, capsys):
    st = _stub_state(conn)
    assert early_stop_shadow.observe(st, 1, 0, criterion="AUC_dir", board=_board([0.50]))["stop_fold"] is None     # un pli ne suffit pas
    note = early_stop_shadow.observe(st, 1, 1, criterion="AUC_dir", board=_board([0.50, 0.51]))
    assert note["stop_fold"] == 2 and note["champion"] == pytest.approx(0.56) and note["best"] == pytest.approx(0.505)
    assert "[EARLY-STOP?]" in capsys.readouterr().out
    later = early_stop_shadow.observe(st, 1, 2, criterion="AUC_dir", board=_board([0.50, 0.51, 0.60]))
    assert later["stop_fold"] == 2                                                # le premier pli de la règle est gardé, même si le candidat remonte


def test_a_challenger_within_the_margin_is_never_noted(conn):
    st = _stub_state(conn)
    early_stop_shadow.observe(st, 1, 0, criterion="AUC_dir", board=_board([0.55]))
    assert early_stop_shadow.observe(st, 1, 1, criterion="AUC_dir", board=_board([0.55, 0.54]))["stop_fold"] is None


def test_nothing_is_observed_without_a_champion(conn):
    st = SimpleNamespace(conn=conn, run_ids={1: "new"}, early_stop_shadow={}, config=SimpleNamespace(objective=SimpleNamespace(run_label=lambda: "X")))
    assert early_stop_shadow.observe(st, 1, 1, criterion="AUC_dir", board=_board([0.4, 0.4])) is None


# -- le cache de variables dit ce qu'il sert vraiment -----------------------------------------------------------------

def test_pool_cache_counts_hits_and_misses(tmp_path, monkeypatch):
    import numpy as np
    import pandas as pd

    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(tmp_path / "fc"))
    monkeypatch.setenv("PATRICK_FEATURE_CACHE", "1")
    pool_cache.take_stats()
    raw = pd.DataFrame({"a": np.arange(5.0)}, index=pd.date_range("2026-01-01", periods=5))
    compute = lambda: pd.DataFrame({"f": np.arange(5.0)}, index=raw.index)
    pool_cache.cached("base", raw, {"k": 1}, compute)
    pool_cache.cached("base", raw, {"k": 1}, compute)
    pool_cache.cached("parametric", raw, {"k": 1}, compute)
    stats = pool_cache.take_stats()
    assert stats["base"]["hits"] == 1 and stats["base"]["misses"] == 1 and stats["parametric"] == {"hits": 0, "misses": 1, "compute_s": stats["parametric"]["compute_s"]}
    assert pool_cache.take_stats() == {}                                          # remis à zéro
    assert "base : 1 lus / 1 calculés" in pool_cache.stats_line(stats) and pool_cache.stats_line({}) == ""
