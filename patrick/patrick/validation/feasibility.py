"""Walk-forward feasibility of a (ticker, horizon) combination -- Phase 1
(feature/expanded-horizons). This is the ONE hard technical gate of that
phase: PATRICK is otherwise an exploratory research platform that exposes
options with a warning rather than blocking them by default (see
`config/defaults.py`/`webapp/forms.py` docstrings for that general stance),
but a run launched on an infeasible combination here either crashes or
produces statistically empty walk-forward folds -- not something a warning
can make safe to ignore, so it stays a hard block (`check_feasibility`/
`is_feasible` below), never just a warning.

Derivation (see `validation/walkforward.py::build_fold_cuts` and
`validation/embargo.py::embargo_mask`, both already parametrized by horizon
and audited separately from this module): the available history (`n_obs`
observations) is split into `n_wf_folds` walk-forward TEST segments, the
first (and smallest -- the last absorbs the remainder of the integer
division) sized

    test_span = (n_obs - int(n_obs * min_train_frac)) // n_wf_folds

Embargo (enabled by default, `embargo_bars` defaulting to the horizon itself
-- `config/defaults.py::DEFAULT_EMBARGO_BARS`/`DEFAULT_EMBARGO_ENABLED`) then
drops the first `embargo_bars` rows of EVERY test fold: if
`embargo_bars >= test_span`, the fold is emptied entirely, and a run over
every fold empty (or nearly) produces no statistically meaningful test set.
The binding constraint is therefore exactly `test_span > horizon`.

With the CURRENT defaults (`n_wf_folds=5`, `min_train_frac=0.40`),
`test_span ~= 0.12 * n_obs`, giving the corrected feasibility threshold
`n_obs > horizon / 0.12 ~= 8.33 x horizon` bars -- NOT the naive 6x used in
an earlier one-off audit (too optimistic: it did not account for the
interaction between `n_wf_folds`/`min_train_frac` and the embargo). This
module computes the EXACT integer threshold from the real `build_fold_cuts`
formula rather than hardcoding the rounded 8.33x constant, so it tracks any
future change to `config/defaults.py` automatically -- and, symmetrically,
never hardcodes a static table of "known" per-ticker history depths: how
much history is actually available for a given symbol is read from the
local data lake (`data/store.py`) AT CALL TIME, since it grows every day a
run ingests fresh data.
"""
from __future__ import annotations

from dataclasses import dataclass

from patrick.config.defaults import DEFAULT_MIN_TRAIN_FRAC, DEFAULT_N_WF_FOLDS
from patrick.data.store import DataStore


def min_test_fold_size(n_obs: int, n_wf_folds: int = DEFAULT_N_WF_FOLDS,
                        min_train_frac: float = DEFAULT_MIN_TRAIN_FRAC) -> int:
    """Size of the smallest walk-forward TEST fold `build_fold_cuts` would
    produce for `n_obs` observations. Always the size of the first
    `n_wf_folds - 1` folds (`build_fold_cuts` gives them all the same
    `test_span`); the last fold absorbs the leftover from the integer
    division and so is never smaller -- this is genuinely the minimum
    across every fold, not an approximation of it."""
    if n_obs <= 0 or n_wf_folds <= 0:
        return 0
    first_cut = int(n_obs * min_train_frac)
    return max(0, (n_obs - first_cut) // n_wf_folds)


def is_feasible(n_obs: int, horizon: int, n_wf_folds: int = DEFAULT_N_WF_FOLDS,
                 min_train_frac: float = DEFAULT_MIN_TRAIN_FRAC) -> bool:
    """True if a walk-forward run over `n_obs` observations at this
    `horizon` would leave at least one TEST row per fold after embargo
    (default `embargo_bars = horizon`, see `validation/embargo.py`)."""
    if horizon <= 0:
        return True
    return min_test_fold_size(n_obs, n_wf_folds, min_train_frac) > horizon


def min_obs_required(horizon: int, n_wf_folds: int = DEFAULT_N_WF_FOLDS,
                      min_train_frac: float = DEFAULT_MIN_TRAIN_FRAC) -> int:
    """Smallest `n_obs` for which `is_feasible(n_obs, horizon)` holds -- the
    inverse of the check above, used to phrase the "N bars required" part of
    the UI/error message. Found by direct search rather than an algebraic
    inverse of the integer-division formula (`test_span` is a floor
    division, not exactly invertible in closed form) -- horizons stay small
    enough (up to ~756) that a linear scan costs nothing measurable."""
    if horizon <= 0:
        return 0
    n = horizon + 1
    while not is_feasible(n, horizon, n_wf_folds, min_train_frac):
        n += 1
    return n


@dataclass(frozen=True)
class FeasibilityResult:
    symbol: str
    horizon: int
    feasible: bool
    n_obs: int | None  # None when nothing is cached yet for this symbol
    n_obs_required: int
    source: str  # "store" (real cached history) | "unknown" (nothing cached)
    reason: str


def check_feasibility(symbol: str, horizon: int, store: DataStore | None = None,
                       n_wf_folds: int = DEFAULT_N_WF_FOLDS,
                       min_train_frac: float = DEFAULT_MIN_TRAIN_FRAC) -> FeasibilityResult:
    """Feasibility of (symbol, horizon), based on the REAL history depth
    currently in the local data lake (`data/store.py`, key `raw_<symbol>` --
    the exact same cache `data/ingest.py::ingest` reads/writes when `symbol`
    is used as a run's target) -- never a static, hand-maintained table of
    "known" history depths, which would silently drift as the cache grows.

    When nothing is cached yet for `symbol` (never launched as a target
    before), there is no depth to check against: per this phase's guiding
    principle (expose with a warning rather than block by prudence, except
    for this module's own hard technical gate, which only applies once we
    KNOW the history is too short), the combination is reported
    `feasible=True` with `source="unknown"` and an explicit `reason` --
    an unverified ticker is not assumed broken."""
    store = store or DataStore()
    required = min_obs_required(horizon, n_wf_folds, min_train_frac)
    cache_key = f"raw_{symbol}"

    if not store.exists(cache_key):
        return FeasibilityResult(
            symbol=symbol, horizon=horizon, feasible=True, n_obs=None,
            n_obs_required=required, source="unknown",
            reason=(f"Historique non encore mis en cache pour {symbol} "
                    "(jamais lance comme cible) -- faisabilite non verifiee "
                    f"pour un horizon de {horizon}j."),
        )

    n_obs = len(store.load(cache_key))
    feasible = is_feasible(n_obs, horizon, n_wf_folds, min_train_frac)
    if feasible:
        reason = (f"Historique suffisant pour {symbol} : {n_obs}j disponibles, "
                   f"{required}j requis pour un horizon de {horizon}j.")
    else:
        reason = (f"Historique insuffisant pour {symbol} : {n_obs}j disponibles, "
                   f"{required}j requis pour un horizon de {horizon}j.")
    return FeasibilityResult(
        symbol=symbol, horizon=horizon, feasible=feasible, n_obs=n_obs,
        n_obs_required=required, source="store", reason=reason,
    )
