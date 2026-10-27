"""Historique de nouvelles disponible, et porte d'entrée vers l'entraînement.

Une variable textuelle n'a de sens dans un entraînement que si l'historique point-in-time couvre assez de séances : avec deux jours
de collecte, 99 % des lignes d'entraînement seraient vides et le modèle apprendrait le hasard. Ce module mesure l'historique
(`measure`) et refuse d'en fabriquer des variables tant qu'il est trop court (`require_history`).

Critères (volontairement stricts, à relire avec les premiers résultats) :
- `MIN_SPAN_SESSIONS` séances ouvrées entre la première et la dernière nouvelle utilisable (un an environ) ;
- `MIN_NEWS_DAYS` jours distincts avec au moins une nouvelle utilisable : une collecte qui a des trous ne remplit pas la fenêtre.
Une nouvelle « utilisable » est vue dans les 72 h suivant sa publication (`service.MAX_LAG_HOURS`) : les nouvelles rattrapées
longtemps après n'ont pas d'heure de connaissance fiable.

Rien ici n'est branché sur `RunConfig` : ajouter un champ à `FeaturesConfig` change la clé du cache de variables et l'identité des runs
existants. Le branchement se fera avec un drapeau explicite, une fois la porte franchie et l'apport mesuré en walk-forward.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.text import store

MIN_SPAN_SESSIONS = 250
MIN_NEWS_DAYS = 60
MAX_LAG_HOURS = 72.0


class NewsHistoryTooShort(RuntimeError):
    """L'historique de nouvelles ne permet pas encore d'en faire des variables d'entraînement."""


@dataclass(frozen=True)
class Readiness:
    symbol: str | None
    n_items: int
    news_days: int                          # jours distincts avec au moins une nouvelle utilisable
    span_sessions: int                      # séances ouvrées entre la première et la dernière
    first_day: pd.Timestamp | None
    last_day: pd.Timestamp | None
    ready: bool
    ready_on: pd.Timestamp | None           # première date où la durée requise est atteinte si la collecte continue

    def missing(self) -> str:
        if self.ready:
            return ""
        parts = []
        if self.span_sessions < MIN_SPAN_SESSIONS:
            parts.append(f"{MIN_SPAN_SESSIONS - self.span_sessions} séance(s) d'historique")
        if self.news_days < MIN_NEWS_DAYS:
            parts.append(f"{MIN_NEWS_DAYS - self.news_days} jour(s) avec nouvelles")
        return " et ".join(parts)


def measure(conn: sqlite3.Connection, symbol: str | None = None) -> Readiness:
    """Historique utilisable, pour tout le magasin ou pour les nouvelles rattachées à `symbol`."""
    items = store.load_items(conn, max_lag_hours=MAX_LAG_HOURS)
    if symbol is not None:
        links = store.load_links(conn)
        items = items[items["item_id"].isin(set(links.loc[links["symbol"] == symbol, "item_id"]))]
    if items.empty:
        return Readiness(symbol, 0, 0, 0, None, None, False, None)
    days = pd.DatetimeIndex(items["known_at"].dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize().unique()).sort_values()
    first, last = days[0], days[-1]
    span = int(np.busday_count(first.date(), last.date())) + 1
    ready = span >= MIN_SPAN_SESSIONS and len(days) >= MIN_NEWS_DAYS
    ready_on = first + pd.offsets.BDay(MIN_SPAN_SESSIONS - 1)
    return Readiness(symbol, len(items), len(days), span, first, last, ready, ready_on)


def quick_counts(conn: sqlite3.Connection) -> dict:
    """Historique de tout le magasin par comptages SQL seulement (la page /news doit s'ouvrir tout de suite) :
    `news_days`, `span_sessions`, `required_sessions`, `ready`."""
    known = "MAX(published_at, first_seen_at)"
    n_days, first, last = conn.execute(
        f"SELECT COUNT(DISTINCT substr({known}, 1, 10)), MIN(substr({known}, 1, 10)), MAX(substr({known}, 1, 10)) "
        f"FROM news_item WHERE {store.LAG_SQL} <= ?", (MAX_LAG_HOURS,)).fetchone()
    span = int(np.busday_count(first, last)) + 1 if first else 0
    return {"news_days": n_days, "span_sessions": span, "required_sessions": MIN_SPAN_SESSIONS,
            "ready": span >= MIN_SPAN_SESSIONS and n_days >= MIN_NEWS_DAYS}


def require_history(conn: sqlite3.Connection, symbol: str | None = None) -> Readiness:
    """`measure`, ou `NewsHistoryTooShort` si la porte n'est pas franchie."""
    status = measure(conn, symbol)
    if not status.ready:
        where = f" pour {symbol}" if symbol else ""
        raise NewsHistoryTooShort(
            f"historique de nouvelles trop court{where} : {status.span_sessions} séance(s) sur {MIN_SPAN_SESSIONS} requises, "
            f"{status.news_days} jour(s) avec nouvelles sur {MIN_NEWS_DAYS} (il manque {status.missing()})")
    return status
