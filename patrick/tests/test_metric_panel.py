"""Panneau de métriques d'un modèle et règle du duel (ADR 0023, `validation/metric_panel.py`), rattrapage du panneau pour les modèles
évalués avant lui (`tracking/metric_backfill.py`), et panneau dans les lignes des listes (`tracking/db.py::enrich_runs`)."""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import matthews_corrcoef

from patrick.tracking import db as trackdb
from patrick.tracking import metric_backfill
from patrick.validation import direction, metric_panel

# --------------------------------------------------------------------------------------------------------------------- règle du duel


def _m(auc=None, brier=None, mcc=None, acc=None, f1=None) -> dict:
    out = {"AUC_dir": auc, "Brier_up": brier, "MCC_4cls": mcc, "Acc_dir_p": acc, "F1_dir": f1}
    return {k: v for k, v in out.items() if v is not None}


def test_the_panel_is_always_the_same_four_measures_in_the_same_order():
    assert metric_panel.PANEL_KEYS == ("AUC_dir", "Brier_up", "MCC_4cls", "Acc_dir_p")
    assert metric_panel.panel({"AUC_dir": 0.55, "F1_dir": 0.6, "Brier_up": float("nan")}) == {
        "AUC_dir": 0.55, "Brier_up": None, "MCC_4cls": None, "Acc_dir_p": None}


def test_a_better_auc_with_a_brier_no_worse_wins():
    v = metric_panel.duel_verdict(_m(0.56, 0.246, 0.02), _m(0.54, 0.247, 0.05))
    assert (v["winner"], v["criterion"], v["reason"]) == ("challenger", "AUC_dir+Brier_up", "better")
    assert (v["challenger_score"], v["champion_score"]) == (0.56, 0.54)


def test_a_better_auc_with_clearly_worse_probabilities_loses():
    v = metric_panel.duel_verdict(_m(0.56, 0.247 + metric_panel.BRIER_TOLERANCE + 0.0005), _m(0.54, 0.247))
    assert (v["winner"], v["reason"]) == ("champion", "brier_worse")


def test_the_brier_tolerance_lets_a_slightly_worse_brier_through():
    v = metric_panel.duel_verdict(_m(0.56, 0.247 + metric_panel.BRIER_TOLERANCE), _m(0.54, 0.247))
    assert v["winner"] == "challenger"


@pytest.mark.parametrize("auc_c", [0.54, 0.53])
def test_an_auc_tie_or_worse_keeps_the_champion_whatever_the_brier_and_the_f1(auc_c):
    v = metric_panel.duel_verdict(_m(auc_c, 0.20, f1=0.70), _m(0.54, 0.26, f1=0.40))
    assert (v["winner"], v["reason"]) == ("champion", "auc_not_better")


def test_without_brier_on_a_side_the_auc_alone_decides():
    v = metric_panel.duel_verdict(_m(0.56), _m(0.54, 0.20))
    assert (v["winner"], v["criterion"]) == ("challenger", "AUC_dir")


def test_without_auc_on_a_side_the_mcc_decides_and_never_the_f1():
    v = metric_panel.duel_verdict(_m(mcc=0.03, f1=0.40), _m(0.60, 0.24, mcc=0.05, f1=0.70))
    assert (v["winner"], v["criterion"], v["reason"]) == ("champion", "MCC_4cls", "mcc_not_better")
    assert metric_panel.duel_verdict(_m(f1=0.70), _m(f1=0.40)) is None        # le F1 seul ne départage plus


def test_rank_key_orders_by_auc_then_brier_and_puts_models_without_auc_last():
    models = [_m(0.55, 0.25), _m(0.57, 0.26), None, _m(0.57, 0.24), _m(brier=0.20)]
    ranked = sorted(models, key=metric_panel.rank_key)
    assert ranked[:3] == [_m(0.57, 0.24), _m(0.57, 0.26), _m(0.55, 0.25)]


def test_best_of_takes_the_lowest_brier_and_the_highest_of_the_others():
    assert metric_panel.best_of("Brier_up", [0.25, None, 0.24]) == 0.24
    assert metric_panel.best_of("AUC_dir", [0.51, 0.56, None]) == 0.56
    assert metric_panel.best_of("MCC_4cls", [None]) is None


def test_formatting_of_the_panel():
    assert metric_panel.cells({"AUC_dir": 0.5612, "Brier_up": 0.24, "Acc_dir_p": 0.5234}) == ["0.561", "0.240", "—", "52.3 %"]
    assert metric_panel.heads({"pm_AUC_dir": "AUC dir."})[0] == "AUC dir."


# ---------------------------------------------------------------------------------------------------------------------- rattrapage


