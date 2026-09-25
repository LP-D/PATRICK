"""F05 -- the Benjamini-Hochberg family must contain EVERY target that was
tested, not only those that happen to carry a Diebold-Mariano p-value.

Before the fix, `tracking/stats.py::fdr_across_targets` built the family from
`dm_result` alone. DM is never computed in CPCV mode, so every CPCV-only
target silently left the family: m shrank, and with it every other target's
BH threshold (k/m * alpha) grew. Trying 20 targets in CPCV and 1 in
walk-forward was scored as if a single target had been tried.

A target without a p-value enters the family with p = 1 ("untestable"):
it can never be declared significant, but it counts in m -- the conservative
treatment of an unobserved test.

F05b (found in the same query): the per-target p-value was the MIN over
every run of that target. The minimum of k p-values is not uniform under
H0 (P(min <= p) = 1 - (1 - p)^k); re-running a target until one DM run
comes out significant was invisible. The per-target p-value is now the
Sidak-adjusted minimum 1 - (1 - p_min)^k (conservative under the positive
dependence between runs of the same target).
"""
from __future__ import annotations

import json

import pytest

from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats


def _run(conn, run_id, target, scheme="walkforward", status="done", p_value=None):
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, None)
    config = {"validation": {"scheme": scheme}}
    trackdb.create_run(conn, run_id, target=target, horizon=5, snapshot_id="snap",
                        config_json=json.dumps(config), config_hash="c", git_sha="g", seed=42)
    trackdb.finish_run(conn, run_id, status=status)
    if p_value is not None:
        trackdb.save_dm_result(conn, run_id, {"baseline": "BASELINE_persistence", "dm_stat": -2.0,
                                               "p_value": p_value}, kind="class_specific")


def test_cpcv_only_targets_count_in_the_bh_family(conn):
    _run(conn, "wf", "^A", p_value=0.02)
    for i in range(4):
        _run(conn, f"cpcv{i}", f"^C{i}", scheme="cpcv")
    fdr = trackstats.fdr_across_targets(conn, alpha=0.10)
    assert fdr["n_tested"] == 5
    assert fdr["n_untestable"] == 4
    assert fdr["results"]["^A"]["adjusted_p_value"] == pytest.approx(0.10)
    for i in range(4):
        r = fdr["results"][f"^C{i}"]
        assert r["untestable"] and not r["significant"]


def test_family_excludes_targets_whose_runs_never_completed(conn):
    _run(conn, "wf", "^A", p_value=0.02)
    _run(conn, "crashed", "^B", status="failed")
    fdr = trackstats.fdr_across_targets(conn)
    assert fdr["n_tested"] == 1
    assert "^B" not in fdr["results"]


def test_repeated_runs_of_a_target_are_sidak_adjusted_not_min_picked(conn):
    for i, p in enumerate((0.03, 0.40, 0.70)):
        _run(conn, f"r{i}", "^A", p_value=p)
    fdr = trackstats.fdr_across_targets(conn, alpha=0.10)
    r = fdr["results"]["^A"]
    assert r["best_run_p_value"] == pytest.approx(0.03)
    assert r["n_runs_with_p_value"] == 3
    assert r["p_value"] == pytest.approx(1 - (1 - 0.03) ** 3)


def test_no_p_value_anywhere_is_reported_as_not_computable(conn):
    _run(conn, "c", "^C", scheme="cpcv")
    fdr = trackstats.fdr_across_targets(conn)
    assert fdr["n_with_p_value"] == 0
    assert fdr["n_bh_significant"] == 0
