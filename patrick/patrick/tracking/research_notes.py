"""Carnet de recherche (migration 0041) : création, modification (le texte et le statut, jamais la date de création), liste filtrée.

Une hypothèse liée à un run est marquée « posée avant le run » quand sa date de création précède le début du run : c'est la preuve, pour soi-même,
qu'elle n'a pas été écrite après avoir vu le résultat. Toutes les chaînes viennent d'un formulaire : elles sont bornées et normalisées ici, et ne sont
jamais interprétées comme du HTML (les pages les affichent par `textContent`)."""
from __future__ import annotations

import re
import sqlite3

KINDS = ("hypothesis", "note", "result", "decision")
STATUSES = ("open", "confirmed", "refuted", "archived")
MAX_TITLE = 160
MAX_BODY = 8000
MAX_TAGS = 12
_TAG = re.compile(r"[^a-z0-9_\-éèêàùç ]")
COLS = ("note_id", "created_at", "updated_at", "kind", "status", "title", "body", "tags", "target", "horizon", "run_id", "revisions")


class NoteError(ValueError):
    """Entrée invalide : le message est un code (`bad_kind`, `bad_status`, `title_required`, `not_found`, `bad_horizon`)."""


def normalize_tags(raw: str | list[str] | None) -> str:
    items = raw if isinstance(raw, list) else re.split(r"[,;\n]", raw or "")
    out: list[str] = []
    for t in items:
        t = _TAG.sub("", str(t).strip().lower()).strip()[:32]
        if t and t not in out:
            out.append(t)
    return ",".join(out[:MAX_TAGS])


def _clean(value: str | None, limit: int) -> str:
    return (value or "").replace("\x00", "").strip()[:limit]


def create(conn: sqlite3.Connection, kind: str, title: str, body: str = "", tags=None, target: str | None = None, horizon: int | None = None,
           run_id: str | None = None) -> int:
    if kind not in KINDS:
        raise NoteError("bad_kind")
    title = _clean(title, MAX_TITLE)
    if not title:
        raise NoteError("title_required")
    if horizon is not None:
        try:
            horizon = int(horizon)
        except (TypeError, ValueError) as exc:
            raise NoteError("bad_horizon") from exc
    with conn:
        cur = conn.execute("INSERT INTO research_note (kind, title, body, tags, target, horizon, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (kind, title, _clean(body, MAX_BODY), normalize_tags(tags), _clean(target, 80) or None, horizon, _clean(run_id, 120) or None))
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, note_id: int, *, title: str | None = None, body: str | None = None, tags=None, status: str | None = None) -> None:
    row = conn.execute("SELECT title, body, tags, status FROM research_note WHERE note_id = ?", (note_id,)).fetchone()
    if row is None:
        raise NoteError("not_found")
    new_title = row[0] if title is None else _clean(title, MAX_TITLE)
    if not new_title:
        raise NoteError("title_required")
    new_body = row[1] if body is None else _clean(body, MAX_BODY)
    new_tags = row[2] if tags is None else normalize_tags(tags)
    new_status = row[3] if status is None else status
    if new_status not in STATUSES:
        raise NoteError("bad_status")
    if (new_title, new_body, new_tags, new_status) == tuple(row):
        return
    with conn:
        conn.execute("UPDATE research_note SET title = ?, body = ?, tags = ?, status = ?, updated_at = datetime('now'), revisions = revisions + 1 WHERE note_id = ?",
                     (new_title, new_body, new_tags, new_status, note_id))


def list_notes(conn: sqlite3.Connection, *, run_id: str | None = None, target: str | None = None, horizon: int | None = None, kind: str | None = None,
               status: str | None = None, tag: str | None = None, q: str | None = None, include_archived: bool = False, limit: int = 300) -> list[dict]:
    where, params = [], []
    if run_id:
        where.append("n.run_id = ?")
        params.append(run_id)
    if target:
        where.append("n.target = ?")
        params.append(target)
    if horizon is not None:
        where.append("n.horizon = ?")
        params.append(int(horizon))
    if kind:
        where.append("n.kind = ?")
        params.append(kind)
    if status:
        where.append("n.status = ?")
        params.append(status)
    elif not include_archived:
        where.append("n.status != 'archived'")
    if tag:
        where.append("(',' || n.tags || ',') LIKE ?")
        params.append(f"%,{normalize_tags(tag)},%")
    if q:
        where.append("(n.title LIKE ? ESCAPE '!' OR n.body LIKE ? ESCAPE '!')")
        like = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"          # les jokers de LIKE saisis sont cherchés tels quels
        params += [like, like]
    sql = (f"SELECT {', '.join('n.' + c for c in COLS)}, r.started_at FROM research_note n LEFT JOIN run r ON r.run_id = n.run_id "
           + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY n.created_at DESC, n.note_id DESC LIMIT ?")
    out = []
    for row in conn.execute(sql, (*params, max(1, min(1000, int(limit))))).fetchall():
        d = dict(zip(COLS, row[:-1], strict=True))
        d["tags"] = [t for t in d["tags"].split(",") if t]
        d["before_run"] = bool(row[-1] and d["created_at"] <= str(row[-1])[:19]) if d["run_id"] and row[-1] else None
        out.append(d)
    return out


def stats(conn: sqlite3.Connection) -> dict:
    by_kind = dict(conn.execute("SELECT kind, COUNT(*) FROM research_note WHERE status != 'archived' GROUP BY kind"))
    hyp = dict(conn.execute("SELECT status, COUNT(*) FROM research_note WHERE kind = 'hypothesis' AND status != 'archived' GROUP BY status"))
    decided = hyp.get("confirmed", 0) + hyp.get("refuted", 0)
    tags: dict[str, int] = {}
    for (t,) in conn.execute("SELECT tags FROM research_note WHERE status != 'archived' AND tags != ''"):
        for tag in t.split(","):
            tags[tag] = tags.get(tag, 0) + 1
    return {"by_kind": by_kind, "hypotheses": hyp, "confirmation_rate": (hyp.get("confirmed", 0) / decided) if decided else None, "decided": decided,
            "tags": sorted(tags.items(), key=lambda kv: -kv[1])[:30]}
