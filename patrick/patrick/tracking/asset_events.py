"""Événements datés d'un actif à poser sur sa courbe de cours (D3) : changements de champion et publications de résultats.

Lecture seule. Les publications viennent de `earn_calendar` (page /resultats) quand l'actif y est suivi ; une base sans ces tables donne
simplement les changements de champion.
"""
from __future__ import annotations

import sqlite3

from patrick.tracking import champion_history

MAX_EVENTS = 60


def events(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    """`[{"date": "AAAA-MM-JJ", "kind": "champion" | "earnings", "label": str}]`, triés par date, au plus `MAX_EVENTS` (les plus récents)."""
    out: list[dict] = []
    for horizon, reigns in champion_history.history(conn, symbol).items():
        for r in reigns:
            if r["start"]:
                out.append({"date": r["start"], "kind": "champion", "label": f"C{horizon}"})
    try:
        for (day,) in conn.execute("SELECT ann_date FROM earn_calendar WHERE symbol = ? ORDER BY ann_date", (symbol,)):
            out.append({"date": str(day)[:10], "kind": "earnings", "label": "R"})
    except sqlite3.OperationalError:          # base sans les tables des résultats
        pass
    # Plusieurs changements de champion le même jour (un lancement à plusieurs horizons) : une seule étiquette « C1·5·10 », sinon superposées.
    merged: dict[tuple[str, str], dict] = {}
    for e in sorted(out, key=lambda e: (e["date"], e["kind"])):
        key = (e["date"], e["kind"])
        if key in merged and e["kind"] == "champion":
            merged[key]["label"] += "·" + e["label"][1:]
        else:
            merged.setdefault(key, dict(e))
    return list(merged.values())[-MAX_EVENTS:]
