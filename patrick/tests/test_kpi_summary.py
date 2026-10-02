"""KPI summary of a finished launch (`tracking/kpi_summary.py`): per
algorithm, per number of features and a ranking of the tested configurations,
to decide which setup to launch next.

The comparison window is the set of folds EVERY candidate of a horizon went
through: in staged screening only the first fold (non-finalists stop there),
in exhaustive mode all folds -- never a mix of windows. Tuned trials (Optuna
re-evaluations) and other model categories are not part of the grid."""
from __future__ import annotations

import pytest

from patrick.tracking import db as trackdb
from patrick.tracking import kpi_summary
from patrick.tracking.holdout_diagnostic import write_holdout_diagnostic

JOB = "job-1"


def _run(conn, run_id: str, horizon: int, job_id: str | None = JOB, target: str = "^TEST") -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap1",
                       config_json="{}", config_hash="h", git_sha="sha", seed=42, job_id=job_id)


def _candidate(conn, run_id: str, algo: str, n: int, folds: dict[int, tuple[float, float]],
               sampler: str = "SMOTE", params_json: str = "{}", category: str = "global") -> int:
    """`folds`: fold_index -> (F1_dir, Acc_dir) on the test split."""
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, sampler, n, "shap",
                               params_json=params_json, category=category)
    for fold, (f1, acc) in folds.items():
        trackdb.add_fold_metrics(conn, tid, fold, "test", {"F1_dir": f1, "Acc_dir": acc,
                                                             "MCC_4cls": f1 / 10, "BalAcc_4cls": f1 / 2})
    return tid


@pytest.fixture
def staged(conn):
    """Two horizons of one launch, 2 algos x 2 N. Staged screening: every
    candidate has fold 1 only, the finalist of each horizon also folds 2..."""
    _run(conn, "r_h1", 1)
    _run(conn, "r_h5", 5)
    # horizon 1: fold-1 (F1, Acc) per candidate; finalist A/6 continues on folds 2-3
    _candidate(conn, "r_h1", "A", 5, {1: (0.50, 0.55)})
    a6 = _candidate(conn, "r_h1", "A", 6, {1: (0.60, 0.65), 2: (0.70, 0.75), 3: (0.50, 0.55)})
    _candidate(conn, "r_h1", "B", 5, {1: (0.40, 0.45)})
    _candidate(conn, "r_h1", "B", 6, {1: (0.30, 0.35)})
    # horizon 5: finalist B/5 continues on fold 2
    _candidate(conn, "r_h5", "A", 5, {1: (0.58, 0.60)})
    _candidate(conn, "r_h5", "A", 6, {1: (0.52, 0.50)})
    b5 = _candidate(conn, "r_h5", "B", 5, {1: (0.62, 0.66), 2: (0.50, 0.54)})
    _candidate(conn, "r_h5", "B", 6, {1: (0.44, 0.40)})
    # things that must NOT count: a tuned re-evaluation and another model category
    _candidate(conn, "r_h1", "A", 6, {1: (0.99, 0.99)}, params_json='{"depth": 4}')
    _candidate(conn, "r_h1", "A", 6, {1: (0.99, 0.99)}, category="stacking")
    # final model of horizon 1 (exported) with its holdout score
    trackdb.mark_best_trial(conn, a6, artifact_path="x.joblib")
    trackdb.add_fold_metrics(conn, a6, 0, "holdout", {"F1_dir": 0.45, "Acc_dir": 0.50})
    # holdout diagnostic (read-only, never used to choose): the scan version of each horizon's best config
    write_holdout_diagnostic(conn, a6, {"F1_dir": 0.41, "Acc_dir": 0.52})
    write_holdout_diagnostic(conn, b5, {"F1_dir": 0.38, "Acc_dir": 0.47})
    return {"a6": a6, "b5": b5}


def _by(rows, key):
    return {r[key]: r for r in rows}


def test_siblings_are_the_runs_of_the_same_launch(conn):
    _run(conn, "r_h1", 1)
    _run(conn, "r_h5", 5)
    _run(conn, "other", 1, job_id="job-2")
    _run(conn, "cli_run", 1, job_id=None)
    assert sorted(kpi_summary.sibling_run_ids(conn, "r_h1")) == ["r_h1", "r_h5"]
    assert kpi_summary.sibling_run_ids(conn, "cli_run") == ["cli_run"]
    assert kpi_summary.sibling_run_ids(conn, "missing") == []


def test_staged_screening_compares_every_candidate_on_the_first_fold_only(conn, staged):
    s = kpi_summary.summarize(conn, ["r_h1", "r_h5"])

    assert s["horizons"] == [1, 5] and s["target"] == "^TEST"
    assert s["n_candidates"] == 8
    assert s["window"]["mode"] == "first_fold"
    assert s["window"]["folds_by_horizon"] == {1: [1], 5: [1]}


