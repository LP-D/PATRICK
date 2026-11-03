"""Tables `earn_*` : schéma additif et isolé, sur le modèle de `tracking/cache_tables.py` (cache SHAP).

Volontairement PAS une migration numérotée passée par `db.migrate()` : cette fonction a une course connue sur
`schema_version` (non reproduite, hors périmètre). Ces tables sont créées par `ensure_schema()` (CREATE TABLE IF NOT EXISTS :
idempotent, sûr à chaque accès depuis n'importe quel processus, ne touche jamais `schema_version` ni une table existante).
Aucune clé étrangère vers les tables de runs : un cycle d'ingestion ne bloque jamais un run, et inversement.

- `earn_alias` : nom normalisé -> ligne locale (+ ADR), confirmée par l'utilisateur ou semée ; persistante.
- `earn_batch` / `earn_batch_item` : une newsletter collée et ses noms (avec candidats Yahoo et statut de confirmation).
- `earn_calendar` : toutes les annonces d'un titre (passées avec EPS, à venir), avec l'heure convertie et le timing BMO/AMC.
- `earn_instrument` : fiche du titre (secteur, pays, devise, capitalisation, dates fiscales) en JSON.
- `earn_result` : mesures par événement (trajectoire de rendements anormaux, CAR, liquidité), clé = (titre, date, hash des mesures).
- `earn_study_cache` : résultat d'une carte d'étude, clé = (étude, périmètre, paramètres, version des données).
- `earn_snapshot` : instantanés quotidiens (consensus, options, vendeurs à découvert) : le seul moyen d'avoir un historique
  daté avec des sources gratuites. Une ligne par (titre, jour, nature) : on n'écrase jamais un instantané d'un autre jour.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, date, datetime

from patrick.clock import local_now

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS earn_alias (
        alias TEXT PRIMARY KEY, symbol TEXT NOT NULL, adr_symbol TEXT, display TEXT,
        source TEXT NOT NULL DEFAULT 'user', updated_at TEXT NOT NULL DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS earn_batch (
        batch_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
        anchor_monday TEXT NOT NULL, raw_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending')""",
    """CREATE TABLE IF NOT EXISTS earn_batch_item (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES earn_batch(batch_id) ON DELETE CASCADE,
        day_index INTEGER NOT NULL, plan_date TEXT NOT NULL, name TEXT NOT NULL, alias TEXT NOT NULL, hint TEXT,
        symbol TEXT, adr_symbol TEXT, candidates_json TEXT, timing_override TEXT,
        status TEXT NOT NULL DEFAULT 'pending', flags_json TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_earn_batch_item_batch ON earn_batch_item (batch_id)",
    """CREATE TABLE IF NOT EXISTS earn_calendar (
        symbol TEXT NOT NULL, ann_date TEXT NOT NULL, ann_local_time TEXT NOT NULL DEFAULT '', timing TEXT NOT NULL,
        timing_source TEXT NOT NULL, uncertain INTEGER NOT NULL DEFAULT 0, reason TEXT,
        eps_estimate REAL, eps_actual REAL, surprise_pct REAL, source TEXT NOT NULL DEFAULT 'yahoo',
        fetched_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (symbol, ann_date))""",
    """CREATE TABLE IF NOT EXISTS earn_instrument (
        symbol TEXT PRIMARY KEY, payload_json TEXT NOT NULL, fetched_at TEXT NOT NULL DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS earn_result (
        symbol TEXT NOT NULL, ann_date TEXT NOT NULL, cfg_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
        computed_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (symbol, ann_date, cfg_hash))""",
    """CREATE TABLE IF NOT EXISTS earn_study_cache (
        study_id TEXT NOT NULL, scope_key TEXT NOT NULL, params_hash TEXT NOT NULL, data_version TEXT NOT NULL,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (study_id, scope_key, params_hash, data_version))""",
    """CREATE TABLE IF NOT EXISTS earn_state (
        key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS earn_snapshot (
        symbol TEXT NOT NULL, snap_date TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
        taken_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (symbol, snap_date, kind))""",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    with conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)


def clean(value):
    """JSON strict : NaN / inf -> null, numpy -> Python, dates -> texte."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):          # numpy scalar
        return clean(value.item())
    if hasattr(value, "tolist"):
        return clean(value.tolist())
    return value


def dumps(payload) -> str:
    return json.dumps(clean(payload), ensure_ascii=False, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------------------------------------------------------ alias

def get_alias(conn, alias: str) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("SELECT alias, symbol, adr_symbol, display, source FROM earn_alias WHERE alias = ?", (alias,)).fetchone()
    return dict(zip(("alias", "symbol", "adr_symbol", "display", "source"), row)) if row else None


def put_alias(conn, alias: str, symbol: str, adr_symbol: str | None = None, display: str | None = None, source: str = "user") -> None:
    ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO earn_alias (alias, symbol, adr_symbol, display, source, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(alias) DO UPDATE SET symbol = excluded.symbol, adr_symbol = excluded.adr_symbol, "
            "display = COALESCE(excluded.display, display), source = excluded.source, updated_at = excluded.updated_at",
            (alias, symbol, adr_symbol or None, display, source))


def list_aliases(conn) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute("SELECT alias, symbol, adr_symbol, display, source FROM earn_alias ORDER BY alias").fetchall()
    return [dict(zip(("alias", "symbol", "adr_symbol", "display", "source"), r)) for r in rows]


def delete_alias(conn, alias: str) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM earn_alias WHERE alias = ?", (alias,))


# ------------------------------------------------------------------------------------------------------------------ batch

def create_batch(conn, anchor_monday: date, raw_text: str, items: list[dict]) -> int:
    ensure_schema(conn)
    with conn:
        cur = conn.execute("INSERT INTO earn_batch (anchor_monday, raw_text) VALUES (?, ?)", (anchor_monday.isoformat(), raw_text))
        batch_id = cur.lastrowid
        for it in items:
            conn.execute(
                "INSERT INTO earn_batch_item (batch_id, day_index, plan_date, name, alias, hint, symbol, adr_symbol, candidates_json, "
                "timing_override, status, flags_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (batch_id, it["day_index"], it["plan_date"], it["name"], it["alias"], it.get("hint"), it.get("symbol"),
                 it.get("adr_symbol"), dumps(it.get("candidates", [])), it.get("timing_override"),
                 it.get("status", "pending"), dumps(it.get("flags", []))))
    return int(batch_id)


_ITEM_COLS = ("item_id", "batch_id", "day_index", "plan_date", "name", "alias", "hint", "symbol", "adr_symbol",
              "candidates_json", "timing_override", "status", "flags_json")


def batch_items(conn, batch_id: int) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute(f"SELECT {', '.join(_ITEM_COLS)} FROM earn_batch_item WHERE batch_id = ? ORDER BY day_index, item_id",
                        (batch_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(zip(_ITEM_COLS, r))
        d["candidates"] = json.loads(d.pop("candidates_json") or "[]")
        d["flags"] = json.loads(d.pop("flags_json") or "[]")
        out.append(d)
    return out


def get_batch(conn, batch_id: int) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("SELECT batch_id, created_at, anchor_monday, raw_text, status FROM earn_batch WHERE batch_id = ?",
                       (batch_id,)).fetchone()
    return dict(zip(("batch_id", "created_at", "anchor_monday", "raw_text", "status"), row)) if row else None


def latest_batch(conn) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("SELECT batch_id FROM earn_batch ORDER BY batch_id DESC LIMIT 1").fetchone()
    return get_batch(conn, row[0]) if row else None


def list_batches(conn, limit: int = 12) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute("SELECT b.batch_id, b.created_at, b.anchor_monday, b.status, COUNT(i.item_id) "
                        "FROM earn_batch b LEFT JOIN earn_batch_item i USING (batch_id) GROUP BY b.batch_id "
                        "ORDER BY b.batch_id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(zip(("batch_id", "created_at", "anchor_monday", "status", "n_items"), r)) for r in rows]


def update_item(conn, item_id: int, **fields) -> None:
    allowed = {"symbol", "adr_symbol", "timing_override", "status", "flags", "candidates"}
    sets, args = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"champ non modifiable : {key}")
        col = {"flags": "flags_json", "candidates": "candidates_json"}.get(key, key)
        sets.append(f"{col} = ?")
        args.append(dumps(value) if key in ("flags", "candidates") else value)
    if sets:
        with conn:
            conn.execute(f"UPDATE earn_batch_item SET {', '.join(sets)} WHERE item_id = ?", (*args, item_id))


def set_batch_status(conn, batch_id: int, status: str) -> None:
    with conn:
        conn.execute("UPDATE earn_batch SET status = ? WHERE batch_id = ?", (status, batch_id))


def delete_batch(conn, batch_id: int) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM earn_batch WHERE batch_id = ?", (batch_id,))


# -------------------------------------------------------------------------------------------------------------- calendar

_CAL_COLS = ("symbol", "ann_date", "ann_local_time", "timing", "timing_source", "uncertain", "reason", "eps_estimate",
             "eps_actual", "surprise_pct", "source")


def upsert_calendar(conn, rows: list[dict], keep_user: bool = True) -> int:
    """Insère ou met à jour des annonces. Une ligne saisie ou corrigée par l'utilisateur (`timing_source = 'user'`) n'est
    jamais écrasée par un rafraîchissement Yahoo (`keep_user`)."""
    ensure_schema(conn)
    n = 0
    with conn:
        for r in rows:
            values = [clean(r.get(c)) for c in _CAL_COLS]
            values[1] = str(values[1])
            guard = " WHERE earn_calendar.timing_source != 'user'" if keep_user else ""
            conn.execute(
                f"INSERT INTO earn_calendar ({', '.join(_CAL_COLS)}, fetched_at) VALUES ({', '.join('?' * len(_CAL_COLS))}, datetime('now')) "
                "ON CONFLICT(symbol, ann_date) DO UPDATE SET "
                + ", ".join(f"{c} = excluded.{c}" for c in _CAL_COLS[2:]) + ", fetched_at = excluded.fetched_at" + guard,
                values)
            n += 1
    return n


def calendar_for(conn, symbol: str, since: str | None = None) -> list[dict]:
    ensure_schema(conn)
    sql = f"SELECT {', '.join(_CAL_COLS)} FROM earn_calendar WHERE symbol = ?"
    args: list = [symbol]
    if since:
        sql += " AND ann_date >= ?"
        args.append(since)
    rows = conn.execute(sql + " ORDER BY ann_date", args).fetchall()
    return [dict(zip(_CAL_COLS, r)) for r in rows]


def calendar_fetched_at(conn, symbol: str) -> str | None:
    ensure_schema(conn)
    row = conn.execute("SELECT MAX(fetched_at) FROM earn_calendar WHERE symbol = ? AND source = 'yahoo'", (symbol,)).fetchone()
    return row[0] if row else None


def all_calendar(conn, symbols: list[str] | None = None) -> list[dict]:
    ensure_schema(conn)
    sql = f"SELECT {', '.join(_CAL_COLS)} FROM earn_calendar"
    args: list = []
    if symbols:
        sql += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
        args = list(symbols)
    return [dict(zip(_CAL_COLS, r)) for r in conn.execute(sql + " ORDER BY symbol, ann_date", args).fetchall()]


# ----------------------------------------------------------------------------------------------------------- instrument

def put_instrument(conn, symbol: str, payload: dict) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute("INSERT INTO earn_instrument (symbol, payload_json, fetched_at) VALUES (?, ?, datetime('now')) "
                     "ON CONFLICT(symbol) DO UPDATE SET payload_json = excluded.payload_json, fetched_at = excluded.fetched_at",
                     (symbol, dumps(payload)))


def get_instrument(conn, symbol: str, max_age_days: float | None = None) -> dict | None:
    ensure_schema(conn)
    sql = "SELECT payload_json FROM earn_instrument WHERE symbol = ?"
    args: list = [symbol]
    if max_age_days is not None:
        sql += " AND julianday('now') - julianday(fetched_at) <= ?"
        args.append(max_age_days)
    row = conn.execute(sql, args).fetchone()
    return json.loads(row[0]) if row else None


def all_instruments(conn, symbols: list[str] | None = None) -> dict[str, dict]:
    ensure_schema(conn)
    sql, args = "SELECT symbol, payload_json FROM earn_instrument", []
    if symbols:
        sql += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
        args = list(symbols)
    return {s: json.loads(p) for s, p in conn.execute(sql, args).fetchall()}


# --------------------------------------------------------------------------------------------------------------- results

def put_result(conn, symbol: str, ann_date: str, cfg_hash: str, payload: dict) -> None:
    ensure_schema(conn)
    with conn:
        # milliseconde : un recalcul dans la même seconde doit quand même changer la version des données (clé de cache des études)
        conn.execute("INSERT INTO earn_result (symbol, ann_date, cfg_hash, payload_json, computed_at) VALUES (?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now')) "
                     "ON CONFLICT(symbol, ann_date, cfg_hash) DO UPDATE SET payload_json = excluded.payload_json, "
                     "computed_at = excluded.computed_at", (symbol, str(ann_date), cfg_hash, dumps(payload)))


def delete_results(conn, symbol: str, cfg_hash: str) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM earn_result WHERE symbol = ? AND cfg_hash = ?", (symbol, cfg_hash))


def load_results(conn, cfg_hash: str, symbols: list[str] | None = None) -> list[dict]:
    ensure_schema(conn)
    sql = "SELECT payload_json FROM earn_result WHERE cfg_hash = ?"
    args: list = [cfg_hash]
    if symbols:
        sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
        args += list(symbols)
    return [json.loads(p) for (p,) in conn.execute(sql + " ORDER BY symbol, ann_date", args).fetchall()]


def results_signature(conn, cfg_hash: str, symbols: list[str] | None = None) -> str:
    """Empreinte des résultats lus : change dès qu'un événement est ajouté, recalculé ou retiré (clé de cache des études)."""
    ensure_schema(conn)
    sql = "SELECT COUNT(*), COALESCE(MAX(computed_at), ''), COALESCE(SUM(LENGTH(payload_json)), 0) FROM earn_result WHERE cfg_hash = ?"
    args: list = [cfg_hash]
    if symbols:
        sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
        args += list(symbols)
    n, last, size = conn.execute(sql, args).fetchone()
    return f"{n}-{last}-{size}"


# ------------------------------------------------------------------------------------------------------------ study cache

def get_study(conn, study_id: str, scope_key: str, params_hash: str, data_version: str) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("SELECT payload_json FROM earn_study_cache WHERE study_id = ? AND scope_key = ? AND params_hash = ? "
                       "AND data_version = ?", (study_id, scope_key, params_hash, data_version)).fetchone()
    return json.loads(row[0]) if row else None


def put_study(conn, study_id: str, scope_key: str, params_hash: str, data_version: str, payload: dict) -> None:
    ensure_schema(conn)
    with conn:
        # une version de données plus récente remplace les anciennes du même triplet : pas de croissance sans fin
        conn.execute("DELETE FROM earn_study_cache WHERE study_id = ? AND scope_key = ? AND params_hash = ?",
                     (study_id, scope_key, params_hash))
        conn.execute("INSERT INTO earn_study_cache (study_id, scope_key, params_hash, data_version, payload_json) VALUES (?, ?, ?, ?, ?)",
                     (study_id, scope_key, params_hash, data_version, dumps(payload)))


def list_cached_studies(conn, scope_key: str, data_version: str) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute("SELECT study_id, params_hash, payload_json FROM earn_study_cache WHERE scope_key = ? AND data_version = ?",
                        (scope_key, data_version)).fetchall()
    return [{"study_id": s, "params_hash": h, "payload": json.loads(p)} for s, h, p in rows]


def clear_studies(conn) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM earn_study_cache")


def adr_map(conn) -> dict[str, str]:
    """{ligne locale: ligne ADR ou liée} d'après les alias confirmés et les lots collés."""
    ensure_schema(conn)
    out: dict[str, str] = {}
    for sql in ("SELECT symbol, adr_symbol FROM earn_batch_item WHERE adr_symbol IS NOT NULL AND symbol IS NOT NULL AND adr_symbol != ''",
                "SELECT symbol, adr_symbol FROM earn_alias WHERE adr_symbol IS NOT NULL AND adr_symbol != ''"):
        for sym, adr in conn.execute(sql).fetchall():
            out[sym] = adr
    return out


def get_state(conn, key: str, default=None):
    ensure_schema(conn)
    row = conn.execute("SELECT value_json FROM earn_state WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put_state(conn, key: str, value) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute("INSERT INTO earn_state (key, value_json, updated_at) VALUES (?, ?, datetime('now')) "
                     "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at", (key, dumps(value)))


def cached_study_rows(conn, scope_key: str, versions: dict[str, str]) -> list[dict]:
    """Toutes les cartes en cache d'un périmètre dont la version de données est la courante (une version par carte)."""
    ensure_schema(conn)
    out = []
    for study_id, version in versions.items():
        for params_hash, payload in conn.execute("SELECT params_hash, payload_json FROM earn_study_cache WHERE study_id = ? AND scope_key = ? "
                                                 "AND data_version = ?", (study_id, scope_key, version)).fetchall():
            out.append({"study_id": study_id, "params_hash": params_hash, "payload": json.loads(payload)})
    return out


# ---------------------------------------------------------------------------------------------------------------- snapshots

def put_snapshot(conn, symbol: str, kind: str, payload: dict, snap_date: date | str | None = None) -> bool:
    """Un instantané par (titre, jour, nature) ; renvoie False si celui du jour existe déjà (jamais réécrit : daté = figé)."""
    ensure_schema(conn)
    day = str(snap_date or local_now().date())
    with conn:
        cur = conn.execute("INSERT OR IGNORE INTO earn_snapshot (symbol, snap_date, kind, payload_json, taken_at) "
                           "VALUES (?, ?, ?, ?, datetime('now'))", (symbol, day, kind, dumps(payload)))
    return cur.rowcount > 0


def snapshots(conn, symbol: str | None = None, kind: str | None = None) -> list[dict]:
    ensure_schema(conn)
    sql, where, args = "SELECT symbol, snap_date, kind, payload_json, taken_at FROM earn_snapshot", [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol)
    if kind:
        where.append("kind = ?")
        args.append(kind)
    rows = conn.execute(sql + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY symbol, snap_date", args).fetchall()
    return [{"symbol": s, "snap_date": d, "kind": k, "payload": json.loads(p), "taken_at": t} for s, d, k, p, t in rows]


def snapshot_counts(conn) -> dict[str, int]:
    ensure_schema(conn)
    return {k: n for k, n in conn.execute("SELECT kind, COUNT(*) FROM earn_snapshot GROUP BY kind").fetchall()}
