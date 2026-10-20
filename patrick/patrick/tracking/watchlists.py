"""Listes de suivi (migration 0042) : un nom, des symboles du data lake, des étiquettes. Les chaînes viennent d'un formulaire : bornées et
normalisées ici, jamais interprétées comme du HTML (les pages les affichent par `textContent`)."""
from __future__ import annotations

import json
import re
import sqlite3

MAX_NAME = 60
MAX_SYMBOLS = 200
MAX_TAGS = 12
MAX_NOTE = 1000
_SYMBOL = re.compile(r"^[A-Za-z0-9^=.\-_]{1,24}$")
_TAG = re.compile(r"[^a-z0-9_\-éèêàùç ]")


class WatchlistError(ValueError):
    """Entrée invalide : le message est un code (`name_required`, `name_taken`, `not_found`, `bad_symbol`, `too_many_symbols`)."""


def normalize_symbols(raw) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,;\s]+", raw or "")
    out: list[str] = []
    for s in items:
        s = str(s).strip()
        if not s:
            continue
        if not _SYMBOL.match(s):
            raise WatchlistError("bad_symbol")
        if s not in out:
            out.append(s)
    if len(out) > MAX_SYMBOLS:
        raise WatchlistError("too_many_symbols")
    return out


def normalize_tags(raw) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,;\n]", raw or "")
    out: list[str] = []
    for t in items:
        t = _TAG.sub("", str(t).strip().lower()).strip()[:32]
        if t and t not in out:
            out.append(t)
    return out[:MAX_TAGS]


def _row(r) -> dict:
    return {"watchlist_id": r[0], "name": r[1], "symbols": json.loads(r[2]), "tags": json.loads(r[3]), "note": r[4], "created_at": r[5], "updated_at": r[6]}


_SELECT = "SELECT watchlist_id, name, symbols, tags, note, created_at, updated_at FROM watchlist"


def list_all(conn: sqlite3.Connection) -> list[dict]:
    return [_row(r) for r in conn.execute(_SELECT + " ORDER BY name COLLATE NOCASE")]


def get(conn: sqlite3.Connection, watchlist_id: int) -> dict | None:
    r = conn.execute(_SELECT + " WHERE watchlist_id = ?", (watchlist_id,)).fetchone()
    return _row(r) if r else None


def _name(value: str | None) -> str:
    name = (value or "").replace("\x00", "").strip()[:MAX_NAME]
    if not name:
        raise WatchlistError("name_required")
    return name


def create(conn: sqlite3.Connection, name: str, symbols=None, tags=None, note: str = "") -> int:
    name = _name(name)
    try:
        with conn:
            cur = conn.execute("INSERT INTO watchlist (name, symbols, tags, note) VALUES (?, ?, ?, ?)",
                               (name, json.dumps(normalize_symbols(symbols)), json.dumps(normalize_tags(tags)), (note or "").replace("\x00", "").strip()[:MAX_NOTE]))
    except sqlite3.IntegrityError as exc:
        raise WatchlistError("name_taken") from exc
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, watchlist_id: int, *, name: str | None = None, symbols=None, tags=None, note: str | None = None) -> None:
    cur = get(conn, watchlist_id)
    if cur is None:
        raise WatchlistError("not_found")
    new = {"name": cur["name"] if name is None else _name(name),
           "symbols": cur["symbols"] if symbols is None else normalize_symbols(symbols),
           "tags": cur["tags"] if tags is None else normalize_tags(tags),
           "note": cur["note"] if note is None else (note or "").replace("\x00", "").strip()[:MAX_NOTE]}
    try:
        with conn:
            conn.execute("UPDATE watchlist SET name = ?, symbols = ?, tags = ?, note = ?, updated_at = datetime('now') WHERE watchlist_id = ?",
                         (new["name"], json.dumps(new["symbols"]), json.dumps(new["tags"]), new["note"], watchlist_id))
    except sqlite3.IntegrityError as exc:
        raise WatchlistError("name_taken") from exc


def delete(conn: sqlite3.Connection, watchlist_id: int) -> None:
    """Supprime la liste seulement (aucune donnée de marché n'est touchée)."""
    with conn:
        n = conn.execute("DELETE FROM watchlist WHERE watchlist_id = ?", (watchlist_id,)).rowcount
    if not n:
        raise WatchlistError("not_found")
