"""Fonds : lecture de ce qu'une stratégie a fait, au-delà de sa valeur.

- `attribution` : le P&L par modèle (règle), par classe d'actifs et par sens ;
- `witnesses` : les mêmes ordres rejoués « toujours acheteur » et « à pile ou face » (mêmes dates, mêmes tailles), pour savoir ce que le
  choix du sens par les modèles a apporté ;
- `log_replacement` / `replacements` : le journal des modèles remplacés (leurs ordres sont supprimés, `systematic.purge_rule`).

Lecture seule, sauf `log_replacement` (une ligne de journal).
"""
from __future__ import annotations

import datetime as dt
import random
import sqlite3

from patrick.data.session_calendar import classify_asset_class
from patrick.fund import engine, prices, service, store, systematic

MANUAL = "manual"
COIN_SEEDS = 8               # tirages du témoin « pile ou face » (leur moyenne)


def _rule_of(note: str | None) -> str | None:
    """Identifiant de la règle qui a généré l'ordre (`auto:<règle>:<date>:<action>`), ou `None` pour un ordre saisi à la main."""
    parts = (note or "").split(":")
    return parts[1] if len(parts) >= 4 and parts[0] == systematic.NOTE_PREFIX else None


def _position_rules(orders: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for order in orders:
        rule_id = _rule_of(order.get("note"))
        if rule_id and order["position_id"] not in out:
            out[order["position_id"]] = rule_id
    return out


def _bucket(acc: dict, key, label: str, position: dict) -> None:
    row = acc.setdefault(key, {"key": key, "label": label, "pnl": 0.0, "n": 0, "n_open": 0})
    row["pnl"] += float(position["pnl"] or 0.0)
    row["n"] += 1
    row["n_open"] += int(position["status"] == "open")


def attribution(conn: sqlite3.Connection, strategy_id: str, snapshot: dict) -> dict:
    """`{"by_rule", "by_class", "by_side"}` : listes `{key, label, pnl, n, n_open}` triées par P&L décroissant. `snapshot` : celui de
    `service.strategy_snapshot` (positions et ordres déjà calculés). Une position dont la règle a été supprimée garde son identifiant."""
    rules = {r["rule_id"]: r for r in systematic.list_rules(conn, strategy_id)}
    owner = _position_rules(snapshot["orders"])
    by_rule: dict = {}
    by_class: dict = {}
    by_side: dict = {}
    for position in snapshot["positions"]:
        rule_id = owner.get(position["position_id"])
        if rule_id is None:
            _bucket(by_rule, MANUAL, MANUAL, position)
        else:
            _bucket(by_rule, rule_id, rules[rule_id]["name"] if rule_id in rules else rule_id, position)
        asset_class = classify_asset_class(position["symbol"] or "")
        _bucket(by_class, asset_class, asset_class, position)
        _bucket(by_side, position["side"], position["side"], position)

    def ranked(acc: dict) -> list[dict]:
        return sorted(acc.values(), key=lambda r: -r["pnl"])
    return {"by_rule": ranked(by_rule), "by_class": ranked(by_class), "by_side": ranked(by_side)}


def _with_sides(orders: list[dict], side_of: dict[str, str]) -> list[dict]:
    """Les mêmes ordres, chaque position prenant le sens `side_of[position]`. Une position retournée perd son stop et son objectif
    (posés pour l'autre sens, ils se déclencheraient à l'envers)."""
    out = []
    for order in orders:
        side = side_of.get(order["position_id"], order["side"])
        if side == order["side"]:
            out.append(order)
        else:
            spec = {k: v for k, v in (order.get("spec") or {}).items() if k not in ("stop", "target")}
            out.append({**order, "side": side, "spec": spec})
    return out


def witnesses(conn: sqlite3.Connection, strategy: dict, snapshot: dict, today: dt.date | None = None) -> dict | None:
    """Ce qu'auraient donné les mêmes ordres sans le choix du sens par les modèles : `{"nav", "always_long", "coin_flip", "n_positions"}`
    (valeurs de la stratégie). Seules les positions négociables dans les deux sens (CFD, futures) changent de sens ; une action au
    comptant reste acheteuse. `None` quand la stratégie n'a aucune position qui puisse changer de sens."""
    today = service._today(today)
    orders = snapshot["orders"]
    flippable = sorted({o["position_id"] for o in orders if o.get("instrument_kind") in engine.DERIV_KINDS and o.get("side")})
    if not flippable:
        return None
    market, _ = prices.build_market(conn, orders, strategy["base_currency"])

    def nav(side_of: dict[str, str]) -> float:
        daily = engine.simulate(strategy, _with_sides(orders, side_of), market, end=today).daily
        return float(daily["nav"].iloc[-1]) if len(daily) else float(strategy["initial_capital"])

    always_long = nav(dict.fromkeys(flippable, "long"))
    coins = []
    for seed in range(COIN_SEEDS):
        rng = random.Random(seed)                         # tirage reproductible : la page affiche le même chiffre d'un chargement à l'autre
        coins.append(nav({pid: rng.choice(("long", "short")) for pid in flippable}))
    return {"nav": snapshot["kpis"]["nav"], "always_long": always_long, "coin_flip": sum(coins) / len(coins),
            "n_positions": len(flippable), "n_seeds": COIN_SEEDS}


def rule_pnl(conn: sqlite3.Connection, strategy_id: str, rule_id: str, today: dt.date | None = None) -> float | None:
    """P&L (réalisé + latent, net de frais) des positions d'une règle, ou `None` si la stratégie ne se valorise pas."""
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        return None
    try:
        snapshot = service.strategy_snapshot(conn, strategy, today)
    except Exception:  # noqa: BLE001 -- cotations indisponibles : le journal note le remplacement sans montant
        return None
    owner = _position_rules(snapshot["orders"])
    return sum(float(p["pnl"] or 0.0) for p in snapshot["positions"] if owner.get(p["position_id"]) == rule_id)


def current_drawdown(conn: sqlite3.Connection, strategy: dict, today: dt.date | None = None) -> float | None:
    """Repli actuel de la valeur de la stratégie sous son plus haut (0,10 = 10 % sous le sommet), ou `None` sans historique."""
    today = service._today(today)
    orders = store.list_orders(conn, strategy["strategy_id"])
    if not orders:
        return None
    market, _ = prices.build_market(conn, orders, strategy["base_currency"])
    nav = engine.simulate(strategy, orders, market, end=today).daily["nav"]
    if nav.empty:
        return None
    peak = max(float(nav.max()), float(strategy["initial_capital"]))
    return max(0.0, 1.0 - float(nav.iloc[-1]) / peak) if peak > 0 else None


def log_replacement(conn: sqlite3.Connection, rule: dict, new_trial_id: int, n_orders: int, pnl_removed: float | None) -> bool:
    """Une ligne de journal pour le remplacement du modèle de `rule` (déjà supprimée avec ses ordres). Jamais bloquant : une base pas
    encore migrée (worker démarré avant la mise à jour) laisse le remplacement se faire sans trace."""
    cfg = rule["config"]
    cell = conn.execute("SELECT run.target, run.horizon FROM trial JOIN run ON run.run_id = trial.run_id WHERE trial.trial_id = ?",
                        (cfg.get("trial_id"),)).fetchone()
    target, horizon = cell if cell else ((cfg.get("managed") or {}).get("target"), (cfg.get("managed") or {}).get("horizon"))
    try:
        with conn:
            conn.execute("INSERT INTO fund_replacement (strategy_id, rule_name, target, horizon, old_trial_id, new_trial_id, n_orders, pnl_removed) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (rule["strategy_id"], rule["name"], target, horizon, cfg.get("trial_id"), new_trial_id, n_orders, pnl_removed))
        return True
    except sqlite3.Error:
        return False


def replacements(conn: sqlite3.Connection, strategy_id: str, limit: int = 50) -> list[dict]:
    """Les remplacements de modèle d'une stratégie, le plus récent d'abord."""
    try:
        rows = conn.execute(
            "SELECT rule_name, target, horizon, old_trial_id, new_trial_id, n_orders, pnl_removed, replaced_at FROM fund_replacement "
            "WHERE strategy_id = ? ORDER BY replaced_at DESC, replacement_id DESC LIMIT ?", (strategy_id, limit)).fetchall()
    except sqlite3.Error:
        return []
    keys = ("rule_name", "target", "horizon", "old_trial_id", "new_trial_id", "n_orders", "pnl_removed", "replaced_at")
    return [dict(zip(keys, row)) for row in rows]
