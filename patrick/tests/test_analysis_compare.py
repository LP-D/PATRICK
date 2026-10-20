"""Comparateur de runs (`patrick/analysis/compare.py`, `/analyses/comparer`) : chiffres côte à côte, tests de Diebold-Mariano corrigés par Holm,
différences de configuration, refus des cas non comparables."""
from __future__ import annotations

import json

import numpy as np
import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import compare, registry
from patrick.webapp.app import app


def _two_runs(tmp_path, monkeypatch, skill_a=0.8, skill_b=0.5, algo_b="LightGBM"):
    """Deux runs sur la même cible et le même horizon, dans la même base : le second prédit à peu près au hasard."""
    registry.clear_cache()
    conn, info_a = seed_run(tmp_path, monkeypatch, run_id="run_a", skill=skill_a, seed=1)
    # second run : mêmes prix (même graine de prix), autre signal
    from patrick.tracking import db as trackdb
    from patrick.webapp.forms import default_config_dict
    cfg = default_config_dict()
    cfg["name"] = "TST_b"
    cfg["objective"].update({"target_symbol": "TST", "horizons": [2], "regimes": ["GLOBAL"]})
    cfg["models"]["algos"] = [algo_b]
    snap = info_a["snapshot_id"]
    trackdb.create_run(conn, "run_b", "TST", 2, snap, json.dumps(cfg), "h2", "sha", 7)
    tid = trackdb.create_trial(conn, "run_b", "GLOBAL", algo_b, "SMOTE", 5, "shap")
    trackdb.mark_best_trial(conn, tid)
    rows = conn.execute("SELECT ts, fold_index, split, y_true, y_pred, y_proba, p_up FROM prediction WHERE trial_id = ? ORDER BY ts", (info_a["trial_id"],)).fetchall()
    rng = np.random.default_rng(99)
    for split in ("test", "holdout"):
        sub = [r for r in rows if r[2] == split]
        if not sub:
            continue
        copy = rng.random(len(sub)) < skill_b
        ut = np.array([r[3] >= 2 for r in sub])
        up = np.where(copy, ut, ~ut)
        yp = np.where(up, 3.0, 0.0)
        for k in sorted({r[1] for r in sub}):
            idx = [i for i, r in enumerate(sub) if r[1] == k]
            trackdb.add_predictions(conn, tid, k, split, [sub[i][0] for i in idx], [sub[i][3] for i in idx], yp[idx], [0.6] * len(idx),
                                    p_up=np.where(up[idx], 0.7, 0.3))
    trackdb.finish_run(conn, "run_b", status="done", n_trials=1)
    return conn


def test_compare_two_runs_headline_curves_and_dm(tmp_path, monkeypatch):
    conn = _two_runs(tmp_path, monkeypatch)
    out = compare.compare(conn, ["run_a", "run_b"], db_key="cmp")
    assert [r["run_id"] for r in out["runs"]] == ["run_a", "run_b"] and out["same_target"] is True
    a, b = out["runs"]
    assert a["headline"]["test"]["acc"] > b["headline"]["test"]["acc"] + 0.1
    assert a["equity"] and len(a["equity"]["dates"]) <= 700 and a["rolling"] and a["roc"]["auc"] > b["roc"]["auc"]
    pair = out["dm"]["pairs"][0]
    assert pair["reason"] is None and pair["better"] == 0 and pair["p"] < 0.01 and pair["p_adj"] >= pair["p"]
    assert pair["n"] > 500
    diff = {r["key"]: r["values"] for r in out["config_diff"]}
    assert diff["name"] == ["TST_test", "TST_b"] and "models.algos" in diff
    json.dumps(out, allow_nan=False)


def test_holm_correction_is_monotone_and_bounded(tmp_path, monkeypatch):
    conn = _two_runs(tmp_path, monkeypatch, skill_a=0.62, skill_b=0.58)
    from patrick.analysis.context import Ctx
    from patrick.analysis.registry import get_frame
    ctxs = [Ctx(conn, get_frame(conn, r, None, "h"), {}) for r in ("run_a", "run_b")]
    d = compare.dm_matrix(ctxs, ["a", "b"])
    for p in d["pairs"]:
        if p["p"] is not None:
            assert p["p"] <= p["p_adj"] <= 1.0


def test_different_targets_are_not_tested(tmp_path, monkeypatch):
    conn = _two_runs(tmp_path, monkeypatch)
    conn.execute("UPDATE run SET target = 'OTHER' WHERE run_id = 'run_b'")
    conn.commit()
    registry.clear_cache()
    out = compare.compare(conn, ["run_a", "run_b"], db_key="cmp2")
    assert out["same_target"] is False
    assert out["dm"]["pairs"][0]["reason"] == "different_target_or_horizon" and out["dm"]["pairs"][0]["p"] is None
    assert compare.compare(conn, ["run_a", "nope"], db_key="cmp2") is None


def test_config_diff_lists_only_differences():
    rows = compare.config_diff([{"a": 1, "b": {"c": [1, 2], "d": "x"}}, {"a": 1, "b": {"c": [1, 3], "d": "x"}, "e": True}])
    assert {r["key"] for r in rows} == {"b.c", "e"}
    assert next(r for r in rows if r["key"] == "e")["values"] == [None, "true"]


def test_compare_page_and_api(tmp_path, monkeypatch):
    _two_runs(tmp_path, monkeypatch)
    c = TestClient(app)
    page = c.get("/analyses/comparer?run_ids=run_a&run_ids=run_b")
    assert page.status_code == 200 and 'data-run-ids="run_a,run_b"' in page.text
    api = c.get("/api/analyses/compare?run_ids=run_a&run_ids=run_b&cost_bps=10&window=60")
    assert api.status_code == 200 and api.json()["cost_bps"] == 10
    assert c.get("/analyses/comparer?run_ids=run_a").status_code == 400
    assert c.get("/analyses/comparer?run_ids=run_a&run_ids=nope").status_code == 404
    assert c.get("/api/analyses/compare?run_ids=run_a&run_ids=nope").status_code == 404
    assert c.get("/api/analyses/compare?run_ids=" + "&run_ids=".join(["a", "b", "c", "d", "e"])).status_code in (404, 400)


def test_old_comparison_page_links_to_detailed_one(tmp_path, monkeypatch):
    _two_runs(tmp_path, monkeypatch)
    r = TestClient(app).get("/compare-runs?run_ids=run_a&run_ids=run_b")
    assert r.status_code == 200 and "/analyses/comparer?run_ids=run_a&amp;run_ids=run_b" in r.text


@pytest.fixture(autouse=True)
def _clear():
    yield
    registry.clear_cache()
