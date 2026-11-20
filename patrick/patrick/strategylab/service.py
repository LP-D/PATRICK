"""Études complètes du laboratoire : `run_event` (acheter avant / vendre après) et `run_straddle` (straddle autour des résultats).

Le résultat est un dictionnaire JSON (nombres Python, NaN -> None) relu par la page `/strategies`. Les deux études partagent la même évaluation
(`evaluate_trades`) : mise fixe, courbe de capital, indicateurs, concentration, Monte Carlo d'une campagne, extrêmes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from patrick.placements.service import _num
from patrick.strategylab import core, straddle

Progress = Callable[[float, str], None]


def _groups(table: pd.DataFrame, col: str) -> list[dict]:
    out = []
    for name, sub in table.groupby("group"):
        v = sub[col].dropna().to_numpy(float)
        if len(v):
            out.append({"group": str(name), "n": len(v), "mean": float(v.mean()), "median": float(np.median(v)), "win": float((v > 0).mean())})
    return sorted(out, key=lambda g: -g["n"])


def _equity(table: pd.DataFrame, col: str, stake: float) -> dict:
    sub = table.dropna(subset=[col])
    return {"dates": [d.date().isoformat() for d in sub["day0"]], "pnl": [float(x) for x in np.cumsum(stake * sub[col].to_numpy(float))]}


def evaluate_trades(table: pd.DataFrame, col: str, stake: float) -> dict:
    """Évaluation d'une colonne de rendements (une règle fixée) : indicateurs, capital, concentration, campagne, extrêmes."""
    sub = table.dropna(subset=[col])
    r = sub[col].to_numpy(float)
    return {"metrics": core.trade_metrics(r, stake), "equity": _equity(table, col, stake),
            "concentration": core.concentration(r, sub["symbol"].to_numpy(), sub["day0"].dt.year.to_numpy()),
            "campaign": core.campaign(r, stake), "groups": _groups(table, col)}


def _check(table: pd.DataFrame, skipped: dict, n_in: int) -> None:
    if table.empty:
        reasons = "; ".join(f"{n} {why}" for why, n in skipped.items()) or "aucun événement"
        raise core.StrategyError(f"Aucun événement exploitable sur {n_in} (écartés : {reasons}).")


def run_event(events: pd.DataFrame, source, params: core.EventParams, progress: Progress | None = None) -> dict:
    """Étude « acheter avant / vendre après » : courbe par jour de sortie, bootstrap, validation chronologique, évaluation du meilleur jour."""
    params.validate()
    say = progress or (lambda _f, _m: None)
    K = params.max_exit
    table, skipped = core.build_returns(events, source, params, progress)
    _check(table, skipped, len(events))
    say(0.70, "Courbe par jour de sortie")
    V = core.matrix(table, K)
    C = core.complete_rows(V)
    if len(C) < core.MIN_COMPLETE:
        raise core.StrategyError(f"Seulement {len(C)} événements ont une trajectoire complète sur {K} séances (au moins {core.MIN_COMPLETE} sont nécessaires) : "
                                 "réduisez le jour de sortie maximal ou ajoutez des événements plus anciens.")
    curve = core.curve(V)
    say(0.78, "Bootstrap et stabilité du meilleur jour")
    boot = core.bootstrap(C, params.n_boot, params.seed)
    k = boot["best_k"]
    best = {**curve[k - 1], "k": k, "ci_low": boot["ci_low"][k - 1], "ci_high": boot["ci_high"][k - 1], "n_complete": len(C)}
    say(0.86, "Validation chronologique")
    split = core.split_validation(V, params.split_frac, params.n_boot, params.seed)
    col = f"k{k}"
    detail = evaluate_trades(table, col, params.stake)
    last = core.trade_metrics(table[f"k{K}"].dropna().to_numpy(float), params.stake) if K != k else None
    say(0.95, "Verdict")
    result = {
        "kind": "event", "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "params": {"entry": params.entry, "max_exit": K, "cost_bps": params.cost_bps, "split_frac": params.split_frac, "n_boot": params.n_boot, "stake": params.stake},
        "n_events_in": len(events), "n_events": len(table), "n_complete": len(C), "n_symbols": int(table["symbol"].nunique()),
        "dropped_rows": int(events.attrs.get("dropped", 0)), "failed_symbols": list(events.attrs.get("failed", [])), "skipped": skipped,
        "first_date": table["day0"].min().date().isoformat(), "last_date": table["day0"].max().date().isoformat(),
        "curve": curve, "bootstrap": boot, "best": best, "split": split, "last_metrics": last,
        "extremes": core.extremes(table, k), **detail,
        "verdict": core.verdict(len(C), best, boot, split, detail["concentration"]),
    }
    say(1.0, "Terminé")
    return _num(result)


def run_straddle(events: pd.DataFrame, source, params: straddle.StraddleParams, progress: Progress | None = None) -> dict:
    """Étude « straddle autour d'un événement » : P&L reconstruit, validation chronologique, matrice maturité x écrasement de volatilité."""
    params.validate()
    say = progress or (lambda _f, _m: None)
    table, skipped = straddle.simulate(events, source, params, progress)
    _check(table, skipped, len(events))
    table = table.rename(columns={"ret": "k1"})
    say(0.70, "Évaluation")
    V = table[["k1"]].to_numpy(float)
    if len(V) < core.MIN_COMPLETE:
        raise core.StrategyError(f"Seulement {len(V)} straddles évaluables (au moins {core.MIN_COMPLETE} sont nécessaires).")
    boot = core.bootstrap(V, params.n_boot, params.seed)
    curve = core.curve(V)[0]
    best = {**curve, "k": 1, "ci_low": boot["ci_low"][0], "ci_high": boot["ci_high"][0], "n_complete": len(V)}
    split = core.split_validation(V, params.split_frac, params.n_boot, params.seed)
    detail = evaluate_trades(table, "k1", params.stake)
    say(0.80, "Sensibilité maturité x volatilité de sortie")
    grid = straddle.sensitivity(events, source, params)
    result = {
        "kind": "straddle", "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "params": {k: getattr(params, k) for k in ("maturity_days", "strike_factor", "entry_iv_mult", "exit_iv_ratio", "lookback", "rate", "commission",
                                                   "half_spread", "slippage", "stake", "split_frac", "n_boot")},
        "n_events_in": len(events), "n_events": len(table), "n_symbols": int(table["symbol"].nunique()),
        "dropped_rows": int(events.attrs.get("dropped", 0)), "failed_symbols": list(events.attrs.get("failed", [])), "skipped": skipped,
        "first_date": table["day0"].min().date().isoformat(), "last_date": table["day0"].max().date().isoformat(),
        "cost_per_contract": straddle.trade_cost(params), "mean_premium": float(table["premium"].mean()), "mean_move": float(table["move"].abs().mean()),
        "best": best, "bootstrap": boot, "split": split, "sensitivity": grid, "extremes": core.extremes(table, 1), **detail,
        "verdict": core.verdict(len(V), best, boot, split, detail["concentration"]),
    }
    say(1.0, "Terminé")
    return _num(result)
