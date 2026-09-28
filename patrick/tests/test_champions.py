"""Champion / challenger, database layer (`tracking/champions.py`): one model
"in title" per (target, horizon); a replaced or rejected model keeps only
its descriptive record (`model_archive`), its heavy rows and files are
pruned -- except `trial_registry` (DSR n_trials counts every configuration
ever tested)."""
from __future__ import annotations

import json
import os

import pytest

from patrick.tracking import champions
from patrick.tracking import db as trackdb


def _run(conn, run_id: str, target: str = "^TEST", horizon: int = 5, status: str = "done",
         started: str = "-1 day") -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap1",
                       config_json='{"name": "cfg"}', config_hash="h", git_sha="sha", seed=42)
    with conn:
        conn.execute("UPDATE run SET status = ?, started_at = datetime('now', ?) WHERE run_id = ?",
                     (status, started, run_id))


def _best_trial(conn, tmp_path, run_id: str, algo: str = "XGBoost", with_artifact: bool = True) -> int:
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", 3, "shap")
    path = None
    if with_artifact:
        path = str(tmp_path / f"{run_id}_best_model_h5.joblib")
        with open(path, "wb") as f:
            f.write(b"model")
        with open(path[: -len(".joblib")] + "_meta.json", "w") as f:
            json.dump({"feature_names": ["f_a", "f_b", "f_c"], "best_params": {"max_depth": 4},
                       "N": 3, "algo": algo, "sampler": "SMOTE", "regime": "GLOBAL"}, f)
    trackdb.mark_best_trial(conn, tid, artifact_path=path)
    return tid


def test_no_champion_without_any_run(conn):
    assert champions.current(conn, "^TEST", 5) is None


def test_implicit_incumbent_is_the_latest_done_run_with_an_exported_model(conn, tmp_path):
    _run(conn, "old", started="-3 days")
    old_tid = _best_trial(conn, tmp_path, "old")
    _run(conn, "recent", started="-2 days")
    recent_tid = _best_trial(conn, tmp_path, "recent")
    _run(conn, "failed_newer", status="failed", started="-1 day")
    _best_trial(conn, tmp_path, "failed_newer")
    _run(conn, "no_model_newest", started="-1 hours")
    _best_trial(conn, tmp_path, "no_model_newest", with_artifact=False)
    _run(conn, "other_horizon", horizon=10, started="-1 hours")
    _best_trial(conn, tmp_path, "other_horizon")

    cur = champions.current(conn, "^TEST", 5)
    assert (cur["run_id"], cur["trial_id"], cur["implicit"]) == ("recent", recent_tid, True)
    cur = champions.current(conn, "^TEST", 5, exclude_run_ids=["recent"])
    assert (cur["run_id"], cur["trial_id"]) == ("old", old_tid)


def test_an_explicit_champion_overrides_the_implicit_incumbent(conn, tmp_path):
    _run(conn, "old", started="-3 days")
    old_tid = _best_trial(conn, tmp_path, "old")
    _run(conn, "recent", started="-2 days")
    _best_trial(conn, tmp_path, "recent")

    champions.promote(conn, "^TEST", 5, "old", old_tid, reason="won_duel", holdout_f1_dir=0.61)

    cur = champions.current(conn, "^TEST", 5)
    assert (cur["run_id"], cur["trial_id"], cur["implicit"]) == ("old", old_tid, False)
    assert cur["reason"] == "won_duel"
    assert cur["holdout_f1_dir"] == pytest.approx(0.61)


def test_archive_keeps_the_models_description_metrics_and_live_record(conn, tmp_path):
    _run(conn, "r1")
    tid = _best_trial(conn, tmp_path, "r1")
    trackdb.add_fold_metrics(conn, tid, 0, "test", {"F1_dir": 0.50, "MCC_4cls": 0.10})
    trackdb.add_fold_metrics(conn, tid, 1, "test", {"F1_dir": 0.60, "MCC_4cls": 0.20})
    trackdb.add_fold_metrics(conn, tid, 0, "holdout", {"F1_dir": 0.57})
    # live: UP predicted and up realized (hit), DOWN predicted and up realized (miss), one pending
    trackdb.add_predictions(conn, tid, fold_index=0, split="live", ts=["2026-01-02", "2026-01-05", "2026-01-06"],
                            y_true=[1.0, 1.0, None], y_pred=[3, 0, 2])
    duel = {"winner": "challenger", "champion_f1_dir": 0.55, "challenger_f1_dir": 0.58}

    archive_id = champions.archive(conn, "r1", role="replaced_champion", duel=duel)

    row = conn.execute("SELECT * FROM model_archive WHERE archive_id = ?", (archive_id,)).fetchone()
    rec = dict(zip([d[0] for d in conn.execute("SELECT * FROM model_archive").description], row))
    assert (rec["target"], rec["horizon"], rec["run_id"], rec["trial_id"]) == ("^TEST", 5, "r1", tid)
    assert rec["role"] == "replaced_champion"
    assert (rec["algo"], rec["sampler"], rec["regime"], rec["n_features"]) == ("XGBoost", "SMOTE", "GLOBAL", 3)
    assert json.loads(rec["feature_names_json"]) == ["f_a", "f_b", "f_c"]
    assert json.loads(rec["params_json"]) == {"max_depth": 4}
    assert json.loads(rec["wf_metrics_json"]) == pytest.approx({"F1_dir": 0.55, "MCC_4cls": 0.15})
    assert json.loads(rec["holdout_metrics_json"]) == pytest.approx({"F1_dir": 0.57})
    assert json.loads(rec["duel_json"]) == duel
    assert json.loads(rec["live_json"]) == {"n_predictions": 3, "n_resolved": 2, "hit_rate": 0.5}
    assert rec["config_json"] == '{"name": "cfg"}'
    assert rec["pruned"] == 0


