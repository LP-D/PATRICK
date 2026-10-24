"""Partage des fonds entre deux PC : chaque PC publie ses fonds dans un petit fichier à lui, et fusionne ceux
des autres (voir `patrick.sync`, étape « fonds »).

Contrairement au patrimoine (un PC de référence que les autres adoptent), les fonds se FUSIONNENT : chaque
stratégie a un identifiant unique (`str_xxxxxxxxxx`), donc deux PC qui en créent chacun de leur côté se
retrouvent avec la réunion des deux. La stratégie est l'unité d'échange (avec ses ordres et ses règles) :

- absente d'ici : importée;
- présente des deux côtés : la version modifiée en dernier (`fund_strategy.updated_at`) l'emporte, l'autre est
  d'abord sauvegardée en JSON; à date égale, ce PC garde la sienne;
- supprimée quelque part (`fund_deleted`) : supprimée partout, sauf si elle a été modifiée après la suppression;
- cotations (`fund_price`) : l'union des jours; pour un titre dont l'autre PC a rafraîchi l'historique plus
  récemment, ses valeurs remplacent celles de ce PC.

Rien n'est écrit tant que tout n'est pas passé : une seule transaction. Les identifiants d'ordre (`order_id`)
sont propres à chaque base : les ordres importés reçoivent les suivants, dans leur ordre d'origine.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from patrick import paths
from patrick.tracking import db as trackdb

# Parents avant enfants. Les enfants d'une stratégie sont recopiés avec elle.
TABLES = ("fund_strategy", "fund_rule", "fund_order", "fund_deleted", "fund_price_meta", "fund_price")
MIN_SCHEMA = 44                                        # 0033 : `updated_at`, `fund_deleted` ; 0044 : `autopilot_json`


class FundShareError(RuntimeError):
    """Échange impossible (schéma trop ancien ou trop récent...), expliqué à l'utilisateur."""


def _uri(path: str | Path, mode: str) -> str:
    return Path(path).resolve().as_uri() + f"?mode={mode}"


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _shared_columns(conn: sqlite3.Connection, table: str, *, skip: tuple[str, ...] = ()) -> list[str]:
    src = set(_columns(conn, "src", table))
    return [c for c in _columns(conn, "main", table) if c in src and c not in skip]


def _csv(cols: list[str], prefix: str = "") -> str:
    return ", ".join(f'{prefix}"{c}"' for c in cols)


