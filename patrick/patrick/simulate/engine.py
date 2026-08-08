"""Investment simulator (Phase 4) -- v1 single-asset.

Non-negotiable constraints from the plan, applied here:
- NEVER re-runs a model: reads only `prediction` (test/holdout/live split) +
  the immutable raw data of the snapshot associated with the run (to compute
  the underlying asset's realized return -- a data load, not an inference).
- explicit execution timing (correction report, C6 -- replaces the
  `open_next` convention from the phase-4 plan, never implementable here: the
  simulator only models a close-to-close series, no per-asset open/high/low):
  only `execution_lag_bars` drives timing, and that is all it does. Actual
  convention (`_build_exposure`): the signal is known at the close of day
  `t`; the exposure starts at row `t + execution_lag_bars` of the daily
  grid; since `underlying_ret[i] = close[i]/close[i-1] - 1` (the return that
  ENDS on day i), the FIRST return captured is that of `t+lag-1` to `t+lag`.
  With the enforced minimum `execution_lag_bars=1`, this first captured
  return is therefore exactly the one from `t` to `t+1` -- the move that
  immediately follows the signal's close, with no additional real latency.
  `execution_lag_bars=0` is structurally forbidden (`SimParams.
  __post_init__`, anti-pattern #5 of the plan): it would capture the return
  from `t-1` to `t`, already known at the moment the signal is computed,
  i.e. pure look-ahead. Revisits F.2 (audit report, "lag=0 gives a lower
  Sharpe than lag=1", unresolved): an oracle signal (perfect prediction of
  the `t`->`t+1` move) confirms this is NOT an alignment bug -- lag=1
  captures exactly what the oracle predicts (Sharpe ~6, near-perfect on
  synthetic series), lag=0/2/3 capture a return unrelated to the prediction
  (Sharpe close to 0, never negative or abnormal). `_build_exposure` works
  as expected; the diagnostic script was not kept in the repo (one-off
  measurement, like D2).
- overlapping horizons explicitly resolved: `overlap_mode` "tranches"
  (average of active signals, default) or "renewed" (single position
  renewed), never an implicit choice.

`y_proba` in the database is the model's confidence in ITS predicted class
(top-1, 4 classes DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT -- see
features/target.py), not directly P(up). Documented choice (minor detail
left to my judgment, see phase report): `_directional_score` converts it to
a [0,1] "P(up)"-style score by returning the confidence when the predicted
class is bullish, and its complement otherwise.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.simulate import metrics as simmetrics
from patrick.tracking import db as trackdb
from patrick.validation.dsr import deflated_sharpe_ratio

_UP_CLASSES = (2, 3)
_DOWN_CLASSES = (0, 1)

ASSET_CLASS_FRICTION_BPS = {
    "futures_liquid": 1.0,
    "us_large_cap": 3.0,
    "eu_mid_cap": 15.0,
    "crypto_non_major": 30.0,
}


@dataclass
class SimParams:
    position_mode: str = "threshold"  # threshold | proportional | heuristic_leverage
    threshold: float = 0.55
    kelly_fraction: float = 0.5  # Leverage fraction (heuristic, not Kelly formula)
    max_leverage: float = 1.0
    max_position: float = 1.0
    short_allowed: bool = True
    execution_lag_bars: int = 1
    overlap_mode: str = "tranches"  # tranches | renewed
    spread_bps: float = 0.0
    commission_bps: float = 0.0
    carry_bps_per_year: float = 0.0
    asset_class: str | None = None  # if provided, prefills spread+commission (see ASSET_CLASS_FRICTION_BPS)

    def __post_init__(self) -> None:
        if self.execution_lag_bars < 1:
            raise ValueError("execution_lag_bars must be >= 1: executing on the signal's own "
                              "bar (anti-pattern #5 of the plan) is structurally forbidden.")
        if self.asset_class and self.asset_class in ASSET_CLASS_FRICTION_BPS:
            total = ASSET_CLASS_FRICTION_BPS[self.asset_class]
            if self.spread_bps == 0.0 and self.commission_bps == 0.0:
                self.spread_bps, self.commission_bps = total / 2, total / 2

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _directional_score(y_pred: np.ndarray, y_proba: np.ndarray) -> np.ndarray:
    up = np.isin(y_pred, _UP_CLASSES)
    score = np.where(up, y_proba, 1.0 - y_proba)
    return np.nan_to_num(score, nan=0.5)


def _position_from_score(score: np.ndarray, params: SimParams) -> np.ndarray:
    if params.position_mode == "threshold":
        pos = np.zeros_like(score)
        pos[score >= params.threshold] = 1.0
        pos[score <= 1 - params.threshold] = -1.0
    elif params.position_mode == "proportional":
        pos = np.clip((score - 0.5) * 2, -1.0, 1.0)
    elif params.position_mode == "heuristic_leverage":
        # Heuristic leverage (not true Kelly formula, which is f*=edge/odds in discrete
        # or f*=μ/σ² in continuous). This linear approximation ignores volatility.
        pos = params.kelly_fraction * (2 * score - 1)
    else:
        raise ValueError(f"unknown position_mode: {params.position_mode}")

    pos = pos * params.max_leverage
    if not params.short_allowed:
        pos = np.clip(pos, 0.0, params.max_position)
    else:
        pos = np.clip(pos, -params.max_position, params.max_position)
    return pos


def _brier_score(y_true_binary: np.ndarray, score: np.ndarray) -> float:
    return float(np.mean((score - y_true_binary) ** 2))


def check_leverage_available(conn: sqlite3.Connection, trial_id: int, min_obs: int = 30) -> tuple[bool, str]:
    """Heuristic allocation is only enabled if a calibration curve (proxy here:
    a Brier score better than a coin flip on the binarized problem, 0.25)
    holds on the test fold -- otherwise disabled with an explanatory message
    (Phase 4.1), never silently approximated.

    DISCLAIMER: this allocation is a heuristic (`leverage = kelly_frac * (2*score - 1)`),
    not a true Kelly formula (which is f*=edge/odds in discrete or f*=μ/σ² in continuous).
    It ignores the signal's volatility and can over/under-size relative to the real variance."""
    rows = conn.execute(
        "SELECT y_pred, y_proba, y_true FROM prediction "
        "WHERE trial_id = ? AND split = 'test' AND y_proba IS NOT NULL AND y_true IS NOT NULL",
        (trial_id,),
    ).fetchall()
    if len(rows) < min_obs:
        return False, f"Heuristic allocation disabled: only {len(rows)} test observations with proba (min {min_obs})."
    y_pred = np.array([r[0] for r in rows])
    y_proba = np.array([r[1] for r in rows])
    y_true = np.array([r[2] for r in rows])
    score = _directional_score(y_pred, y_proba)
    y_true_binary = np.isin(y_true, _UP_CLASSES).astype(float)
    brier = _brier_score(y_true_binary, score)
    if brier >= 0.25:
        return False, f"Heuristic allocation disabled: Brier score {brier:.3f} >= 0.25 (no better than a coin flip)."
    return True, f"Heuristic allocation enabled (Brier score {brier:.3f} on {len(rows)} test obs.)."


