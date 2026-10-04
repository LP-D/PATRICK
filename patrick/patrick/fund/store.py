"""Persistance des stratégies et des ordres (migration 0029). Aucune position
ni aucun solde n'est stocké : tout se recalcule depuis les ordres."""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import uuid

import pandas as pd

from patrick.clock import utc_today
from patrick.wealth.ledger import PEA_DEPOSIT_CAP_EUR

WRAPPERS = ("PEA", "CTO")
ACTIONS = ("open", "increase", "reduce", "close", "modify")
INSTRUMENT_KINDS = ("equity", "etf", "future", "cfd")
_STRATEGY_COLUMNS = ("strategy_id", "name", "wrapper", "base_currency", "initial_capital", "opened_on",
                     "archived", "created_at")
_ORDER_COLUMNS = ("order_id", "strategy_id", "position_id", "ts", "action", "instrument_kind", "symbol", "side",
                  "quantity", "price", "price_source", "currency", "fx_rate", "fees", "fees_source", "fee_seed",
                  "spec_json", "note")


class FundError(ValueError):
    """Entrée invalide (400 à l'API)."""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _iso(value) -> str:
    if not isinstance(value, (str, dt.date)):                # liste, nombre, None : refus lisible, jamais une exception
        raise FundError(f"date invalide : {value!r}")
    try:
        day = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise FundError(f"date invalide : {value!r}") from exc
    if pd.isna(day):
        raise FundError(f"date invalide : {value!r}")
    return day.date().isoformat()


# -------------------------------------------------------------- strategies

def create_strategy(conn: sqlite3.Connection, name: str, wrapper: str, initial_capital, opened_on,
                    base_currency: str = "EUR") -> str:
    if name is not None and not isinstance(name, str):
        raise FundError("nom de stratégie invalide : texte attendu")
    name = (name or "").strip()
    if not name:
        raise FundError("nom de stratégie manquant")
    if wrapper not in WRAPPERS:
        raise FundError(f"enveloppe inconnue : {wrapper!r} ({WRAPPERS})")
    try:
        capital = float(str(initial_capital).replace(",", ".").replace(" ", ""))
    except ValueError as exc:
        raise FundError(f"capital invalide : {initial_capital!r}") from exc
    if not math.isfinite(capital) or capital <= 0:
        raise FundError("le capital doit être strictement positif")
    if wrapper == "PEA" and capital > PEA_DEPOSIT_CAP_EUR:
        raise FundError(f"PEA : capital {capital:,.0f} € > plafond de versements {PEA_DEPOSIT_CAP_EUR:,.0f} €"
                        .replace(",", " "))
    opened = _iso(opened_on)
    if opened > utc_today().isoformat():
        raise FundError("la date d'ouverture ne peut pas être dans le futur")
    strategy_id = new_id("str")
    with conn:
        conn.execute("INSERT INTO fund_strategy (strategy_id, name, wrapper, base_currency, initial_capital, "
                     "opened_on) VALUES (?, ?, ?, ?, ?, ?)",
                     (strategy_id, name[:120], wrapper, (base_currency or "EUR").upper()[:3], capital, opened))
    return strategy_id


def get_strategy(conn: sqlite3.Connection, strategy_id: str) -> dict | None:
    row = conn.execute(f"SELECT {', '.join(_STRATEGY_COLUMNS)} FROM fund_strategy WHERE strategy_id = ?",
                       (strategy_id,)).fetchone()
    return dict(zip(_STRATEGY_COLUMNS, row)) if row else None


def list_strategies(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    sql = f"SELECT {', '.join(_STRATEGY_COLUMNS)} FROM fund_strategy"
    if not include_archived:
        sql += " WHERE archived = 0"
    return [dict(zip(_STRATEGY_COLUMNS, r)) for r in conn.execute(sql + " ORDER BY created_at, rowid")]


def update_strategy(conn: sqlite3.Connection, strategy_id: str, **fields) -> None:
    allowed = {"name", "archived"}
    unknown = set(fields) - allowed
    if unknown:
        raise FundError(f"champ(s) non modifiable(s) : {sorted(unknown)}")
    if "name" in fields:
        if not isinstance(fields["name"], str):
            raise FundError("nom de stratégie invalide : texte attendu")
        if not fields["name"].strip():
            raise FundError("nom de stratégie manquant")
        fields["name"] = fields["name"].strip()[:120]
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE fund_strategy SET {sets} WHERE strategy_id = ?", (*fields.values(), strategy_id))


def delete_strategy(conn: sqlite3.Connection, strategy_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM fund_strategy WHERE strategy_id = ?", (strategy_id,))


# ------------------------------------------------------------------ orders

def _order_row(raw: dict) -> dict:
    out = {k: raw.get(k) for k in _ORDER_COLUMNS if k not in ("order_id", "spec_json")}
    out["spec_json"] = json.dumps(raw.get("spec") or {}, sort_keys=True)
    return out


def _parse_order(row: tuple) -> dict:
    o = dict(zip(_ORDER_COLUMNS, row))
    o["spec"] = json.loads(o.pop("spec_json") or "{}")
    return o


def insert_order(conn: sqlite3.Connection, raw: dict) -> int:
    r = _order_row(raw)
    cols = list(r)
    with conn:
        cur = conn.execute(f"INSERT INTO fund_order ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                           tuple(r[c] for c in cols))
    return int(cur.lastrowid)


def update_order(conn: sqlite3.Connection, order_id: int, raw: dict) -> None:
    r = _order_row(raw)
    sets = ", ".join(f"{c} = ?" for c in r)
    with conn:
        conn.execute(f"UPDATE fund_order SET {sets} WHERE order_id = ?", (*r.values(), order_id))


def get_order(conn: sqlite3.Connection, order_id: int) -> dict | None:
    row = conn.execute(f"SELECT {', '.join(_ORDER_COLUMNS)} FROM fund_order WHERE order_id = ?",
                       (order_id,)).fetchone()
    return _parse_order(row) if row else None


def list_orders(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    rows = conn.execute(f"SELECT {', '.join(_ORDER_COLUMNS)} FROM fund_order WHERE strategy_id = ? "
                        "ORDER BY ts, order_id", (strategy_id,)).fetchall()
    return [_parse_order(r) for r in rows]


def delete_position(conn: sqlite3.Connection, position_id: str) -> int:
    with conn:
        cur = conn.execute("DELETE FROM fund_order WHERE position_id = ?", (position_id,))
    return cur.rowcount
