"""Notes libres datées sur la courbe d'un actif (VI24 du 26/11) : lecture, ajout, suppression.

Une note = un symbole, une date de séance, un texte court (au plus 120 caractères). Elle s'affiche comme un repère vertical sur le graphique
de cours de la fiche de l'actif (`/api/asset-stats/{symbole}?events=1`, type « note »). Aucun calcul ne la lit.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

MAX_TEXT = 120


class NoteError(ValueError):
    """Note refusée : message en français."""


def list_notes(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    try:
        rows = conn.execute("SELECT note_id, day, text FROM chart_note WHERE symbol = ? ORDER BY day, note_id", (symbol,)).fetchall()
    except sqlite3.OperationalError:            # migration 0061 pas encore passée
        return []
    return [{"note_id": n, "day": d, "text": t} for n, d, t in rows]


def add_note(conn: sqlite3.Connection, symbol: str, day: str, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise NoteError("texte de la note manquant")
    if len(text) > MAX_TEXT:
        raise NoteError(f"note trop longue ({len(text)} caractères, {MAX_TEXT} au plus)")
    try:
        day = dt.date.fromisoformat(str(day)[:10]).isoformat()
    except ValueError as exc:
        raise NoteError("date attendue au format AAAA-MM-JJ") from exc
    with conn:
        cur = conn.execute("INSERT INTO chart_note (symbol, day, text) VALUES (?, ?, ?)", (symbol, day, text))
    return {"note_id": cur.lastrowid, "day": day, "text": text}


def delete_note(conn: sqlite3.Connection, note_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM chart_note WHERE note_id = ?", (int(note_id),))
    return cur.rowcount > 0


def as_events(notes: list[dict]) -> list[dict]:
    """Repères pour le graphique : même forme que `tracking/asset_events.events` (`date`, `kind`, `label`)."""
    return [{"date": n["day"], "kind": "note", "label": "✎ " + (n["text"] if len(n["text"]) <= 24 else n["text"][:23] + "…"),
             "text": n["text"], "note_id": n["note_id"]} for n in notes]