def test_kpis_per_algorithm(conn, staged):
    by_algo = _by(kpi_summary.summarize(conn, ["r_h1", "r_h5"])["by_algo"], "algo")

    assert [r["algo"] for r in kpi_summary.summarize(conn, ["r_h1", "r_h5"])["by_algo"]] == ["A", "B"]
    assert by_algo["A"]["rank"] == 1 and by_algo["B"]["rank"] == 2
    assert by_algo["A"]["n"] == 4
    assert by_algo["A"]["F1_dir"] == pytest.approx((0.50 + 0.60 + 0.58 + 0.52) / 4)
    assert by_algo["A"]["Acc_dir"] == pytest.approx((0.55 + 0.65 + 0.60 + 0.50) / 4)
    assert by_algo["A"]["MCC_4cls"] == pytest.approx((0.50 + 0.60 + 0.58 + 0.52) / 4 / 10)
    assert by_algo["B"]["F1_dir"] == pytest.approx((0.40 + 0.30 + 0.62 + 0.44) / 4)


def test_kpis_per_number_of_features_are_ranked(conn, staged):
    rows = kpi_summary.summarize(conn, ["r_h1", "r_h5"])["by_n_features"]
    by_n = _by(rows, "n_features")

    assert [r["n_features"] for r in rows] == [5, 6]          # ranked by F1_dir, best first
    assert [r["rank"] for r in rows] == [1, 2]
    assert by_n[5]["F1_dir"] == pytest.approx((0.50 + 0.40 + 0.58 + 0.62) / 4)
    assert by_n[6]["F1_dir"] == pytest.approx((0.60 + 0.30 + 0.52 + 0.44) / 4)
    assert by_n[5]["n"] == 4


def test_ranking_of_configurations_averages_over_horizons(conn, staged):
    ranking = kpi_summary.summarize(conn, ["r_h1", "r_h5"])["ranking"]

    assert [(r["algo"], r["n_features"]) for r in ranking] == [("A", 6), ("A", 5), ("B", 5), ("B", 6)]
    assert [r["rank"] for r in ranking] == [1, 2, 3, 4]
    assert ranking[0]["F1_dir"] == pytest.approx((0.60 + 0.52) / 2)
    assert ranking[0]["n_horizons"] == 2
    assert ranking[0]["sampler"] == "SMOTE"


def test_per_horizon_best_config_over_the_complete_period_and_final_model(conn, staged):
    rows = _by(kpi_summary.summarize(conn, ["r_h1", "r_h5"])["by_horizon"], "horizon")

    h1, h5 = rows[1], rows[5]
    assert (h1["algo"], h1["n_features"]) == ("A", 6)
    assert h1["window_F1_dir"] == pytest.approx(0.60)
    assert h1["full_F1_dir"] == pytest.approx((0.60 + 0.70 + 0.50) / 3) and h1["full_folds"] == 3
    assert h1["full_Acc_dir"] == pytest.approx((0.65 + 0.75 + 0.55) / 3)
    assert (h1["final_algo"], h1["final_n_features"]) == ("A", 6)
    assert h1["holdout_F1_dir"] == pytest.approx(0.45) and h1["holdout_Acc_dir"] == pytest.approx(0.50)

    assert (h5["algo"], h5["n_features"]) == ("B", 5)
    assert h5["window_F1_dir"] == pytest.approx(0.62)
    assert h5["full_F1_dir"] == pytest.approx((0.62 + 0.50) / 2) and h5["full_folds"] == 2
    assert h5["final_algo"] is None and h5["holdout_F1_dir"] is None   # no exported model yet


def test_every_horizon_reports_the_holdout_of_its_best_config_before_optuna(conn, staged):
    rows = _by(kpi_summary.summarize(conn, ["r_h1", "r_h5"])["by_horizon"], "horizon")

    # the diagnostic exists for every horizon, even where no exported model was evaluated on the holdout
    assert rows[1]["diag_F1_dir"] == pytest.approx(0.41) and rows[1]["diag_Acc_dir"] == pytest.approx(0.52)
    assert rows[5]["diag_F1_dir"] == pytest.approx(0.38) and rows[5]["diag_Acc_dir"] == pytest.approx(0.47)
    assert rows[5]["holdout_F1_dir"] is None


def test_staged_note_warns_that_the_common_window_score_is_optimistic(conn, staged):
    note = kpi_summary.summarize(conn, ["r_h1", "r_h5"])["window"]["note"]
    assert "optimiste" in note and "toute sa période" in note


