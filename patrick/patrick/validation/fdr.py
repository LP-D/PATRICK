"""Phase 6.4 (P6.4) -- FDR correction (Benjamini-Hochberg, 1995) across ALL
historically tested targets -- distinct from the multi-testing guards
already in place (section 4 of METHODOLOGY.md), which correct for the
number of CONFIG TRIALS within a single (target, horizon): successively
trying N different targets (VIX, then GSPC, then SPY...) and keeping the one
whose Diebold-Mariano test is significant raises the SAME multiple-testing
problem, at a different scale -- across 20 targets with no real signal at
all, about 1 would appear "significant" at p<0.05 by pure chance.

Pure function (no SQLite dependency): `benjamini_hochberg` takes a dict
{target: best historical DM p-value} and returns, for each target, its
adjusted p-value (q-value) and its significance status at the chosen FDR
threshold -- the bridge to the database (`tracking/stats.py::fdr_across_targets`)
builds this dict from `dm_result`/`run`.
"""
from __future__ import annotations


def benjamini_hochberg(p_values: dict[str, float], alpha: float = 0.10) -> dict:
    """Benjamini-Hochberg (step-up) procedure: adjusted p-values (q-values)
    such that `significant = (q <= alpha)` is equivalent to the original
    criterion (largest k such that p_(k) <= (k/m)*alpha, rejects 1..k) --
    standard equivalence, see Benjamini & Hochberg (1995).

    `p_values`: {target: p_value}, NaN silently excluded (target with no
    valid DM trial, e.g. all its runs in CPCV mode -- see P6.1 limitation,
    Diebold-Mariano not computed in that scheme)."""
    items = [(k, v) for k, v in p_values.items() if v == v]  # excludes NaN
    m = len(items)
    if m == 0:
        return {"alpha": alpha, "n_tested": 0, "n_raw_significant": 0,
                "n_bh_significant": 0, "results": {}}

    items_sorted = sorted(items, key=lambda kv: kv[1])
    raw_p = [v for _, v in items_sorted]

    # q_(i) = min_{j>=i} (m/j * p_(j)) -- computed from the end backward to
    # guarantee monotonicity (q_(1) <= q_(2) <= ... <= q_(m)).
    adjusted = [0.0] * m
    adjusted[-1] = min(1.0, raw_p[-1])
    for i in range(m - 2, -1, -1):
        adjusted[i] = min(adjusted[i + 1], raw_p[i] * m / (i + 1))

    results = {}
    n_bh_sig = 0
    n_raw_sig = 0
    for idx, (target, p) in enumerate(items_sorted):
        sig = adjusted[idx] <= alpha
        n_bh_sig += int(sig)
        n_raw_sig += int(p <= alpha)
        results[target] = {
            "p_value": p, "adjusted_p_value": adjusted[idx],
            "rank": idx + 1, "significant": sig,
        }
    return {
        "alpha": alpha, "n_tested": m,
        "n_raw_significant": n_raw_sig, "n_bh_significant": n_bh_sig,
        "results": results,
    }