def _load_predictions(conn: sqlite3.Connection, trial_id: int) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT ts, y_pred, y_proba FROM prediction "
        "WHERE trial_id = ? AND split IN ('test', 'holdout', 'live') AND y_proba IS NOT NULL "
        "ORDER BY ts",
        (trial_id,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["ts", "y_pred", "y_proba"])
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def _build_exposure(signal_dates: pd.DatetimeIndex, target_pos: np.ndarray,
                     daily_index: pd.DatetimeIndex, horizon: int, params: SimParams) -> pd.Series:
    """Places each signal on the daily grid at `entry_idx = signal position +
    execution_lag_bars` (never earlier, see `SimParams.__post_init__`); the
    first return captured at this entry is `underlying_ret[entry_idx]`, i.e.
    the close-to-close return from `entry_idx-1` to `entry_idx` (see detailed
    convention, module docstring, correction report C6) -- then resolves
    overlapping horizons (Phase 4, non-negotiable constraint): "tranches"
    averages the active signals over [entry, entry+H), "renewed" holds the
    last signal until the next one."""
    n = len(daily_index)
    date_to_idx = {d: i for i, d in enumerate(daily_index)}
    entry_idxs = []
    for d in signal_dates:
        pos_in_index = daily_index.searchsorted(d)
        entry_idx = pos_in_index + params.execution_lag_bars
        entry_idxs.append(entry_idx if entry_idx < n else None)

    if params.overlap_mode == "tranches":
        accum = np.zeros(n)
        count = np.zeros(n)
        for entry_idx, pos in zip(entry_idxs, target_pos):
            if entry_idx is None:
                continue
            end_idx = min(entry_idx + horizon, n)
            accum[entry_idx:end_idx] += pos
            count[entry_idx:end_idx] += 1
        exposure = np.divide(accum, count, out=np.zeros(n), where=count > 0)
    elif params.overlap_mode == "renewed":
        sparse = pd.Series(np.nan, index=daily_index)
        for entry_idx, pos in zip(entry_idxs, target_pos):
            if entry_idx is not None:
                sparse.iloc[entry_idx] = pos
        exposure = sparse.ffill().fillna(0.0).values
    else:
        raise ValueError(f"unknown overlap_mode: {params.overlap_mode}")

    return pd.Series(exposure, index=daily_index)


