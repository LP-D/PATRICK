"""Briques statistiques pures de l'analyse des entraînements (`patrick/analysis/stats_core.py`)."""
from __future__ import annotations

import math

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score, roc_curve

from patrick.analysis import stats_core as sc


def test_clean_and_jsonable_handle_nan_inf_and_numpy():
    out = sc.jsonable({"a": np.float64("nan"), "b": [np.int64(3), np.inf], "c": np.array([1.0, np.nan]), "d": np.bool_(True)})
    assert out == {"a": None, "b": [3, None], "c": [1.0, None], "d": True}


def test_thin_indices_keeps_ends_and_bounds_size():
    idx = sc.thin_indices(10_000, 300)
    assert idx[0] == 0 and idx[-1] == 9_999 and len(idx) <= 300
    assert list(sc.thin_indices(5, 300)) == [0, 1, 2, 3, 4]


def test_wilson_matches_known_value_and_edges():
    lo, hi = sc.wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert sc.wilson(0, 0) == (None, None)
    lo0, hi0 = sc.wilson(0, 20)
    assert lo0 == 0.0 and 0.0 < hi0 < 0.2


def test_binom_p_greater_basic():
    assert sc.binom_p_greater(60, 100, 0.5) < 0.05
    assert sc.binom_p_greater(50, 100, 0.5) > 0.4
    assert sc.binom_p_greater(1, 0, 0.5) is None
    assert sc.binom_p_greater(1, 10, 1.5) is None


def test_auc_matches_sklearn_including_ties():
    rng = np.random.default_rng(0)
    y = rng.random(400) < 0.45
    s = np.round(rng.random(400) + 0.3 * y, 1)                    # beaucoup d'ex æquo
    assert sc.auc(y, s) == pytest.approx(roc_auc_score(y, s), abs=1e-12)
    assert sc.auc(np.ones(5, bool), np.arange(5)) is None


def test_roc_curve_matches_sklearn_endpoints_and_area():
    rng = np.random.default_rng(1)
    y = rng.random(300) < 0.5
    s = rng.random(300) + 0.5 * y
    r = sc.roc_curve(y, s, max_points=10_000)
    fpr, tpr, _ = roc_curve(y, s)
    assert r["fpr"][0] == 0 and r["tpr"][0] == 0 and r["fpr"][-1] == 1 and r["tpr"][-1] == 1
    assert np.trapezoid(r["tpr"], r["fpr"]) == pytest.approx(np.trapezoid(tpr, fpr), abs=1e-9)
    assert len(sc.roc_curve(y, s, max_points=20)["fpr"]) <= 20


def test_pr_curve_base_rate_and_perfect_classifier():
    y = np.array([1, 1, 0, 0, 1, 0, 0, 0], dtype=bool)
    perfect = sc.pr_curve(y, y.astype(float))
    assert perfect["ap"] == pytest.approx(1.0)
    assert perfect["base_rate"] == pytest.approx(3 / 8)
    assert sc.pr_curve(np.zeros(5, bool), np.arange(5))["ap"] is None


def test_reliability_perfectly_calibrated_has_small_ece_and_decomposes_brier():
    rng = np.random.default_rng(2)
    p = rng.random(20_000)
    y = (rng.random(20_000) < p).astype(float)
    r = sc.reliability(p, y, 10, "uniform")
    assert r["ece"] < 0.02
    assert sum(b["n"] for b in r["bins"]) == 20_000
    assert r["brier"] == pytest.approx(r["reliability"] - r["resolution"] + r["uncertainty"], abs=0.01)


def test_reliability_overconfident_model_has_large_ece():
    rng = np.random.default_rng(3)
    p = np.where(rng.random(5000) < 0.5, 0.95, 0.05)
    y = (rng.random(5000) < 0.5).astype(float)
    assert sc.reliability(p, y, 10)["ece"] > 0.35


def test_reliability_empty_and_constant_inputs_do_not_raise():
    assert sc.reliability([], [])["bins"] == []
    r = sc.reliability(np.full(50, 0.5), np.tile([0.0, 1.0], 25))
    assert r["n"] == 50 and r["ece"] == pytest.approx(0.0, abs=1e-9)


def test_confusion_matrix_and_per_class_scores():
    cm = sc.confusion_matrix([0, 0, 1, 2, 3, 3, 9], [0, 1, 1, 2, 3, 2, 0])         # 9 hors classes : ignoré
    assert cm.sum() == 6 and cm[0, 0] == 1 and cm[0, 1] == 1 and cm[3, 2] == 1
    scores = sc.per_class_scores(cm)
    assert scores[1]["precision"] == pytest.approx(0.5) and scores[1]["recall"] == pytest.approx(1.0)
    assert scores[3]["support"] == 2


