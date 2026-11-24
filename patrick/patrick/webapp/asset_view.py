"""Fiche d'un actif (`/targets/{symbol}`) : ce qui l'entoure et qui ne dépend d'aucun run -- sa classe et son groupe, son historique,
ses voisins du groupe, les stratégies du fonds qui l'ont traité, ses champions. Lectures légères (aucune cotation, aucun calcul de
modèle) : la fiche s'ouvre avec elles, le reste (cours, signaux, actualités) arrive en fragments."""
from __future__ import annotations

import sqlite3
from datetime import date

from patrick.config import asset_classes, equity_context
from patrick.config.equity_universe import is_equity_symbol
from patrick.tracking import champions as trackchampions
from patrick.tracking import data_health

PEERS_LIMIT = 14


def locate(symbol: str, groups: dict[str, list[tuple[str, str]]]) -> tuple[str | None, str | None]:
    """`(groupe, classe)` de l'actif dans le catalogue des cibles (`forms.TARGET_GROUPS`), ou `(None, None)`."""
    for group, items in groups.items():
        if any(sym == symbol for sym, *_ in items):
            return group, asset_classes.class_of_group(group)
    return None, None


def peers(symbol: str, group: str | None, groups: dict[str, list[tuple[str, str]]], limit: int = PEERS_LIMIT) -> list[str]:
    """Les voisins de `symbol` dans son groupe, autour de lui (le précédent et le suivant d'abord) : de quoi passer d'une fiche à l'autre."""
    if group is None or group not in groups:
        return []
    symbols = [sym for sym, *_ in groups[group]]
    if symbol not in symbols or len(symbols) <= 1:
        return []
    i = symbols.index(symbol)
    ordered = sorted((s for s in symbols if s != symbol), key=lambda s: abs(symbols.index(s) - i))
    return sorted(ordered[:limit], key=symbols.index)


def history(symbol: str, today: date | None = None) -> dict:
    """`{first, years}` : première date connue (données ingérées, sinon première cotation vérifiée) et ancienneté en années."""
    first = data_health.depth_by_symbol_for_form().get(symbol)
    if not first:
        return {"first": None, "years": None}
    return {"first": first, "years": data_health.years_available(first, today)}


def fund_usage(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    """Stratégies du fonds qui ont passé au moins un ordre sur `symbol` : `{strategy_id, name, wrapper, n_orders, last_order, kinds}`."""
    rows = conn.execute(
        "SELECT s.strategy_id, s.name, s.wrapper, COUNT(*), MAX(o.ts), GROUP_CONCAT(DISTINCT o.instrument_kind) "
        "FROM fund_order o JOIN fund_strategy s ON s.strategy_id = o.strategy_id "
        "WHERE o.symbol = ? AND s.archived = 0 GROUP BY s.strategy_id, s.name, s.wrapper ORDER BY MAX(o.ts) DESC", (symbol,)).fetchall()
    return [{"strategy_id": r[0], "name": r[1], "wrapper": r[2], "n_orders": r[3], "last_order": str(r[4])[:10],
             "kinds": sorted((r[5] or "").split(","))} for r in rows]


def champions_by_horizon(conn: sqlite3.Connection, symbol: str) -> dict[int, dict]:
    """Le champion de chaque horizon de `symbol` : `{horizon: {run_id, algo, n_features, holdout_panel, promoted_at}}`."""
    mine = [c for c in trackchampions.list_champions(conn) if c["target"] == symbol]
    panels = trackchampions.holdout_panels(conn, [c["trial_id"] for c in mine])
    return {c["horizon"]: {**c, "holdout_panel": panels.get(c["trial_id"])} for c in mine}


def value_champions(conn: sqlite3.Connection, symbol: str) -> dict[int, dict]:
    """Les champions « valeur exacte » de `symbol` (étiquette `symbole__val`) et leur dernière prévision live :
    `{horizon: {run_id, algo, y_value, p_up, ts, ic}}` -- `y_value` = rendement prévu à l'horizon, `ic` = IC du contrôle final."""
    from patrick.config.target_label import run_label

    label = run_label(symbol, task="value")
    out: dict[int, dict] = {}
    for c in trackchampions.list_champions(conn):
        if c["target"] != label:
            continue
        row = conn.execute("SELECT ts, y_value, p_up FROM prediction WHERE trial_id = ? AND split = 'live' AND y_value IS NOT NULL "
                           "ORDER BY ts DESC LIMIT 1", (c["trial_id"],)).fetchone()
        ic = conn.execute("SELECT AVG(value) FROM fold_metric WHERE trial_id = ? AND split = 'holdout' AND metric = 'IC'",
                          (c["trial_id"],)).fetchone()
        out[int(c["horizon"])] = {"run_id": c["run_id"], "algo": c["algo"], "ts": row[0] if row else None,
                                  "y_value": row[1] if row else None, "p_up": row[2] if row else None,
                                  "ic": ic[0] if ic and ic[0] is not None else None}
    return out


def market_context(symbol: str) -> dict | None:
    """Le contexte de marché des features d'une action (`config/equity_context.py`) : indice de sa place, référence mondiale, composite
    zone euro et région. `None` pour tout autre actif."""
    if not is_equity_symbol(symbol):
        return None
    euro = equity_context.uses_euro_composite(symbol)
    return {"region": equity_context.region_of(symbol), "home_index": equity_context.home_index(symbol),
            "benchmark": equity_context.GLOBAL_BENCHMARK, "euro_members": list(equity_context.EURO_COMPOSITE) if euro else []}