def solve_break_even_cost_bps(gross_returns: pd.Series, turnover: pd.Series,
                               hard_ceiling_bps: float = 1000.0) -> float:
    """Cost (spread+commission) per unit of turnover, in bps, that brings the
    total COMPOUNDED return to zero. `gross_returns`: return per period net
    of carry but before transaction cost (`exposure * underlying_ret -
    carry_cost`). `turnover`: |Δexposure| per period, aligned with
    `gross_returns`.

    Numerical solve (`brentq`), not a linear division: transaction costs
    apply period by period on an equity that COMPOUNDS (`cumprod`), so
    `total_gross_return / total_turnover` strongly underestimates the real
    cost as soon as the position is held over multiple periods (see audit
    report, section F.3 -- exact reconciliation verified by
    `tests/test_simulate.py::test_break_even_cost_reconciles_...`).
    """
    total_turnover = float(turnover.sum())
    if total_turnover <= 1e-9:
        return float("nan")

    gross_arr = gross_returns.values
    turn_arr = turnover.values

    def net_total_return(c: float) -> float:
        # Clip to 1e-9 (not 0/negative): once equity has "gone bust" on a
        # period, a higher cost cannot dig an already-zero factor any deeper --
        # without this clip, `cumprod` could flip sign and break the decreasing
        # monotonicity that `brentq` assumes.
        factors = np.clip(1.0 + gross_arr - turn_arr * c, 1e-9, None)
        return float(np.prod(factors) - 1.0)

    gross_total_return = net_total_return(0.0)
    if gross_total_return <= 0.0:
        return 0.0

    hard_ceiling = hard_ceiling_bps / 10000.0
    c_hi = 1e-4  # 1 bp in decimal
    while net_total_return(c_hi) > 0.0 and c_hi < hard_ceiling:
        c_hi *= 2
    c_hi = min(c_hi, hard_ceiling)

    if net_total_return(c_hi) > 0.0:
        warnings.warn(
            f"break_even_cost_bps: return still positive at the hard ceiling of "
            f"{hard_ceiling_bps:.0f} bps -- no sign change found, "
            "break-even cost is undetermined.", stacklevel=2)
        return float("nan")

    c_star = brentq(net_total_return, 0.0, c_hi, xtol=1e-14, rtol=1e-12)
    return c_star * 10000.0


