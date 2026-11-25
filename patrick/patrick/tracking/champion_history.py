"""Frise des champions d'une cible (D26) : qui a tenu le titre, de quand à quand, pour chaque horizon.

Le champion en titre est dans `champion` (avec `promoted_at`) ; chaque champion détrôné est archivé dans `model_archive` avec le rôle
`replaced_champion` et la date de sa défaite (`decided_at`). Son règne commençait à la défaite du précédent (le successeur est promu dans
le même duel) ; le premier règne connu commence à la fin de son run. Lecture seule.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3


def _parse(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=None)
    except ValueError:
        return None


def history(conn: sqlite3.Connection, target: str, now: dt.datetime | None = None) -> dict[int, list[dict]]:
    """`{horizon: [règne, ...]}` du plus ancien au plus récent ; un règne = `run_id`, `algo`, `start`, `end` (None = en titre), `days`,
    `current`, `lost_by` (règle du duel qui l'a détrôné, si connue)."""
    now = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).replace(tzinfo=None)      # les dates de la base sont en UTC sans fuseau
    out: dict[int, list[dict]] = {}
    rows = conn.execute(
        "SELECT horizon, run_id, algo, decided_at, run_finished_at, duel_json FROM model_archive "
        "WHERE target = ? AND role = 'replaced_champion' ORDER BY horizon, decided_at, archive_id", (target,)).fetchall()
    for horizon, run_id, algo, decided_at, finished_at, duel_json in rows:
        reigns = out.setdefault(int(horizon), [])
        start = _parse(reigns[-1]["end_raw"]) if reigns else _parse(finished_at)
        rule = None
        if duel_json:
            try:
                rule = (json.loads(duel_json) or {}).get("rule")
            except ValueError:
                rule = None
        reigns.append({"run_id": run_id, "algo": algo, "start_raw": start.isoformat(sep=" ") if start else None, "end_raw": decided_at,
                       "current": False, "lost_by": rule})
    for horizon, run_id, promoted_at, reason, algo in conn.execute(
            "SELECT c.horizon, c.run_id, c.promoted_at, c.reason, t.algo FROM champion c LEFT JOIN trial t ON t.trial_id = c.trial_id "
            "WHERE c.target = ? ORDER BY c.horizon", (target,)):
        out.setdefault(int(horizon), []).append({"run_id": run_id, "algo": algo, "start_raw": promoted_at, "end_raw": None,
                                                  "current": True, "lost_by": None, "reason": reason})
    for reigns in out.values():
        for r in reigns:
            start, end = _parse(r.pop("start_raw")), _parse(r.pop("end_raw"))
            r["start"] = start.date().isoformat() if start else None
            r["end"] = end.date().isoformat() if end else None
            r["days"] = max(0, ((end or now) - start).days) if start else None
    return dict(sorted(out.items()))