def _trial_with_predictions(conn, run_id: str = "old_run", with_auc: bool = False) -> tuple[int, dict]:
    """Un run d'avant l'ADR 0013 : F1 / MCC / Brier par pli, pas d'AUC_dir ni d'Acc_dir_p, mais ses prédictions en base."""
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, run_id, target="^TEST", horizon=5, snapshot_id="snap1", config_json="{}", config_hash="h", git_sha="sha", seed=1)
    with conn:
        conn.execute("UPDATE run SET status = 'done' WHERE run_id = ?", (run_id,))
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 6, "shap")
    trackdb.mark_best_trial(conn, tid, artifact_path="x.joblib")
    rng = np.random.default_rng(3)
    expected: dict = {}
    for split, fold, start in (("test", 1, "2020-01-01"), ("test", 2, "2021-01-01"), ("holdout", 0, "2023-01-01")):
        n = 150
        ts = [str(d.date()) for d in pd.bdate_range(start, periods=n)]
        y_class = rng.integers(0, 4, n)
        p_up = np.clip(0.5 + 0.15 * (y_class >= 2) - 0.07 + rng.normal(0, 0.15, n), 0.01, 0.99)
        y_pred = np.where(p_up > 0.5, 2, 1)
        trackdb.add_predictions(conn, tid, fold, split, ts, y_class.tolist(), y_pred.tolist(), p_up=p_up.tolist())
        y_up = (y_class >= 2).astype(float)
        exp = {**direction.direction_metrics(y_up, p_up), "Brier_up": float(np.mean((p_up - y_up) ** 2)),
               "MCC_4cls": round(float(matthews_corrcoef(y_class, y_pred)), 4)}
        expected[(split, fold)] = exp
        stored = {"F1_dir": 0.51, "MCC_4cls": 0.9}               # MCC volontairement faux : une mesure présente n'est jamais réécrite
        if with_auc:
            stored.update(exp)
        trackdb.add_fold_metrics(conn, tid, fold, split, stored)
    trackdb.add_predictions(conn, tid, 0, "live", ["2026-11-02"], [1.0], [3], p_up=[0.6])   # classe binaire en réel : ignorée
    return tid, expected


def _metrics(conn, tid: int) -> dict:
    return {(s, f, m): v for s, f, m, v in conn.execute(
        "SELECT split, fold_index, metric, value FROM fold_metric WHERE trial_id = ?", (tid,))}


def test_backfill_recomputes_the_missing_panel_measures_from_the_stored_predictions(conn):
    tid, expected = _trial_with_predictions(conn)

    report = metric_backfill.backfill(conn)

    got = _metrics(conn, tid)
    assert report["n_touched"] == 1 and report["n_rows"] > 0
    for (split, fold), exp in expected.items():
        assert got[(split, fold, "AUC_dir")] == pytest.approx(exp["AUC_dir"])
        assert got[(split, fold, "Acc_dir_p")] == pytest.approx(exp["Acc_dir_p"])
        assert got[(split, fold, "F1_dir_p")] == pytest.approx(exp["F1_dir_p"])
        assert got[(split, fold, "Brier_up")] == pytest.approx(exp["Brier_up"])
        assert got[(split, fold, "MCC_4cls")] == 0.9                     # déjà là : intact
        assert got[(split, fold, "F1_dir")] == 0.51
    assert not [k for k in got if k[0] == "live"]


def test_backfill_is_idempotent_and_skips_complete_trials(conn):
    tid, _ = _trial_with_predictions(conn)
    metric_backfill.backfill(conn)
    before = _metrics(conn, tid)

    again = metric_backfill.backfill(conn)

    assert again["n_rows"] == 0 and _metrics(conn, tid) == before


def test_backfill_leaves_a_recent_trial_alone(conn):
    tid, _ = _trial_with_predictions(conn, with_auc=True)
    before = _metrics(conn, tid)

    report = metric_backfill.backfill(conn)

    assert report["n_trials"] == 0 and _metrics(conn, tid) == before


def test_the_prediction_query_reads_by_trial_not_by_path_id_index(conn):
    """Régression 2026-11-20 : `path_id = -1` seul faisait choisir `idx_pred_path` (balayage de toute la table, 23 min par essai sur 76 Go),
    transaction d'écriture ouverte : la base restait verrouillée et les workers mouraient. La requête doit passer par la clé primaire."""
    for run_id in ("old_run_a", "old_run_b", "old_run_c"):
        _trial_with_predictions(conn, run_id=run_id)           # sans ANALYZE : l'ancienne requête choisit alors `idx_pred_path`, comme en production
    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + metric_backfill.PREDICTIONS_SQL.format(s_ph="?,?"),
                                                 [1, "test", "holdout"]))
    assert "idx_pred_path" not in plan and "trial_id=?" in plan, plan


def test_backfill_releases_the_write_lock_between_batches(tmp_path):
    """Un worker qui écrit (30 s de `busy_timeout`) ne doit jamais attendre un rattrapage : le verrou est rendu à chaque lot."""
    path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(path)
    for run_id in ("old_run_a", "old_run_b", "old_run_c"):
        _trial_with_predictions(conn, run_id=run_id)
    locked_at: list[int] = []

    def other_writer_gets_in(done: int, total: int) -> None:
        other = trackdb.connect(path)
        try:
            other.execute("PRAGMA busy_timeout = 0")
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
        except Exception:                                       # noqa: BLE001 -- sqlite3.OperationalError : base verrouillée
            locked_at.append(done)
        finally:
            other.close()

    report = metric_backfill.backfill(conn, commit_every=1, progress=other_writer_gets_in)

    assert report["n_touched"] == 3 and not locked_at, f"base verrouillée après {locked_at} essai(s)"
    assert inspect.signature(metric_backfill.backfill).parameters["commit_every"].default <= 50     # le lot par défaut reste court


def test_the_backfilled_panel_reaches_the_run_lists(conn):
    _trial_with_predictions(conn)
    assert trackdb.list_all_runs(conn, with_balance=False)[0]["panel"]["AUC_dir"] is None

    metric_backfill.backfill(conn)

    row = trackdb.list_all_runs(conn, with_balance=False)[0]
    assert row["panel"]["AUC_dir"] is not None and row["holdout_panel"]["AUC_dir"] is not None
    assert row["panel"]["MCC_4cls"] == pytest.approx(0.9)
