"""Page-level aggregation for /patrimoine and /mouvements: one call per
page, pure functions of (connection, price provider) so the web layer
stays thin and tests can pass a dict provider."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from patrick.wealth import ledger, performance


def account_detail(conn: sqlite3.Connection, account_id: str, prices) -> dict | None:
    account = ledger.get_account(conn, account_id)
    if account is None:
        return None
    movements = ledger.list_movements(conn, account_id)
    holdings = performance.holdings_table(movements, prices, account=account)
    perf = performance.performance_summary(movements, prices, benchmark=account["benchmark"])
    risk = performance.ex_ante_risk(holdings, prices)
    return {"account": account, "movements": movements, "holdings": holdings, "performance": perf, "risk": risk}


def _series_points(s: pd.Series | None) -> list[dict]:
    if s is None or len(s) == 0:
        return []
    s = s.dropna()
    return [{"t": d.date().isoformat(), "v": round(float(v), 4)} for d, v in s.items() if np.isfinite(v)]


def chart_payload(detail: dict) -> dict:
    perf = detail["performance"]
    val = perf.get("valuation")
    return {
        "value": _series_points(val["value"]) if val is not None and len(val) else [],
        "net_invested": _series_points(val["flow"].cumsum()) if val is not None and len(val) else [],
        "benchmark_replica": _series_points(perf.get("benchmark_replica")),
        "benchmark": perf.get("benchmark"),
    }


def overview(conn: sqlite3.Connection, prices) -> dict:
    """Every account (real and fictive), totals per mode, consolidated real
    holdings (weights over the real patrimoine) and ex-ante risk of the
    real patrimoine as a whole."""
    accounts = []
    totals = {"real": 0.0, "fictive": 0.0}
    consolidated: dict[str, dict] = {}
    real_movements: list[dict] = []
    all_warnings: list[str] = []
    for acc in ledger.list_accounts(conn):
        detail = account_detail(conn, acc["account_id"], prices)
        h, perf = detail["holdings"], detail["performance"]
        totals[acc["mode"]] += h["total"]
        all_warnings.extend(f"{acc['name']} — {w}" for w in h["warnings"])
        accounts.append({**acc, "value": h["total"], "cash": h["cash"], "twr": perf.get("twr"),
                         "xirr": perf.get("xirr"), "benchmark_return": perf.get("benchmark_return"),
                         "excess": perf.get("excess_vs_benchmark"), "n_movements": len(detail["movements"]),
                         "volatility": detail["risk"]["volatility"]})
        if acc["mode"] == "real":
            real_movements.extend(detail["movements"])
            for r in h["rows"]:
                c = consolidated.setdefault(r["symbol"], {"symbol": r["symbol"], "quantity": 0.0, "value": 0.0,
                                                          "cost": 0.0, "latent_pnl": 0.0,
                                                          "is_term_deposit": r["is_term_deposit"]})
                c["quantity"] += r["quantity"]
                c["value"] += r["value"]
                c["cost"] += r["cost"]
                c["latent_pnl"] += r["latent_pnl"]
    real_total = totals["real"]
    rows = sorted(consolidated.values(), key=lambda r: -r["value"])
    for r in rows:
        r["weight"] = r["value"] / real_total if real_total else None
    real_cash = sum(a["cash"] for a in accounts if a["mode"] == "real")
    risk = performance.ex_ante_risk({"total": real_total, "rows": rows}, prices) if rows else \
        {"volatility": None, "covered_weight": 0.0, "excluded": [], "shrinkage": None}
    return {"accounts": accounts, "totals": totals, "holdings": rows, "real_cash": real_cash, "risk": risk,
            "warnings": all_warnings}