def test_exhaustive_mode_compares_candidates_on_all_folds(conn):
    _run(conn, "r_h1", 1)
    _candidate(conn, "r_h1", "A", 5, {1: (0.50, 0.50), 2: (0.70, 0.70)})
    _candidate(conn, "r_h1", "B", 5, {1: (0.40, 0.40), 2: (0.60, 0.60)})

    s = kpi_summary.summarize(conn, ["r_h1"])

    assert s["window"]["mode"] == "all_folds" and s["window"]["folds_by_horizon"] == {1: [1, 2]}
    assert _by(s["by_algo"], "algo")["A"]["F1_dir"] == pytest.approx(0.60)
    assert _by(s["by_algo"], "algo")["B"]["F1_dir"] == pytest.approx(0.50)


def test_no_grid_gives_an_empty_summary_instead_of_failing(conn):
    _run(conn, "r_h1", 1)
    s = kpi_summary.summarize(conn, ["r_h1"])
    assert s["n_candidates"] == 0 and s["by_algo"] == [] and s["ranking"] == [] and s["by_horizon"] == []
    assert kpi_summary.summarize(conn, [])["n_candidates"] == 0
    assert "Aucun" in kpi_summary.format_text(s)


def test_text_report_lists_the_three_views(conn, staged):
    text = kpi_summary.format_text(kpi_summary.summarize(conn, ["r_h1", "r_h5"]))

    for heading in ("Par algorithme", "Par nombre de variables", "Classement", "Par horizon"):
        assert heading in text
    assert "0.550" in text          # A's mean F1_dir
    assert "premier fold" in text   # the comparison window is stated


# ---------------------------------------------------------------------------
# Total-window screening: every candidate scored ONCE on the whole
# out-of-sample window (split 'valid', fold 0 -- the validation window the finalist is
# chosen on); only the best one goes on to the walk-forward folds ('test'
# split, folds 1..n).
# ---------------------------------------------------------------------------

def _screened(conn, run_id: str, algo: str, n: int, screen: tuple[float, float],
              folds: dict[int, tuple[float, float]] | None = None) -> int:
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", n, "shap")
    f1, acc = screen
    trackdb.add_fold_metrics(conn, tid, 0, "valid", {"F1_dir": f1, "Acc_dir": acc,
                                                       "MCC_4cls": f1 / 10, "BalAcc_4cls": f1 / 2})
    for fold, (f1, acc) in (folds or {}).items():
        trackdb.add_fold_metrics(conn, tid, fold, "test", {"F1_dir": f1, "Acc_dir": acc})
    return tid


@pytest.fixture
def total_window(conn):
    _run(conn, "r_h1", 1)
    _screened(conn, "r_h1", "A", 5, (0.50, 0.55))
    _screened(conn, "r_h1", "A", 6, (0.60, 0.65), folds={1: (0.42, 0.50), 2: (0.44, 0.52), 3: (0.40, 0.48)})
    _screened(conn, "r_h1", "B", 5, (0.40, 0.45))
    _screened(conn, "r_h1", "B", 6, (0.30, 0.35))


def test_candidates_are_compared_on_the_total_window_when_they_were_screened_on_it(conn, total_window):
    s = kpi_summary.summarize(conn, ["r_h1"])

    assert s["window"]["mode"] == "total_window" and s["window"]["folds_by_horizon"] == {1: [0]}
    assert "fenêtre totale" in s["window"]["note"] and "optimiste" in s["window"]["note"]
    by_algo = _by(s["by_algo"], "algo")
    assert by_algo["A"]["F1_dir"] == pytest.approx((0.50 + 0.60) / 2)       # screen scores, not the folds'
    assert by_algo["B"]["F1_dir"] == pytest.approx((0.40 + 0.30) / 2)
    assert [r["algo"] for r in s["by_algo"]] == ["A", "B"]
    assert s["n_candidates"] == 4


def test_the_screening_winner_is_reported_on_the_total_window_and_on_its_walk_forward(conn, total_window):
    h = kpi_summary.summarize(conn, ["r_h1"])["by_horizon"][0]

    assert (h["algo"], h["n_features"]) == ("A", 6)
    assert h["window_F1_dir"] == pytest.approx(0.60)                          # total window (screening)
    assert h["full_F1_dir"] == pytest.approx((0.42 + 0.44 + 0.40) / 3)         # its walk-forward folds
    assert h["full_Acc_dir"] == pytest.approx((0.50 + 0.52 + 0.48) / 3) and h["full_folds"] == 3


def test_text_report_names_the_total_window(conn, total_window):
    assert "fenêtre totale" in kpi_summary.format_text(kpi_summary.summarize(conn, ["r_h1"]))