def test_binary_scores_hand_computed():
    t = np.array([1, 1, 1, 0, 0, 0, 0, 1], dtype=bool)
    p = np.array([1, 1, 0, 0, 0, 1, 0, 1], dtype=bool)
    s = sc.binary_scores(t, p)
    assert (s["tp"], s["fp"], s["tn"], s["fn"]) == (3, 1, 3, 1)
    assert s["acc"] == pytest.approx(0.75)
    assert s["f1_up"] == pytest.approx(0.75) and s["f1_dir"] == pytest.approx(0.75)
    assert s["mcc"] == pytest.approx(0.5)
    assert sc.binary_scores([], [])["acc"] is None


def test_rolling_mean_nan_prefix_and_values():
    r = sc.rolling_mean(np.arange(10, dtype=float), 3)
    assert np.isnan(r[:2]).all() and r[2] == pytest.approx(1.0) and r[9] == pytest.approx(8.0)
    assert np.isnan(sc.rolling_mean([1.0, 2.0], 5)).all()
    r2 = sc.rolling_mean([1, np.nan, 3, 4, 5], 2)
    assert np.isnan(r2[1]) and np.isnan(r2[2]) and r2[3] == pytest.approx(3.5)


def test_performance_summary_matches_simple_cases():
    flat = sc.performance_summary(np.zeros(100))
    assert flat["total"] == 0 and flat["max_dd"] == 0
    up = sc.performance_summary(np.full(252, 0.001))
    assert up["total"] == pytest.approx(1.001 ** 252 - 1, rel=1e-9) and up["cagr"] == pytest.approx(up["total"], rel=1e-9)
    assert up["win_rate"] == 1.0
    dd = sc.drawdown_series(sc.equity_from_returns([0.1, -0.5, 0.1]))
    assert dd.min() == pytest.approx(-0.5)
    assert sc.performance_summary([])["n"] == 0


def test_block_bootstrap_interval_contains_point_and_shrinks_with_n():
    rng = np.random.default_rng(4)
    x = rng.normal(0.2, 1.0, 400)
    res = sc.block_bootstrap(lambda a: float(a.mean()), (x,), block=5, n_boot=300, seed=1)
    assert res["lo"] < res["point"] < res["hi"]
    big = sc.block_bootstrap(lambda a: float(a.mean()), (rng.normal(0.2, 1.0, 4000),), block=5, n_boot=300, seed=1)
    assert (big["hi"] - big["lo"]) < (res["hi"] - res["lo"])
    short = sc.block_bootstrap(lambda a: float(a.mean()), (x[:5],), block=5)
    assert short["lo"] is None


def test_block_shuffle_keeps_blocks_intact_and_multiset():
    rng = np.random.default_rng(5)
    v = np.arange(23)
    out = sc.block_shuffle(v, 5, rng)
    assert sorted(out) == list(v)
    # chaque bloc de 5 reste consécutif (le dernier bloc, de 3 valeurs, aussi)
    assert any(np.array_equal(out[i:i + 5], np.arange(a, a + 5)) for i in range(len(out) - 4) for a in (0, 5, 10, 15))


def _acc(t, p):
    return float((np.asarray(t) == np.asarray(p)).mean())


def test_permutation_test_detects_skill_and_accepts_noise():
    rng = np.random.default_rng(6)
    truth = rng.random(600) < 0.5
    skilled = np.where(rng.random(600) < 0.7, truth, ~truth)
    noise = rng.random(600) < 0.5
    assert sc.permutation_test(_acc, truth, skilled, block=2, n_perm=300, seed=0)["p_value"] < 0.01
    assert sc.permutation_test(_acc, truth, noise, block=2, n_perm=300, seed=0)["p_value"] > 0.05
    assert sc.permutation_test(_acc, truth[:5], skilled[:5])["p_value"] is None


def test_shift_curve_peaks_at_zero_for_a_aligned_signal():
    rng = np.random.default_rng(7)
    truth = rng.random(3000) < 0.5                         # sans mémoire : un décalage détruit l'alignement
    pred = np.where(rng.random(3000) < 0.75, truth, ~truth)
    curve = sc.shift_curve(truth, pred, 6)
    assert next(c["lag"] for c in curve) == -6 and len(curve) == 13
    best = max(curve, key=lambda c: c["acc"])
    assert best["lag"] == 0 and best["acc"] > 0.7
    assert all(abs(c["acc"] - 0.5) < 0.05 for c in curve if c["lag"] != 0)


def test_spearman_and_longest_runs():
    x = np.arange(50, dtype=float)
    assert sc.spearman(x, x)["rho"] == pytest.approx(1.0)
    assert sc.spearman(x, np.ones(50))["rho"] is None
    runs = sc.longest_runs([0, 1, 1, 1, 0, 1, 1, 0, 1], 2)
    assert runs[0] == {"start": 1, "end": 3, "length": 3} and runs[1]["length"] == 2


def test_sharpe_and_sortino_zero_variance():
    assert sc.sharpe(np.full(10, 0.01)) is None
    assert sc.sharpe([0.01]) is None
    s = sc.sharpe(np.tile([0.02, -0.01], 100))
    assert s is not None and s > 0 and math.isfinite(s)
