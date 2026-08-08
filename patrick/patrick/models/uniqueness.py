"""Phase 6.2 (P6.2) -- uniqueness weights and sequential bootstrap (López de
Prado, "Advances in Financial Machine Learning", chapter 4). With a horizon
`h > 1` and one prediction per bar, label windows overlap: the observation
at bar `t` predicts direction over `[t, t+h]`, so two observations less than
`h` bars apart share information (the same underlying market move partly
double-counted) -- training observations are NOT independent, and the
EFFECTIVE sample size is much lower than `n`."""
from __future__ import annotations

import numpy as np


def build_indicator_matrix(start_positions: np.ndarray, horizon: int, n_bars: int) -> np.ndarray:
    """`ind[i, t] = True` if observation `i` (span `[start_positions[i],
    start_positions[i]+horizon]`, in integer positions on the fold's bar
    grid -- not calendar dates) covers bar `t`. Dense matrix
    (n_obs x n_bars): n_obs is the number of TRAINING observations for a
    single fold (a few hundred), not the whole history -- stays tractable
    in memory."""
    n_obs = len(start_positions)
    ind = np.zeros((n_obs, n_bars), dtype=bool)
    for i, start in enumerate(start_positions):
        start = max(int(start), 0)
        end = min(start + horizon, n_bars - 1)
        if end >= start:
            ind[i, start:end + 1] = True
    return ind


def bar_concurrency(ind: np.ndarray) -> np.ndarray:
    """`c[t]`: number of observations whose span covers bar `t`."""
    return ind.sum(axis=0)


def average_uniqueness(ind: np.ndarray) -> np.ndarray:
    """Average uniqueness per observation: mean of `1/concurrency(t)` over
    the bars covered by that observation. 1.0 if no other observation
    covers it (fully unique), tends toward 0 if many observations overlap
    across its whole span."""
    concurrency = bar_concurrency(ind)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv_c = np.where(concurrency > 0, 1.0 / concurrency, 0.0)
    n_obs = ind.shape[0]
    u = np.zeros(n_obs)
    counts = ind.sum(axis=1)
    for i in range(n_obs):
        if counts[i] > 0:
            u[i] = inv_c[ind[i]].mean()
    return u


def effective_sample_size(avg_uniqueness: np.ndarray) -> float:
    """Sum of average uniquenesses -- the EFFECTIVE sample size (P6.2), to
    report alongside `n`: it governs the interpretation of any metric
    computed on this sample (an F1/MCC on `n=500` rows but `n_eff=80` has
    the statistical uncertainty of a sample of 80, not 500)."""
    return float(avg_uniqueness.sum())


def sequential_bootstrap(ind: np.ndarray, sample_length: int | None = None,
                          rng: np.random.Generator | None = None) -> np.ndarray:
    """Sequential draw (López de Prado, snippet 4.5): at each step, the
    probability of drawing observation `i` is proportional to the average
    uniqueness it WOULD HAVE given the observations ALREADY drawn into THIS
    sample -- dynamically favors observations least concurrent with the
    draw in progress (not just with each other globally, which a static
    sort by uniqueness would do). Returns the INDICES (into `ind`, i.e.
    into the fold's train set), with possible repetition (bootstrap).

    Cost O(sample_length x n_obs x n_bars) -- accepted, this is the KNOWN
    compute cost of this method in the literature, not an unintended
    regression (see the P6.2 report for the measurement on a synthetic
    target)."""
    rng = rng if rng is not None else np.random.default_rng()
    n_obs, n_bars = ind.shape
    sample_length = sample_length if sample_length is not None else n_obs
    ind_int = ind.astype(np.int64)
    span_size = ind_int.sum(axis=1)  # number of bars covered by each observation, fixed
    drawn_concurrency = np.zeros(n_bars, dtype=np.int64)
    phi = np.empty(sample_length, dtype=np.int64)
    for k in range(sample_length):
        candidate_concurrency = drawn_concurrency[None, :] + ind_int  # (n_obs, n_bars)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv_c = np.where(candidate_concurrency > 0, 1.0 / candidate_concurrency, 0.0)
        numer = (inv_c * ind_int).sum(axis=1)
        avg_u = np.divide(numer, span_size, out=np.zeros(n_obs), where=span_size > 0)
        total = avg_u.sum()
        prob = avg_u / total if total > 0 else np.full(n_obs, 1.0 / n_obs)
        choice = int(rng.choice(n_obs, p=prob))
        phi[k] = choice
        drawn_concurrency += ind_int[choice]
    return phi