def simulate(trial_id: int, params: SimParams, db_path: str | None = None,
             store_root: str | None = None) -> dict:
    conn = trackdb.connect(db_path)
    try:
        trial_row = conn.execute(
            "SELECT run_id FROM trial WHERE trial_id = ?", (trial_id,)).fetchone()
        if trial_row is None:
            raise ValueError(f"Trial not found: {trial_id}")
        run = trackdb.get_run(conn, trial_row[0])
        if run is None:
            raise ValueError(f"Run not found for trial {trial_id}")

        kelly_ok, kelly_message = (True, None)
        if params.position_mode == "heuristic_leverage":
            kelly_ok, kelly_message = check_leverage_available(conn, trial_id)
            if not kelly_ok:
                return {"ok": False, "message": kelly_message, "params": params.to_dict()}

        pred_df = _load_predictions(conn, trial_id)
        if len(pred_df) < 10:
            return {"ok": False, "message": "Not enough predictions (test/holdout/live) to simulate "
                                             f"(found {len(pred_df)}, minimum 10).", "params": params.to_dict()}

        store = DataStore(root=store_root) if store_root else DataStore()
        raw = store.load(f"raw_{run['target']}", snapshot_id=run["snapshot_id"])
        target_col = clean_symbol(run["target"])
        underlying = raw[target_col].ffill().dropna()

        daily_index = underlying.index[
            (underlying.index >= pred_df["ts"].min()) & (underlying.index <= underlying.index[-1])]
        underlying = underlying.reindex(daily_index)
        underlying_ret = underlying.pct_change().fillna(0.0)

        score = _directional_score(pred_df["y_pred"].values, pred_df["y_proba"].values)
        target_pos = _position_from_score(score, params)
        exposure = _build_exposure(pred_df["ts"], target_pos, daily_index, run["horizon"], params)

        turnover = exposure.diff().abs().fillna(exposure.abs())
        trading_cost = turnover * (params.spread_bps + params.commission_bps) / 10000.0
        carry_cost = exposure.abs() * (params.carry_bps_per_year / 10000.0) / simmetrics.TRADING_DAYS_PER_YEAR
        strategy_returns = exposure * underlying_ret - trading_cost - carry_cost
        gross_returns = exposure * underlying_ret - carry_cost

        equity = (1 + strategy_returns).cumprod()
        gross_equity = (1 + gross_returns).cumprod()
        bh_equity = (1 + underlying_ret).cumprod()

        strat_summary = simmetrics.performance_summary(equity, strategy_returns, exposure)
        bh_exposure = pd.Series(1.0, index=daily_index)
        bh_summary = simmetrics.performance_summary(bh_equity, underlying_ret, bh_exposure)

        annual_turnover = float(turnover.sum() / max(len(daily_index) / simmetrics.TRADING_DAYS_PER_YEAR, 1e-9))

        # Per-trade returns: a trade = a contiguous non-zero exposure segment
        # (entry -> exit), compounded return over that segment.
        trade_returns = _trade_returns(exposure, strategy_returns)
        strat_summary["turnover_annualized"] = annual_turnover
        strat_summary["hit_rate"] = simmetrics.hit_rate(trade_returns)
        strat_summary["profit_factor"] = simmetrics.profit_factor(trade_returns)

        break_even_bps = solve_break_even_cost_bps(gross_returns, turnover)
        strat_summary["break_even_cost_bps"] = break_even_bps

        n_configs = count_simulations_for_target(conn, run["target"])
        dsr = deflated_sharpe_ratio(strategy_returns.values, n_trials=max(n_configs, 1))
        strat_summary["deflated_sharpe"] = dsr["dsr"]
        strat_summary["sharpe_p_value"] = dsr["p_value"]

        result = {
            "ok": True,
            "message": kelly_message,
            "params": params.to_dict(),
            "n_days": len(daily_index),
            "n_signals": len(pred_df),
            "strategy": strat_summary,
            "buy_and_hold": bh_summary,
            "n_simulation_configs_on_target": n_configs + 1,  # +1: this one counts too
            "equity_curve": _series_to_points(equity),
            "buy_and_hold_curve": _series_to_points(bh_equity),
            "drawdown_curve": _series_to_points(equity / equity.cummax() - 1),
            "trade_returns": [round(float(r), 6) for r in trade_returns],
        }
        return _to_json_safe(result)
    finally:
        conn.close()


def _to_json_safe(obj):
    """NaN/Inf -> None: `json.dumps` accepts them by default (`allow_nan=True`,
    a non-standard extension) but the browser's `JSON.parse` rejects them --
    undefined metrics (e.g. Sharpe on too few observations) must never crash
    the page render, they should just display as "-"."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    if isinstance(obj, np.generic):
        return _to_json_safe(obj.item())
    return obj


def _trade_returns(exposure: pd.Series, strategy_returns: pd.Series) -> pd.Series:
    is_open = exposure.abs() > 1e-9
    segment_id = (is_open != is_open.shift(1)).cumsum()
    out = []
    for seg, group in strategy_returns.groupby(segment_id):
        if not is_open.loc[group.index[0]]:
            continue
        out.append(float((1 + group).prod() - 1))
    return pd.Series(out)


def _series_to_points(s: pd.Series) -> list[dict]:
    return [{"t": ts.strftime("%Y-%m-%d"), "v": None if pd.isna(v) else round(float(v), 6)}
            for ts, v in s.items()]


def save_simulation(conn: sqlite3.Connection, trial_id: int, params: SimParams, result: dict) -> str:
    simulation_id = uuid.uuid4().hex[:12]
    with conn:
        conn.execute(
            "INSERT INTO simulation (simulation_id, trial_id, params_json, metrics_json, error) "
            "VALUES (?, ?, ?, ?, ?)",
            (simulation_id, trial_id, json.dumps(params.to_dict()),
             json.dumps(result) if result.get("ok") else None,
             None if result.get("ok") else result.get("message")),
        )
    return simulation_id


def count_simulations_for_target(conn: sqlite3.Connection, target: str) -> int:
    """Number of simulations already recorded for this target, across all
    runs/trials (Phase 4.5, anti-overfitting guard) -- symmetric to
    `tracking.stats.count_cumulative_trials`."""
    row = conn.execute(
        "SELECT COUNT(*) FROM simulation "
        "JOIN trial ON simulation.trial_id = trial.trial_id "
        "JOIN run ON trial.run_id = run.run_id "
        "WHERE run.target = ?",
        (target,),
    ).fetchone()
    return int(row[0]) if row else 0