def export_funds(db_path: str, dest: str | Path) -> dict:
    """Écrit dans `dest` (fichier neuf) une base migrée qui ne contient que les fonds de `db_path` (lecture seule
    sur `db_path`). Renvoie `{"strategies", "orders"}`."""
    dest = Path(dest)
    if dest.exists():
        raise FundShareError(f"{dest} existe déjà")
    trackdb.connect(str(dest)).close()                     # schéma à jour, vide
    conn = sqlite3.connect(_uri(dest, "rwc"), uri=True, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("ATTACH DATABASE ? AS src", (_uri(db_path, "ro"),))
        conn.execute("BEGIN")
        for table in TABLES:
            cols = _csv(_shared_columns(conn, table))
            conn.execute(f'INSERT INTO main."{table}" ({cols}) SELECT {cols} FROM src."{table}"')
        conn.execute("COMMIT")
        out = {"strategies": conn.execute("SELECT COUNT(*) FROM main.fund_strategy").fetchone()[0],
               "orders": conn.execute("SELECT COUNT(*) FROM main.fund_order").fetchone()[0]}
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    return out


def fingerprint(db_path: str) -> str:
    """Empreinte des stratégies et de leurs suppressions (pas des cotations : elles voyagent avec une
    publication mais n'en déclenchent pas). Lecture seule."""
    conn = sqlite3.connect(_uri(db_path, "ro"), uri=True)
    try:
        parts = [conn.execute("SELECT strategy_id, COALESCE(updated_at, '') FROM fund_strategy "
                              "ORDER BY strategy_id").fetchall(),
                 conn.execute("SELECT strategy_id, deleted_at FROM fund_deleted ORDER BY strategy_id").fetchall()]
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def _stamp(value) -> str:
    return value or ""


def _strategy_dump(conn: sqlite3.Connection, strategy_id: str) -> dict:
    """Une stratégie de `main` avec ses règles et ses ordres, pour la sauvegarde JSON."""
    out: dict = {}
    for table in ("fund_strategy", "fund_rule", "fund_order"):
        cols = _columns(conn, "main", table)
        rows = conn.execute(f'SELECT {_csv(cols)} FROM main."{table}" WHERE strategy_id = ?', (strategy_id,)).fetchall()
        out[table] = [dict(zip(cols, r)) for r in rows]
    return out


def _backup(conn: sqlite3.Connection, strategy_id: str, backup_dir: str | Path, why: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = Path(backup_dir) / f"fonds_{why}_{strategy_id}_{stamp}.json"
    path.write_text(json.dumps(_strategy_dump(conn, strategy_id), indent=1, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return str(path)


def _drop_strategy(conn: sqlite3.Connection, strategy_id: str) -> None:
    for table in ("fund_order", "fund_rule", "fund_strategy"):
        conn.execute(f'DELETE FROM main."{table}" WHERE strategy_id = ?', (strategy_id,))


def _import_strategy(conn: sqlite3.Connection, strategy_id: str) -> int:
    """Recopie de `src` une stratégie, ses règles et ses ordres (dans leur ordre d'origine); renvoie le nombre d'ordres."""
    for table in ("fund_strategy", "fund_rule"):
        cols = _csv(_shared_columns(conn, table))
        conn.execute(f'INSERT INTO main."{table}" ({cols}) SELECT {cols} FROM src."{table}" WHERE strategy_id = ?',
                     (strategy_id,))
    cols = _csv(_shared_columns(conn, "fund_order", skip=("order_id",)))
    before = conn.total_changes
    conn.execute(f'INSERT INTO main.fund_order ({cols}) SELECT {cols} FROM src.fund_order WHERE strategy_id = ? '
                 "ORDER BY order_id", (strategy_id,))
    return conn.total_changes - before


def _merge_prices(conn: sqlite3.Connection) -> int:
    """Union des cotations. Renvoie le nombre de titres dont l'historique de l'autre PC remplace le nôtre."""
    conn.execute("CREATE TEMP TABLE newer_symbols AS SELECT s.symbol AS symbol FROM src.fund_price_meta s "
                 "LEFT JOIN main.fund_price_meta m ON m.symbol = s.symbol "
                 "WHERE m.symbol IS NULL OR COALESCE(s.refreshed_at, '') > COALESCE(m.refreshed_at, '')")
    try:
        cols = _shared_columns(conn, "fund_price")
        sets = ", ".join(f'"{c}" = excluded."{c}"' for c in cols if c not in ("symbol", "day"))
        conn.execute(f'INSERT INTO main.fund_price ({_csv(cols)}) SELECT {_csv(cols)} FROM src.fund_price '
                     f"WHERE symbol IN (SELECT symbol FROM temp.newer_symbols) "
                     f"ON CONFLICT(symbol, day) DO UPDATE SET {sets}")
        conn.execute(f'INSERT OR IGNORE INTO main.fund_price ({_csv(cols)}) SELECT {_csv(cols)} FROM src.fund_price')
        conn.execute("INSERT INTO main.fund_price_meta (symbol, currency, refreshed_at) "
                     "SELECT symbol, currency, refreshed_at FROM src.fund_price_meta "
                     "WHERE symbol IN (SELECT symbol FROM temp.newer_symbols) "
                     "ON CONFLICT(symbol) DO UPDATE SET currency = COALESCE(excluded.currency, fund_price_meta.currency), "
                     "refreshed_at = excluded.refreshed_at")
        return conn.execute("SELECT COUNT(*) FROM temp.newer_symbols").fetchone()[0]
    finally:
        conn.execute("DROP TABLE IF EXISTS temp.newer_symbols")


def merge_funds(db_path: str, incoming: str | Path, *, backup_dir: str | Path | None = None) -> dict:
    """Fusionne dans `db_path` (modifiée en place, en UNE transaction) les fonds du fichier `incoming` (voir le
    module). Renvoie `imported`, `replaced`, `deleted` (identifiants de stratégie), `orders` (ordres ajoutés),
    `prices_newer` (titres rafraîchis par l'autre PC) et `backups` (fichiers JSON des versions écartées)."""
    backup_dir = backup_dir or paths.backups_dir()
    conn = sqlite3.connect(_uri(db_path, "rw"), uri=True, isolation_level=None, timeout=60)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")          # enfants gérés à la main, parents avant enfants
        conn.execute("ATTACH DATABASE ? AS src", (_uri(incoming, "ro"),))
        mine = conn.execute("SELECT COALESCE(MAX(version), 0) FROM main.schema_version").fetchone()[0]
        theirs = conn.execute("SELECT COALESCE(MAX(version), 0) FROM src.schema_version").fetchone()[0]
        if theirs > mine:
            raise FundShareError(f"Les fonds du partage sont en version de schéma {theirs}, ce PC ne connaît que "
                                 f"{mine} : mets PATRICK à jour sur ce PC.")
        if theirs < MIN_SCHEMA:
            raise FundShareError(f"Les fonds du partage viennent d'une version trop ancienne de PATRICK (schéma {theirs}) : "
                                 "mets PATRICK à jour sur l'autre PC.")
        out: dict = {"imported": [], "replaced": [], "deleted": [], "orders": 0, "backups": []}
        conn.execute("BEGIN IMMEDIATE")
        try:
            local = {r[0]: _stamp(r[1]) for r in conn.execute("SELECT strategy_id, updated_at FROM main.fund_strategy")}
            local_del = dict(conn.execute("SELECT strategy_id, deleted_at FROM main.fund_deleted").fetchall())
            remote = {r[0]: _stamp(r[1]) for r in conn.execute("SELECT strategy_id, updated_at FROM src.fund_strategy")}
            remote_del = dict(conn.execute("SELECT strategy_id, deleted_at FROM src.fund_deleted").fetchall())

            for sid, deleted_at in remote_del.items():     # 1) suppressions faites ailleurs
                if sid in local and local[sid] <= deleted_at:
                    out["backups"].append(_backup(conn, sid, backup_dir, "supprime"))
                    _drop_strategy(conn, sid)
                    del local[sid]
                    out["deleted"].append(sid)
                if sid not in local and deleted_at > local_del.get(sid, ""):
                    conn.execute("INSERT OR REPLACE INTO main.fund_deleted (strategy_id, deleted_at) VALUES (?, ?)",
                                 (sid, deleted_at))
                    local_del[sid] = deleted_at

            for sid, updated in remote.items():            # 2) stratégies de l'autre PC
                if sid in local:
                    if updated <= local[sid]:
                        continue
                    out["backups"].append(_backup(conn, sid, backup_dir, "remplace"))
                    _drop_strategy(conn, sid)
                    out["replaced"].append(sid)
                elif sid in local_del:
                    if updated <= local_del[sid]:
                        continue                           # supprimée ici après sa dernière modification là-bas
                    conn.execute("DELETE FROM main.fund_deleted WHERE strategy_id = ?", (sid,))
                    del local_del[sid]
                    out["imported"].append(sid)
                else:
                    out["imported"].append(sid)
                out["orders"] += _import_strategy(conn, sid)
                local[sid] = updated

            out["prices_newer"] = _merge_prices(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return out
    finally:
        conn.close()