def test_prune_removes_rows_and_model_files_but_keeps_the_trial_registry(conn, tmp_path):
    _run(conn, "loser")
    tid = _best_trial(conn, tmp_path, "loser")
    trackdb.add_fold_metrics(conn, tid, 0, "test", {"F1_dir": 0.5})
    trackdb.add_predictions(conn, tid, fold_index=0, split="test", ts=["2026-01-02"], y_true=[1], y_pred=[2])
    model_path = conn.execute("SELECT artifact_path FROM trial WHERE trial_id = ?", (tid,)).fetchone()[0]
    registry_before = conn.execute("SELECT COUNT(*) FROM trial_registry WHERE run_id = 'loser'").fetchone()[0]
    champions.archive(conn, "loser", role="rejected_challenger")

    counts = champions.prune_run(conn, "loser")

    assert counts["run"] == 1 and counts["trial"] == 1 and counts["prediction"] == 1
    for table, key in (("run", "run_id = 'loser'"), ("trial", f"trial_id = {tid}"),
                       ("prediction", f"trial_id = {tid}"), ("fold_metric", f"trial_id = {tid}")):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {key}").fetchone()[0] == 0
    assert not os.path.exists(model_path)
    assert not os.path.exists(model_path[: -len(".joblib")] + "_meta.json")
    assert registry_before == 1
    assert conn.execute("SELECT COUNT(*) FROM trial_registry WHERE run_id = 'loser'").fetchone()[0] == 1
    assert conn.execute("SELECT pruned FROM model_archive WHERE run_id = 'loser'").fetchone()[0] == 1


def test_initialization_keeps_one_model_per_pair_and_supersedes_the_others(conn, tmp_path):
    """`patrick champions init`: existing runs are not dueled retroactively
    -- the model in title is the one the app already uses (latest), or an
    explicit champion if there is one; the other exported models of the pair
    are superseded (archived, then pruned on --apply)."""
    for run_id, started in (("a_old", "-3 days"), ("a_mid", "-2 days"), ("a_new", "-1 day")):
        _run(conn, run_id, horizon=5, started=started)
        _best_trial(conn, tmp_path, run_id)
    _run(conn, "b_champ", horizon=10, started="-3 days")
    b_tid = _best_trial(conn, tmp_path, "b_champ")
    champions.promote(conn, "^TEST", 10, "b_champ", b_tid, reason="won_duel")
    _run(conn, "b_newer", horizon=10, started="-1 day")
    _best_trial(conn, tmp_path, "b_newer")

    plan = {(p["target"], p["horizon"]): p for p in champions.plan_initialization(conn)}

    assert plan[("^TEST", 5)]["keep"] == "a_new" and not plan[("^TEST", 5)]["explicit"]
    assert sorted(plan[("^TEST", 5)]["supersede"]) == ["a_mid", "a_old"]
    assert plan[("^TEST", 10)]["keep"] == "b_champ" and plan[("^TEST", 10)]["explicit"]
    assert plan[("^TEST", 10)]["supersede"] == ["b_newer"]

    summary = champions.apply_initialization(conn, list(plan.values()))

    assert summary == {"promoted": 1, "superseded": 3}
    assert champions.current(conn, "^TEST", 5)["reason"] == "initial_latest"
    assert champions.current(conn, "^TEST", 10)["reason"] == "won_duel"
    assert sorted((a["run_id"], a["role"]) for a in champions.list_archive(conn)) == [
        ("a_mid", "superseded"), ("a_old", "superseded"), ("b_newer", "superseded")]
    remaining = {r[0] for r in conn.execute("SELECT run_id FROM run")}
    assert remaining == {"a_new", "b_champ"}


def test_the_champion_in_title_is_never_pruned(conn, tmp_path):
    _run(conn, "champ")
    tid = _best_trial(conn, tmp_path, "champ")
    champions.promote(conn, "^TEST", 5, "champ", tid, reason="first")
    with pytest.raises(ValueError, match="champion"):
        champions.prune_run(conn, "champ")
    assert conn.execute("SELECT COUNT(*) FROM run WHERE run_id = 'champ'").fetchone()[0] == 1
