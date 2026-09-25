"""Cross-platform reproducibility of model/feature selection at identical seed.

Symptom (documented in `test_drift_psi_infrastructure.py`, masked there by a
monkeypatch pinning the exported features): the same seed, the same library
versions, the same data select "RandomForest N=8" on the Linux CI runner and
"XGBoost N=5" on Windows.

Two root causes, each measured before any fix:

1. Tie ordering of `np.argsort` (default `kind="quicksort"`) depends on the
   CPU's SIMD dispatch (numpy >= 2 routes it through x86-simd-sort /
   highway). Measured on the same machine, same input (1000 importances,
   995 of them exactly 0 -- the normal case for a 60-tree prefilter on a
   2000-column pool): default dispatch returns ...329, 331, 332... for the
   zero-importance tail; with `NPY_DISABLE_CPU_FEATURES="X86_V4 X86_V3"`
   (an AVX2-less CPU) it returns ...336, 331, 332... `pandas.sort_values`
   goes through the same argsort, so `Leaderboard.best()` breaks F1_dir
   ties (frequent: F1 on discrete predictions) the same CPU-dependent way.
2. `n_jobs=-1` on the selection XGBoost models means "one thread per logical
   core" -- the histogram reduction order follows the thread partition, so
   feature importances differ at float precision between machines with a
   different core count (measured: 104 of 400 importances differ, max
   |delta| 2.3e-9, n_jobs=1 vs n_jobs=2, same data/seed) and near-ties
   flip rank.

Plus a selection-bias defect found while reading `Leaderboard.best()`
(F07): it returned the single best (config, fold) ROW -- i.e. it ranked
configurations by their luckiest fold, not by their walk-forward average,
then compared that max against fold-AVERAGED tuned scores.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from patrick.features import interactions
from patrick.pipeline.leaderboard import Leaderboard
from patrick.selection import _common, lasso_select, shap_select

_TIED_IMPORTANCES = "np.r_[[3.0, 1.0, 2.0, 1.0, 3.0], np.zeros(995)]"

_PROBE = textwrap.dedent(f"""
    import numpy as np
    from patrick.selection import _common

    class _Fake:
        def __init__(self, **kw):
            self.feature_importances_ = {_TIED_IMPORTANCES}
        def fit(self, X, y):
            return self

    _common.XGBClassifier = _Fake
    X = np.zeros((10, 1000)); y = np.zeros(10, dtype=int)
    print(",".join(map(str, _common.prefilter_pool(X, y, prefilter=20))))
""")


def _run_probe(disabled_features: str) -> list[int]:
    env = dict(os.environ, NPY_DISABLE_CPU_FEATURES=disabled_features)
    out = subprocess.run([sys.executable, "-c", _PROBE], env=env, capture_output=True,
                         text=True, check=True).stdout.strip().splitlines()[-1]
    return [int(v) for v in out.split(",")]


def test_prefilter_ranking_is_identical_across_cpu_simd_dispatch():
    baseline = _run_probe("")
    no_avx = _run_probe("X86_V4 X86_V3")
    assert baseline == no_avx


def test_prefilter_ranking_breaks_ties_by_ascending_column_index():
    ranked = _run_probe("")
    assert ranked == [0, 4, 2, 1, 3] + list(range(5, 20))


def test_rank_top_puts_nan_scores_last():
    scores = np.array([np.nan, 0.5, 0.5, 2.0])
    assert list(_common.rank_top(scores, 4)) == [3, 1, 2, 0]


@pytest.mark.parametrize("module, attr", [
    (_common, "XGBClassifier"),
    (shap_select, "XGBClassifier"),
    (interactions, "XGBClassifier"),
])
def test_selection_xgboost_models_use_a_fixed_thread_count(monkeypatch, module, attr):
    seen = []

    class _Spy:
        def __init__(self, **kwargs):
            seen.append(kwargs.get("n_jobs"))
            raise RuntimeError("stop")

    monkeypatch.setattr(module, attr, _Spy)
    X = np.zeros((30, 600)); y = np.arange(30) % 4
    with pytest.raises(RuntimeError, match="stop"):
        if module is _common:
            _common.prefilter_pool(X, y, prefilter=10)
        elif module is shap_select:
            monkeypatch.setattr(shap_select, "prefilter_pool", lambda *a, **k: np.arange(5))
            shap_select.shap_rank(X, y, [], 3, prefilter=10)
        else:
            interactions._prefilter_top(X, y, [f"c{i}" for i in range(600)], 5)
    assert seen and all(v == _common.SELECTION_N_JOBS for v in seen)
    assert _common.SELECTION_N_JOBS >= 1


def test_lasso_uses_a_fixed_thread_count(monkeypatch):
    seen = []

    class _Spy:
        def __init__(self, **kwargs):
            seen.append(kwargs.get("n_jobs"))
            raise RuntimeError("stop")

    monkeypatch.setattr(lasso_select, "LogisticRegression", _Spy)
    monkeypatch.setattr(lasso_select, "prefilter_pool", lambda *a, **k: np.arange(5))
    with pytest.raises(RuntimeError, match="stop"):
        lasso_select.lasso_rank(np.zeros((20, 5)), np.arange(20) % 4, 3, prefilter=10)
    assert seen == [_common.SELECTION_N_JOBS]


def _rows(order):
    rows = {
        "A": [{"horizon": 1, "regime": "GLOBAL", "N": 8, "sampler": "SMOTE", "algo": "RandomForest", "fold": f, "F1_dir": 0.6}
              for f in (1, 2)],
        "B": [{"horizon": 1, "regime": "GLOBAL", "N": 5, "sampler": "SMOTE", "algo": "XGBoost", "fold": f, "F1_dir": 0.6}
              for f in (1, 2)],
    }
    return [r for key in order for r in rows[key]]


def test_best_is_invariant_to_insertion_order_on_tied_scores():
    b1, b2 = Leaderboard(), Leaderboard()
    b1.rows = _rows("AB")
    b2.rows = _rows("BA")
    assert (b1.best()["algo"], b1.best()["N"]) == (b2.best()["algo"], b2.best()["N"])


def test_top_k_is_invariant_to_insertion_order_on_tied_scores():
    b1, b2 = Leaderboard(), Leaderboard()
    b1.rows = _rows("AB")
    b2.rows = _rows("BA")
    assert b1.top_k(2) == b2.top_k(2)


def test_best_ranks_configs_by_walk_forward_mean_not_by_their_luckiest_fold():
    board = Leaderboard()
    lucky = {"horizon": 1, "regime": "GLOBAL", "N": 5, "sampler": "SMOTE", "algo": "XGBoost"}
    steady = {"horizon": 1, "regime": "GLOBAL", "N": 8, "sampler": "SMOTE", "algo": "LightGBM"}
    for fold, f1 in enumerate((0.90, 0.10, 0.10), start=1):
        board.add(**lucky, fold=fold, F1_dir=f1)
    for fold in (1, 2, 3):
        board.add(**steady, fold=fold, F1_dir=0.50)
    best = board.best()
    assert best["algo"] == "LightGBM"
    assert best["F1_dir"] == pytest.approx(0.50)


def test_best_on_single_row_per_config_boards_is_unchanged():
    board = Leaderboard()
    board.add(horizon=1, regime="GLOBAL", N=5, sampler="SMOTE", algo="XGBoost", scheme="cpcv", F1_dir=0.55)
    board.add(horizon=1, regime="GLOBAL", N=6, sampler="SMOTE", algo="XGBoost", scheme="cpcv", F1_dir=0.58)
    assert board.best()["N"] == 6
