"""Magasin de news point-in-time (migration 0036).

Trois garanties :
- une news sans heure de publication lisible est refusée, jamais devinée ;
- une date seule est lue à 23:59:59 UTC (l'heure la plus tardive plausible) et marquée `date_only` : la news ne peut pas
  alimenter une séance où elle n'était peut-être pas encore parue ;
- `known_at` = max(publication, première observation) : une news rattrapée après coup (flux relu un mois plus tard) n'est
  pas visible dans le passé.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass

import pandas as pd

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class NewsItem:
    source: str
    source_kind: str            # news | central_bank | commodity_report | social | transcript | index
    external_id: str
    published_at: object
    title: str
    summary: str | None = None
    url: str | None = None
    language: str | None = None
    first_seen_at: object = None


def _utc(value, field: str) -> tuple[pd.Timestamp, bool]:
    """(horodatage UTC, était-ce une date seule ?). Lève `ValueError` si illisible."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError(f"{field} manquant : une news sans heure de publication est refusée, jamais devinée")
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} illisible : {value!r}") from exc
    if pd.isna(ts):
        raise ValueError(f"{field} illisible : {value!r}")
    if ts.tzinfo is None:
        date_only = bool(_DATE_ONLY.match(value.strip())) if isinstance(value, str) else ts == ts.normalize()
        ts = ts.tz_localize("UTC")
        if date_only:
            ts = ts.normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
        return ts, date_only
    return ts.tz_convert("UTC"), False


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def content_hash(title: str) -> str:
    return hashlib.sha1(_normalise_title(title).encode("utf-8")).hexdigest()


def add_items(conn: sqlite3.Connection, items) -> int:
    """Insère les news nouvelles et renvoie leur nombre. Doublon = même (source, identifiant) ou même titre normalisé
    pour la même source. Toute la liste est validée AVANT la première écriture."""
    rows = []
    now = pd.Timestamp.now(tz="UTC")
    for it in items:
        published, date_only = _utc(it.published_at, "published_at")
        seen = _utc(it.first_seen_at, "first_seen_at")[0] if it.first_seen_at is not None else now
        title = (it.title or "").strip()
        if not title:
            raise ValueError("titre vide")
        rows.append((it.source, it.source_kind, str(it.external_id), _iso(published), _iso(seen), int(date_only), title,
                     it.summary, it.url, it.language, content_hash(title)))
    added = 0
    with conn:
        for row in rows:
            same_content = conn.execute("SELECT 1 FROM news_item WHERE source = ? AND content_hash = ?",
                                        (row[0], row[10])).fetchone()
            if same_content:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO news_item (source, source_kind, external_id, published_at, first_seen_at, "
                "date_only, title, summary, url, language, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            added += cur.rowcount
    return added


_COLUMNS = ("item_id", "source", "source_kind", "external_id", "published_at", "first_seen_at", "known_at", "date_only",
            "title", "summary", "url", "language", "lag_hours")
LAG_SQL = "(julianday(first_seen_at) - julianday(published_at)) * 24.0"


def load_items(conn: sqlite3.Connection, start=None, end=None, kinds=None, max_lag_hours: float | None = None) -> pd.DataFrame:
    """News utilisables entre `start` (inclus) et `end` (exclu), filtrées sur `known_at` (et non sur la date annoncée).
    `lag_hours` = écart entre la première observation et la publication annoncée ; `max_lag_hours` écarte les news
    « périmées » (un flux relu des mois plus tard n'est pas de l'actualité : elle ne doit pas peser dans le sentiment du jour)."""
    where, args = [], []
    if start is not None:
        where.append("MAX(published_at, first_seen_at) >= ?")
        args.append(_iso(_utc(start, "start")[0].normalize()))
    if end is not None:
        where.append("MAX(published_at, first_seen_at) < ?")
        args.append(_iso(_utc(end, "end")[0].normalize()))
    if kinds:
        where.append(f"source_kind IN ({','.join('?' for _ in kinds)})")
        args.extend(kinds)
    if max_lag_hours is not None:
        where.append(f"{LAG_SQL} <= ?")
        args.append(float(max_lag_hours))
    sql = ("SELECT item_id, source, source_kind, external_id, published_at, first_seen_at, "
           f"MAX(published_at, first_seen_at) AS known_at, date_only, title, summary, url, language, {LAG_SQL} AS lag_hours "
           "FROM news_item"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY known_at, item_id")
    df = pd.DataFrame(conn.execute(sql, args).fetchall(), columns=list(_COLUMNS))
    for col in ("published_at", "first_seen_at", "known_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    df["date_only"] = df["date_only"].astype(bool)
    return df


def save_scores(conn: sqlite3.Connection, scorer: str, version: str, scores: dict) -> None:
    """`scores` : {item_id: (score, détail)}. Réécrit une note existante (même outil, même version)."""
    with conn:
        for item_id, (score, detail) in scores.items():
            conn.execute(
                "INSERT INTO news_score (item_id, scorer, version, score, detail_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(item_id, scorer, version) DO UPDATE SET score = excluded.score, "
                "detail_json = excluded.detail_json",
                (int(item_id), scorer, str(version), None if score is None else float(score),
                 None if detail is None else json.dumps(detail, ensure_ascii=False)))


def unscored_item_ids(conn: sqlite3.Connection, scorer: str, version: str, limit: int | None = None) -> list[int]:
    sql = ("SELECT item_id FROM news_item WHERE item_id NOT IN "
           "(SELECT item_id FROM news_score WHERE scorer = ? AND version = ?) ORDER BY item_id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(sql, (scorer, str(version)))]


def load_scores(conn: sqlite3.Connection, scorer: str, version: str) -> pd.DataFrame:
    rows = conn.execute("SELECT item_id, score, detail_json FROM news_score WHERE scorer = ? AND version = ?",
                        (scorer, str(version))).fetchall()
    return pd.DataFrame(rows, columns=["item_id", "score", "detail_json"])


def save_links(conn: sqlite3.Connection, links) -> None:
    """`links` : [(item_id, symbole, méthode)]. Un couple (news, symbole) n'existe qu'une fois."""
    with conn:
        conn.executemany("INSERT OR IGNORE INTO news_link (item_id, symbol, method) VALUES (?, ?, ?)",
                         [(int(i), s, m) for i, s, m in links])


def load_links(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT item_id, symbol, method FROM news_link ORDER BY item_id, symbol").fetchall()
    return pd.DataFrame(rows, columns=["item_id", "symbol", "method"])
