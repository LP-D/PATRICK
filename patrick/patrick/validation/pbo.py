"""Probability of Backtest Overfitting (Bailey, Borwein, López de Prado & Zhu,
"The Probability of Backtest Overfitting", 2017) via CSCV (Combinatorially
Symmetric Cross-Validation).

Accepted deviation from the original paper: it splits the return series into
S arbitrary time blocks (a free parameter). Here, the blocks are directly the
walk-forward folds already computed by the engine (`fold_metric`, one per
(trial, fold)) — respects the temporal structure by construction (each fold
is already a contiguous chronological slice), no additional split to invent
or justify separately.

Documented limitation: CSCV wants an EVEN number of blocks, ideally S>=16 for
a reasonable number of combinations. `n_wf_folds` defaults to 5 in this
project (odd, designed for walk-forward, not CSCV) — so the oldest fold is
dropped to fall back to an even number (4 by default, 6 IS/OOS
combinations). A higher `n_wf_folds` gives a more robust PBO; documented
rather than hidden, see phase report.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np


def compute_pbo(perf_matrix: np.ndarray) -> dict:
    """`perf_matrix`: (n_trials, n_blocks) — a performance metric (e.g.
    F1_dir) per (trial, time block). For every partition of the blocks into
    two equal halves (in-sample / out-of-sample, all combinations), the best
    trial in IS is identified and its rank in OOS is checked: if it is not
    better than the median of the other trials in OOS (logit <= 0), the
    "in-sample" selection does not generalize — this is backtest
    overfitting. PBO = proportion of combinations in this case."""
    perf_matrix = np.asarray(perf_matrix, dtype=float)
    n_trials, n_blocks = perf_matrix.shape
    if n_blocks % 2 != 0:
        perf_matrix = perf_matrix[:, 1:]
        n_blocks -= 1
    if n_blocks < 2 or n_trials < 2:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": n_trials, "n_blocks": n_blocks,
                "mean_logit": np.nan}

    half = n_blocks // 2
    block_ids = list(range(n_blocks))
    logits = []
    for is_blocks in combinations(block_ids, half):
        oos_blocks = [b for b in block_ids if b not in is_blocks]
        is_perf = perf_matrix[:, list(is_blocks)].mean(axis=1)
        oos_perf = perf_matrix[:, oos_blocks].mean(axis=1)
        best_is_trial = int(np.argmax(is_perf))

        # Relative rank (0,1) of the "best in IS" trial once evaluated in
        # OOS — proportion of the OTHER trials it beats in OOS.
        if n_trials > 1:
            rank = float((oos_perf < oos_perf[best_is_trial]).sum()) / (n_trials - 1)
        else:
            rank = 0.5
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(float(np.log(rank / (1 - rank))))

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr <= 0))
    return {
        "pbo": round(pbo, 4),
        "n_combinations": len(logits_arr),
        "n_trials": n_trials,
        "n_blocks": n_blocks,
        "mean_logit": round(float(np.mean(logits_arr)), 4),
    }
