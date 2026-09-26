"""Replaying the models' signals on a patrimoine (roadmap bloc 4: "extend
/simulate to the patrimoine").

For every quoted position of an account, the most recent completed
walk-forward run on that symbol (as target) and its winning trial are
looked up; the per-asset simulation (`simulate.engine.simulate`, one
statistical segment, holdout by default) turns its recorded signals into
an equity curve. The account-level curve is the value-weighted sum of the
per-asset curves -- weights frozen at today's holdings, no rebalancing:
"what if each position had followed its model instead of being held".

Honesty rules:
- positions without a model (no run, no winning trial, no prediction in
  the segment) are listed with the reason and left out of both curves --
  the covered weight is reported, never silently renormalised away;
- each per-asset simulation is logged like any /simulate call
  (`save_simulation`): it is one more configuration tried on that target
  and counts in every later deflated Sharpe;
- the default segment is the holdout; `test` is available but carries
  the engine's selection-bias warning.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from patrick.config import defaults as D
from patrick.simulate import engine as sim_engine
from patrick.tracking import db as trackdb


def _winning_trial(conn: sqlite3.Connection, symbol: str) -> tuple[str, int, int] | None:
    """(run_id, trial_id, horizon) of the most recent completed run on
    `symbol` that has a winning trial -- never at a descriptive horizon
    (`D.DESCRIPTIVE_HORIZONS`, 504/756 days: not a portfolio signal)."""
    descriptive = sorted(D.DESCRIPTIVE_HORIZONS)
    row = conn.execute(
        "SELECT run.run_id, trial.trial_id, run.horizon FROM run "
        "JOIN trial ON trial.run_id = run.run_id AND trial.is_best = 1 "
        f"WHERE run.target = ? AND run.status = 'done' "
        f"AND run.horizon NOT IN ({','.join('?' for _ in descriptive)}) "
        "ORDER BY run.started_at DESC, run.rowid DESC LIMIT 1", (symbol, *descriptive)).fetchone()
    return (row[0], int(row[1]), int(row[2])) if row else None


def _curve(points: list[dict]) -> pd.Series:
    if not points:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(p["t"]): p["v"] for p in points if p["v"] is not None}, dtype=float)
    return s.sort_index()


def replay_account(holdings: dict, params: sim_engine.SimParams, segment: str | None = "holdout",
                   db_path: str | None = None, store_root: str | None = None, save: bool = True) -> dict:
    total = holdings["total"] or 0.0
    covered, skipped, curves, bh_curves = [], [], {}, {}
    conn = trackdb.connect(db_path)
    try:
        for row in holdings["rows"]:
            sym, weight = row["symbol"], (row["value"] / total if total else 0.0)
            if row["is_term_deposit"]:
                skipped.append({"symbol": sym, "weight": weight, "reason": "dépôt à terme (pas de signal)"})
                continue
            found = _winning_trial(conn, sym)
            if found is None:
                skipped.append({"symbol": sym, "weight": weight, "reason": "aucun run terminé sur ce symbole"})
                continue
            run_id, trial_id, horizon = found
            try:
                res = sim_engine.simulate(trial_id, params, db_path=db_path, store_root=store_root, segment=segment)
            except (ValueError, FileNotFoundError) as exc:
                skipped.append({"symbol": sym, "weight": weight, "reason": str(exc)[:160]})
                continue
            if not res.get("ok", True) or not res.get("equity_curve"):
                skipped.append({"symbol": sym, "weight": weight,
                                "reason": res.get("message") or "aucun signal dans ce segment"})
                continue
            if save:
                sim_engine.save_simulation(conn, trial_id, params, res)
            curves[sym] = _curve(res["equity_curve"])
            bh_curves[sym] = _curve(res["buy_and_hold_curve"])
            covered.append({"symbol": sym, "weight": weight, "run_id": run_id, "trial_id": trial_id,
                            "horizon": horizon, "segment": res.get("segment"),
                            "segment_warning": res.get("segment_warning"), "n_signals": res.get("n_signals"),
                            "strategy_return": float(curves[sym].iloc[-1] / curves[sym].iloc[0] - 1.0),
                            "buy_and_hold_return": float(bh_curves[sym].iloc[-1] / bh_curves[sym].iloc[0] - 1.0),
                            "deflated_sharpe": (res.get("strategy") or {}).get("deflated_sharpe")})
    finally:
        conn.close()

    covered_weight = float(sum(c["weight"] for c in covered))
    out = {"covered": covered, "skipped": skipped, "covered_weight": covered_weight,
           "portfolio": [], "portfolio_buy_and_hold": [], "strategy_return": None, "buy_and_hold_return": None,
           "max_drawdown": None, "segment": segment}
    if not covered:
        return out
    # Common window: every covered asset has a curve there (inner join).
    frame = pd.DataFrame({s: c / c.iloc[0] for s, c in curves.items()}).dropna()
    bh = pd.DataFrame({s: c / c.iloc[0] for s, c in bh_curves.items()}).reindex(frame.index).ffill().dropna()
    frame = frame.loc[bh.index]
    if frame.empty:
        out["skipped"].append({"symbol": "—", "weight": 0.0, "reason": "aucune fenêtre commune entre les actifs"})
        return out
    w = np.array([next(c["weight"] for c in covered if c["symbol"] == s) for s in frame.columns])
    w = w / w.sum()
    port = (frame / frame.iloc[0]).to_numpy() @ w
    port_bh = (bh / bh.iloc[0]).to_numpy() @ w
    port_s = pd.Series(port, index=frame.index)
    out.update({
        "portfolio": [{"t": d.date().isoformat(), "v": round(float(v), 6)} for d, v in port_s.items()],
        "portfolio_buy_and_hold": [{"t": d.date().isoformat(), "v": round(float(v), 6)}
                                   for d, v in zip(frame.index, port_bh, strict=True)],
        "strategy_return": float(port[-1] - 1.0),
        "buy_and_hold_return": float(port_bh[-1] - 1.0),
        "max_drawdown": float((port_s / port_s.cummax() - 1.0).min()),
        "window": [frame.index[0].date().isoformat(), frame.index[-1].date().isoformat()],
    })
    return out
