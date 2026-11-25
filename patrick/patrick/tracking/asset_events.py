"""Événements datés d'un actif à poser sur sa courbe de cours (D3) : changements de champion, publications de résultats et calendrier
économique (A17 : IPC et emploi américains, décisions de taux de la Fed et de la banque centrale de la devise de l'actif).

Lecture seule. Les publications viennent de `earn_calendar` (page /resultats) quand l'actif y est suivi ; une base sans ces tables donne
simplement les changements de champion. Les repères macro ont leur propre plafond : ils ne chassent pas ceux de l'actif.
"""
from __future__ import annotations

import sqlite3

from patrick.data import econ_calendar
from patrick.tracking import champion_history

MAX_EVENTS = 60
MAX_MACRO_EVENTS = 80


def events(conn: sqlite3.Connection, symbol: str, macro: bool = True) -> list[dict]:
    """`[{"date": "AAAA-MM-JJ", "kind": "champion" | "earnings" | "macro", "label": str}]`, triés par date ; au plus `MAX_EVENTS` de l'actif
    et `MAX_MACRO_EVENTS` repères macro (les plus récents)."""
    own = _own_events(conn, symbol)
    if not macro:
        return own
    extra = econ_calendar.chart_events(conn, symbol)[-MAX_MACRO_EVENTS:]
    return sorted(own + extra, key=lambda e: (e["date"], e["kind"]))


def _own_events(conn: sqlite3.Connection, symbol: str) -> list[dict]:
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
