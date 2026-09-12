"""Phase 2 (feature/guida-features-full) -- Tony Guida's factor taxonomy
(Tony Guida (ed.), "Big Data and Machine Learning in Quantitative
Investment", CFA Institute Research Foundation), covering the families that
don't fit cleanly into `technical.py`/`spike.py`/`vol_models.py`/`macro.py`
(which were themselves extended, this session, with the same 14-lookback
grid -- `config.defaults.GUIDA_LOOKBACKS` -- rather than duplicated here).

STATUS OF THE 9 FAMILIES SCOPED FOR THIS PHASE
------------------------------------------------
1-5. technical (incl. RSI) / interactions / spike / vol_models / macro:
     CALCULABLE, real data, no estimation -- see `technical.py`, `spike.py`,
     `vol_models.py`, `macro.py`. `interactions.py` needed no code change:
     `discover_interactions` operates generically on whatever columns are in
     the pool it's handed, so it automatically benefits from every extra
     Guida-lookback column produced by the families above once
     `enable_guida_features=True` -- it has no lookback of its own to extend.
6. Carry (`eurusd_carry_features`, below): ESTIMATED, EUR/USD only.
7. Cross-sectional momentum (`cross_sectional_momentum_features`, below):
   real data, but restricted to ONE group and still flagged `_estimated`
   (see its docstring) -- proxy for the true Guida definition.
8. Idiosyncratic volatility (`idiosyncratic_volatility_features`, below):
   ESTIMATED, factor is a simple equal-weighted in-universe proxy.
9. Basis momentum: ABSENT -- see below. Not implemented.
10. Open-interest moving averages: ABSENT -- see below. Not implemented.
(Numbering follows the task's own list, which has 9 named families plus the
`is_estimated` metadata point; basis momentum and OI are #5 and #8 of the
task's list -- renumbered here only for this docstring's own bookkeeping.)

WHY BASIS MOMENTUM IS NOT IMPLEMENTED
--------------------------------------
Guida's basis momentum factor needs, per commodity: (a) open interest and
(b) the futures TERM STRUCTURE (at least two contract maturities, to define
"basis" = near-vs-far price gap, and its momentum over time). Grepping
`patrick/patrick/data/sources/` confirms NEITHER exists anywhere in the
ingestion layer: `yfinance_source.py` downloads a single continuous
front-month series per commodity ticker (e.g. "GC=F") via `yf.download(...,
auto_adjust=True)["Close"]` -- no second/third maturity is ever requested,
and yfinance's free download path for these continuous futures symbols does
not expose open interest at all (that data lives behind exchange-licensed
feeds this project has no source for). `fred_source.py` has no
commodity-specific open-interest or term-structure series either (FRED
carries macro/rate series, not derivatives-market microstructure). This is a
hard data-availability constraint, not a "difficult to obtain" judgment
call -- no column in `data/sources/*` can be repurposed into a defensible
single-series proxy for a factor that is fundamentally two-input.

WHY OPEN-INTEREST MOVING AVERAGES ARE NOT IMPLEMENTED
-------------------------------------------------------
Same root cause as basis momentum's first ingredient: no open-interest field
exists anywhere in `data/sources/*`, for commodities or any other asset
class. A moving average of a series this codebase never downloads cannot be
computed without inventing the underlying data.

THE `_ESTIMATED` NAMING CONVENTION (task point 9)
---------------------------------------------------
Every column produced by this module carries an explicit `_estimated`
suffix -- chosen over a separate metadata dict because it survives every
existing transformation in the pipeline (concat, rename, SHAP importance
tables, the CSV/leaderboard export, the glossary) with zero extra plumbing,
and is trivially greppable. This is a NAMING/documentation convention only:
these columns are concatenated into the SAME feature pool as every other
family in `pipeline/engine.py::build_base_feature_pool` and go through
SHAP/FDR selection completely unfiltered -- no special-casing, no
pre-exclusion. Whether an `_estimated` feature is useful is exactly the
question SHAP selection already answers for every other feature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config import defaults as D
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.features._utils import safe_pct_change

_ANNUALIZE = np.sqrt(252)


# ---------------------------------------------------------------------------
# Shared helper: rolling simple OLS (one regressor + intercept), closed form.
# ---------------------------------------------------------------------------

def rolling_ols_residual_std(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """Rolling residual std of a simple OLS `y = alpha_t + beta_t * x +
    resid`, (alpha_t, beta_t) re-fit at every bar `t` over the trailing
    `window` observations ending at `t` (causal by construction, same
    "trailing window, evaluate current point" convention as every other
    rolling estimator in this codebase, e.g. `vol_models.
    heston_proxy_features`).

    Closed-form simple OLS (classic normal-equations solution, PAS de deep
    learning), using the standard variance-decomposition identity rather
    than materializing per-window residuals (which would need a second,
    nested rolling pass): for a window's sample moments Var(x), Var(y),
    Cov(x,y) (pandas ddof=1 convention throughout),
        beta = Cov(x,y) / Var(x)
        Var(resid) = Var(y) - beta * Cov(x,y)
    -- algebraically exact (SS_res = S_yy - S_xy^2/S_xx, the textbook OLS
    identity, divided through by (n-1) like pandas' own `.var()`/`.std()`;
    not the textbook (n-2)-corrected UNBIASED regression variance, an
    accepted simplification consistent with every other simple `.std()`
    call in this codebase). `Var(resid)` is clipped at 0 before the sqrt as
    a guard against a floating-point rounding artifact producing a tiny
    negative value when beta*Cov(x,y) is very close to Var(y) (e.g. a
    near-perfect fit)."""
    var_y = y.rolling(window).var()
    var_x = x.rolling(window).var()
    cov_xy = x.rolling(window).cov(y)
    beta = cov_xy / var_x.replace(0, np.nan)
    var_resid = (var_y - beta * cov_xy).clip(lower=0)
    return np.sqrt(var_resid)


# ---------------------------------------------------------------------------
# 6. Carry -- EUR/USD only, ESTIMATED.
# ---------------------------------------------------------------------------

EURUSD_US_RATE_COLUMN = "US3M_Rate"  # FRED DTB3 (3-month T-bill), see config/defaults.py

CARRY_GUIDA_WINDOWS: tuple[int, ...] = (22, 66, 252)


def eurusd_carry_features(raw: pd.DataFrame, us_rate_col: str = EURUSD_US_RATE_COLUMN,
                           windows: list[int] = CARRY_GUIDA_WINDOWS) -> pd.DataFrame:
    """ESTIMATED EUR/USD carry proxy -- documented gap from the true Guida
    definition: real FX carry is a rate DIFFERENTIAL (foreign rate minus
    domestic rate, or equivalently the forward-implied points). This
    codebase's FRED universe (`config.defaults.DEFAULT_TARGET_GROUPS
    ["Macro (FRED)"]`, audited by hand: DGS1/2/3/5/7/10/20/30, DTB1/3/6,
    EFFR, DFF, FEDFUNDS, SOFR, ...) contains ONLY US-side short rates -- no
    EURIBOR/€STR/EONIA or any other Eurozone short-rate series. Rather than
    invent a Euro-side value, this proxy exposes ONLY the US leg (level and
    change of `us_rate_col`, default FRED DTB3 = `US3M_Rate`, the 3-month
    T-bill already in the universe) -- a genuinely PARTIAL, one-sided
    substitute for the true differential (as the US rate rises with the
    Euro rate held fixed, USD carry pressure rises -- but any REAL EUR-side
    move is invisible to this proxy). Flagged `_estimated`; left to SHAP/FDR
    to judge, not pre-filtered.

    Returns an EMPTY DataFrame if `us_rate_col` is absent from `raw` (hard
    data constraint: no fabricated column) -- e.g. a run whose
    `universe.fred_series` doesn't include DTB3/US3M_Rate."""
    if us_rate_col not in raw.columns:
        return pd.DataFrame(index=raw.index)
    us_rate = raw[us_rate_col]
    out = {}
    for w in windows:
        out[f"EURUSD_carry_us_rate_level_{w}d_estimated"] = us_rate.rolling(w).mean()
        out[f"EURUSD_carry_us_rate_chg_{w}d_estimated"] = us_rate.diff(w)
    return pd.DataFrame(out, index=raw.index)


# Commodities: task point 4 explicitly requires marking carry ABSENT there
# (no futures-curve data in `data/sources/*` to derive a roll yield / basis
# from -- same root-cause data gap as basis momentum below) -- no function,
# no column, no proxy invented; documented here rather than duplicating the
# "why" already spelled out for basis momentum in the module docstring.


# ---------------------------------------------------------------------------
# 7. Cross-sectional momentum -- commodities only.
# ---------------------------------------------------------------------------

COMMODITY_GROUP_NAME = "Matieres premieres (futures)"
_COMMODITY_GROUP_NAME_ACCENTED = "Matières premières (futures)"

CROSS_SECTIONAL_MOMENTUM_WINDOWS: tuple[int, ...] = (22, 66, 252)  # ~1M/1Q/1Y horizons

_MIN_GROUP_SIZE_FOR_RANKING = 3


def _commodity_columns(raw_columns) -> list[str]:
    tickers = [sym for sym, _ in D.DEFAULT_TARGET_GROUPS[_COMMODITY_GROUP_NAME_ACCENTED]]
    cleaned = [clean_symbol(t) for t in tickers]
    return [c for c in cleaned if c in raw_columns]


def cross_sectional_momentum_features(
        raw: pd.DataFrame, windows: list[int] = CROSS_SECTIONAL_MOMENTUM_WINDOWS) -> pd.DataFrame:
    """Guida cross-sectional momentum -- percentile RANK of each commodity's
    trailing return against every OTHER commodity in the SAME group, at each
    date and lookback. Restricted to "Matières premières (futures)"
    (~20 tickers, `config.defaults.DEFAULT_TARGET_GROUPS`) -- the only group
    with enough members for a non-degenerate rank:
      - Indices (2 members) / Devises (2) / Crypto (1): ranking 1-2 assets
        against each other either has no meaning (n=1) or collapses to a
        trivial "who's bigger" binary/no-op (n=2) -- not a genuine
        cross-section, would be a degenerate ranking forced for its own
        sake, not a real signal.
      - Macro (FRED): a "cross-sectional momentum" factor compares TRADABLE
        assets of the same kind against each other (that's the economic
        content of the rank); ranking a CPI print against a credit spread
        against a 10Y yield has no momentum interpretation -- these are
        different units/economic objects, not substitutable positions in a
        portfolio.

    ESTIMATED (`_estimated` suffix, task point 9): the true Guida
    construction typically ranks on FUTURES-CURVE-adjusted (roll-adjusted)
    return, not the raw continuous-front-month price series this codebase
    downloads (`data/sources/yfinance_source.py` has no roll-adjustment
    stage) -- a documented approximation, not a hard blocker.

    Requires at least 3 group members present in `raw.columns` (a rank of
    only 1-2 present tickers, e.g. a run with a reduced universe, would be
    just as degenerate as the excluded groups above) -- returns an empty
    DataFrame otherwise."""
    cols = _commodity_columns(raw.columns)
    if len(cols) < _MIN_GROUP_SIZE_FOR_RANKING:
        return pd.DataFrame(index=raw.index)
    out = {}
    for w in windows:
        rets = raw[cols].apply(lambda s: safe_pct_change(s, w))
        pct_rank = rets.rank(axis=1, pct=True)
        for c in cols:
            out[f"{c}_xsect_mom_{w}d_estimated"] = pct_rank[c]
    return pd.DataFrame(out, index=raw.index)


# ---------------------------------------------------------------------------
# 8. Idiosyncratic volatility -- per-group composite factor, ESTIMATED.
# ---------------------------------------------------------------------------

IDIO_VOL_WINDOW = 252  # one Guida lookback (~1 trading year): enough points
# for a stable rolling regression (>>2 degrees of freedom) while staying
# responsive -- a defensible pick among the 14, not the only one.

# Same n>=3 reasoning as cross-sectional momentum: Indices/Devises (2
# members)/Crypto (1) would make the leave-one-out "market factor" either
# undefined (n=1: no "other" members left) or literally just the OTHER
# single member relabeled as a factor (n=2) -- not a genuine composite
# index, so idiosyncratic vol is only built for groups with >=3 members.
GUIDA_IDIO_VOL_GROUPS: tuple[str, ...] = (_COMMODITY_GROUP_NAME_ACCENTED, "Macro (FRED)")

_GROUP_LABELS = {
    _COMMODITY_GROUP_NAME_ACCENTED: "commo",
    "Macro (FRED)": "macro",
}


def idiosyncratic_volatility_for_group(raw: pd.DataFrame, tickers: list[str], window: int,
                                        label: str) -> pd.DataFrame:
    """Residual (annualized) rolling vol of each member's return against a
    LEAVE-ONE-OUT equal-weighted factor built from the OTHER members of its
    own group (excludes the asset itself -- deliberately, to avoid the
    mechanical self-correlation that a factor INCLUDING the asset would
    introduce, especially material for small groups like these; this is the
    method-defining choice documented at module level for this "ESTIMATED"
    family: a proper risk-model factor (PCA, sector index, etc.) would be
    the non-estimated equivalent, out of scope here).

    Residual computed via `rolling_ols_residual_std` (closed-form OLS, no
    DL). Annualized (`sqrt(252)`) like the other vol proxies in this
    codebase (e.g. `vol_models.heston_proxy_features`).

    Returns an empty DataFrame if fewer than 3 `tickers` are present in
    `raw.columns` (see module docstring: a 1-2 member "group" cannot support
    a meaningful leave-one-out factor)."""
    present = [t for t in tickers if t in raw.columns]
    if len(present) < _MIN_GROUP_SIZE_FOR_RANKING:
        return pd.DataFrame(index=raw.index)
    rets = {t: safe_pct_change(raw[t]) for t in present}
    out = {}
    for t in present:
        others = [rets[o] for o in present if o != t]
        factor = pd.concat(others, axis=1).mean(axis=1)
        resid_std = rolling_ols_residual_std(rets[t], factor, window) * _ANNUALIZE
        out[f"{t}_idio_vol_{label}_{window}d_estimated"] = resid_std
    return pd.DataFrame(out, index=raw.index)


def idiosyncratic_volatility_features(raw: pd.DataFrame, window: int = IDIO_VOL_WINDOW) -> pd.DataFrame:
    """Assembles `idiosyncratic_volatility_for_group` over
    `GUIDA_IDIO_VOL_GROUPS` (commodities + macro -- see their docstrings for
    why Indices/Devises/Crypto are excluded)."""
    parts = []
    for group_name in GUIDA_IDIO_VOL_GROUPS:
        tickers = [clean_symbol(sym) for sym, _ in D.DEFAULT_TARGET_GROUPS[group_name]]
        parts.append(idiosyncratic_volatility_for_group(
            raw, tickers, window, label=_GROUP_LABELS[group_name]))
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(index=raw.index)
    return pd.concat(parts, axis=1)


# ---------------------------------------------------------------------------
# Assembly -- called from `pipeline/engine.py::build_base_feature_pool` when
# `config.features.enable_guida_features` is True.
# ---------------------------------------------------------------------------

def build_guida_estimated_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Every "estimated" Guida family, concatenated into one pool. Basis
    momentum and open-interest moving averages contribute NOTHING (see
    module docstring: hard data constraints, not implemented)."""
    parts = [
        eurusd_carry_features(raw),
        cross_sectional_momentum_features(raw),
        idiosyncratic_volatility_features(raw),
    ]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(index=raw.index)
    pool = pd.concat(parts, axis=1)
    return pool.loc[:, ~pool.columns.duplicated()]
