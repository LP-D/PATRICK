"""Calendrier économique (A17) : publications macro américaines et décisions de taux des banques centrales, à poser sur les cours.

Deux sources, deux natures :
- FRED `release/dates` donne, pour chaque publication suivie (IPC, emploi, PIB, revenus et dépenses PCE, ventes au détail), les dates
  passées ET le calendrier officiel à venir. Stockées dans `econ_release` (migration 0058) par `refresh`, appelé par `patrick news refresh`
  (donc chaque nuit). Sans clé FRED_API_KEY, rien n'est fait (la table reste telle quelle).
- Les décisions de la Fed, de la BCE, de la Banque d'Angleterre et de la Banque du Canada sont reconnues dans les TITRES des communiqués
  déjà collectés (`news_item`, source_kind = 'central_bank'). Seulement le passé, et seulement depuis que la collecte tourne : un flux RSS
  ne garde que ses derniers communiqués. La réunion du FOMC n'a pas de calendrier exploitable dans FRED (sa publication 101 change chaque
  jour avec le taux directeur quotidien), d'où le passage par les titres.

Sur la courbe d'un actif, seuls les repères qui bougent tout le marché sont posés : IPC et emploi américains, décisions de la Fed, et celles
de la banque centrale de la devise de l'actif (BCE pour un titre de la zone euro ou une paire en EUR...). Le reste va dans l'agenda de /news.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import sqlite3

import requests

logger = logging.getLogger(__name__)

RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
API_KEY_ENV = "FRED_API_KEY"
# identifiant de publication FRED -> étiquette courte (repère de graphique) ; vérifiés sur l'API le 2026-11-25
RELEASES: dict[int, str] = {10: "IPC", 50: "Emploi", 53: "PIB", 54: "PCE", 9: "Ventes"}
CHART_RELEASES = frozenset({"IPC", "Emploi"})      # les deux publications qui font bouger tous les marchés
HISTORY_START = "2015-01-01"

# Décisions de taux : (étiquette, source du flux, motif sur le titre). Motifs réglés sur les vrais titres collectés depuis mai 2026.
DECISIONS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("Fed", "rss:fed_monetary", re.compile(r"\bFOMC statement\b", re.IGNORECASE)),
    ("BCE", "rss:ecb_press", re.compile(r"^Monetary policy decisions?\b", re.IGNORECASE)),
    ("BoE", "rss:boe_news", re.compile(r"^Bank Rate (maintained|increased|reduced|cut|raised|held)\b", re.IGNORECASE)),
    ("BoC", "rss:boc_press", re.compile(r"\b(maintains|raises|lowers|cuts|holds) (the |its )?policy (interest )?rate\b", re.IGNORECASE)),
)

_EURO_SUFFIXES = (".PA", ".DE", ".AS", ".BR", ".MI", ".MC", ".LS", ".VI", ".IR", ".HE", ".F", ".AT")
_EURO_INDICES = frozenset({"^FCHI", "^GDAXI", "^STOXX50E", "^IBEX", "^N100", "^BFX", "^AEX"})


def _today() -> dt.date:
    """Date du jour en heure locale (les dates FRED sont des jours du calendrier américain, sans heure)."""
    return dt.datetime.now().astimezone().date()


def fetch_release_dates(release_id: int, api_key: str, start: str = HISTORY_START, session=requests) -> list[str]:
    """Dates (AAAA-MM-JJ) de la publication `release_id` depuis `start`, y compris les dates à venir déjà annoncées."""
    resp = session.get(RELEASE_DATES_URL, params={
        "release_id": release_id, "api_key": api_key, "file_type": "json", "realtime_start": start, "realtime_end": "9999-12-31",
        "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 10000}, timeout=60)
    resp.raise_for_status()
    return sorted({str(r["date"])[:10] for r in resp.json().get("release_dates", [])})


def refresh(conn: sqlite3.Connection, api_key: str | None = None, session=requests) -> dict:
    """Met à jour `econ_release` ; `{"stored": n, "errors": [(publication, message)], "skipped": bool}` (jamais d'exception réseau)."""
    api_key = api_key or os.environ.get(API_KEY_ENV)
    if not api_key:
        return {"stored": 0, "errors": [], "skipped": True}
    stored, errors = 0, []
    for release_id, label in RELEASES.items():
        try:
            days = fetch_release_dates(release_id, api_key, session=session)
        except (requests.RequestException, ValueError, KeyError) as exc:
            errors.append((f"fred:release:{release_id}", f"{type(exc).__name__}: {exc}"))
            continue
        with conn:
            conn.executemany("INSERT OR REPLACE INTO econ_release (day, release_id, label, fetched_at) VALUES (?, ?, ?, datetime('now'))",
                             [(d, release_id, label) for d in days])
        stored += len(days)
    return {"stored": stored, "errors": errors, "skipped": False}


def banks_for(symbol: str) -> tuple[str, ...]:
    """Banques centrales dont les décisions comptent pour `symbol` : la Fed toujours, plus celle de sa devise (heuristique sur le ticker)."""
    s = symbol.upper()
    banks = ["Fed"]
    fx = s.endswith("=X")
    if (fx and "EUR" in s) or s.endswith(_EURO_SUFFIXES) or s in _EURO_INDICES:
        banks.append("BCE")
    if (fx and "GBP" in s) or s.endswith(".L") or s == "^FTSE":
        banks.append("BoE")
    if (fx and "CAD" in s) or s.endswith(".TO") or s == "^GSPTSE":
        banks.append("BoC")
    return tuple(banks)


def decisions(conn: sqlite3.Connection) -> list[dict]:
    """Décisions de taux reconnues dans les communiqués collectés : `[{"date", "label"}]`, une par banque et par jour, triées."""
    out: set[tuple[str, str]] = set()
    sources = tuple(src for _l, src, _p in DECISIONS)
    try:
        rows = conn.execute(f"SELECT source, published_at, title FROM news_item WHERE source IN ({','.join('?' * len(sources))})",
                            sources).fetchall()
    except sqlite3.OperationalError:          # base sans les tables des nouvelles
        return []
    by_source = {src: (label, pat) for label, src, pat in DECISIONS}
    for source, published, title in rows:
        label, pat = by_source[source]
        if published and title and pat.search(title):
            out.add((str(published)[:10], label))
    return [{"date": d, "label": lab} for d, lab in sorted(out)]


# CO25 (25/11) : écart maximal attendu entre deux décisions de chaque banque (la Fed se réunit 8 fois par an, la BCE toutes les six
# semaines, la Banque d'Angleterre 8 fois, la Banque du Canada 8 fois) : au-delà, une décision a probablement échappé à la lecture des titres.
MAX_GAP_DAYS = {"Fed": 63, "BCE": 56, "BoE": 63, "BoC": 63}


def decision_gaps(conn: sqlite3.Connection, today: dt.date | None = None) -> list[dict]:
    """Trous suspects dans les décisions reconnues : `[{"label", "after", "before", "days"}]` (le dernier trou va jusqu'à aujourd'hui).

    Sans calendrier officiel à télécharger, la régularité des réunions suffit à voir une décision manquée : un communiqué au titre reformulé,
    une collecte interrompue. Une banque jamais vue n'est pas signalée (aucune source collectée pour elle)."""
    today = today or _today()
    by: dict[str, list[str]] = {}
    for d in decisions(conn):
        by.setdefault(d["label"], []).append(d["date"])
    out = []
    for label, days in by.items():
        limit = MAX_GAP_DAYS.get(label, 63)
        dates = sorted(dt.date.fromisoformat(d) for d in days)
        for a, b in zip(dates, [*dates[1:], today], strict=True):
            if (b - a).days > limit:
                out.append({"label": label, "after": a.isoformat(), "before": b.isoformat(), "days": (b - a).days})
    return sorted(out, key=lambda r: (r["label"], r["after"]))


def releases(conn: sqlite3.Connection, start: str | None = None, end: str | None = None) -> list[dict]:
    """Publications stockées entre `start` et `end` (inclus) : `[{"date", "label"}]`, triées."""
    try:
        rows = conn.execute("SELECT day, label FROM econ_release WHERE day >= ? AND day <= ? ORDER BY day, label",
                            (start or "0000-00-00", end or "9999-12-31")).fetchall()
    except sqlite3.OperationalError:          # migration 0058 pas encore passée
        return []
    return [{"date": d, "label": lab} for d, lab in rows]


def chart_events(conn: sqlite3.Connection, symbol: str, today: dt.date | None = None) -> list[dict]:
    """Repères macro pour la courbe de `symbol` (jusqu'à aujourd'hui) : `[{"date", "kind": "macro", "label"}]`, un par jour (« IPC·Fed »)."""
    today_s = (today or _today()).isoformat()
    banks = set(banks_for(symbol))
    picked = [e for e in releases(conn, end=today_s) if e["label"] in CHART_RELEASES]
    picked += [e for e in decisions(conn) if e["label"] in banks and e["date"] <= today_s]
    by_day: dict[str, list[str]] = {}
    for e in sorted(picked, key=lambda e: e["date"]):
        labels = by_day.setdefault(e["date"], [])
        if e["label"] not in labels:
            labels.append(e["label"])
    return [{"date": d, "kind": "macro", "label": "·".join(labs)} for d, labs in by_day.items()]


def agenda(conn: sqlite3.Connection, today: dt.date | None = None, ahead_days: int = 45, back_days: int = 60) -> dict:
    """Agenda de /news : publications à venir (`upcoming`, `ahead_days` jours) et récentes décisions de taux (`decisions`, `back_days`)."""
    today = today or _today()
    upcoming = releases(conn, start=today.isoformat(), end=(today + dt.timedelta(days=ahead_days)).isoformat())
    since = (today - dt.timedelta(days=back_days)).isoformat()
    recent = [e for e in decisions(conn) if since <= e["date"] <= today.isoformat()]
    for e in upcoming:
        e["in_days"] = (dt.date.fromisoformat(e["date"]) - today).days
    try:
        has_releases = conn.execute("SELECT 1 FROM econ_release LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        has_releases = False
    return {"upcoming": upcoming, "decisions": list(reversed(recent)), "has_releases": has_releases}
