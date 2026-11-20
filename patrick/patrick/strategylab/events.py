"""Listes d'événements : `DataFrame[symbol, at, entry_price, group]`, triée par date.

- `at` : date ou horodatage de PUBLICATION (jamais la date de l'histoire) ; le premier jour de bourse concerné est déterminé plus tard par
  `research.event_study.event_day_zero` (une annonce après la clôture ne peut agir que sur la séance suivante) ;
- `entry_price` : prix d'entrée imposé (prix d'offre d'une IPO), sinon NaN ;
- `group` : cohorte pour comparer des sous-ensembles (secteur, « beat / miss », période…), « tous » par défaut.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from patrick.placements import loader

MAX_EVENTS = 20_000
MAX_SYMBOLS = 250            # téléchargements Yahoo seulement : des cours importés n'ont pas cette limite (voir `prices.downloads_needed`)
SYMBOL_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.=^_\-]{0,22}$")
SYMBOL_NAMES = ("symbol", "ticker", "symbole")
DATE_NAMES = ("published_at", "at", "date", "event_date", "trade_date", "ipo_date", "priced_date", "date_evenement")
PRICE_NAMES = ("entry_price", "offer_price", "prix_offre", "prix_entree")
GROUP_NAMES = ("group", "cohort", "cohorte", "secteur", "sector", "groupe")


class EventsError(ValueError):
    """Liste d'événements illisible : le message (en français) est montré tel quel."""


def _pick(by_name: dict[str, str], names: tuple[str, ...]) -> str | None:
    return next((by_name[n] for n in names if n in by_name), None)


def parse_events_csv(data: bytes, source: str = "événements.csv") -> pd.DataFrame:
    """CSV d'événements : une colonne de symbole, une de date (les noms usuels sont reconnus), éventuellement un prix d'entrée et une cohorte.

    Les lignes sans symbole valide ou sans date lisible sont écartées (le décompte est dans `df.attrs["dropped"]`)."""
    import io
    head = data[:4096].decode("utf-8", errors="replace").lstrip("﻿").splitlines()
    first_line = head[0] if head else ""
    sep = max((",", ";", "\t", "|"), key=first_line.count)
    if first_line.count(sep) == 0:
        raise EventsError(f"{source} : il faut au moins une colonne de symbole et une colonne de date.")
    try:
        raw = pd.read_csv(io.BytesIO(data), sep=sep, encoding="utf-8-sig", encoding_errors="replace", dtype=str, on_bad_lines="skip")
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise EventsError(f"{source} : fichier CSV illisible ({exc}).") from exc
    by_name = {str(c).strip().lower(): c for c in raw.columns}
    sym_col, date_col = _pick(by_name, SYMBOL_NAMES), _pick(by_name, DATE_NAMES)
    if sym_col is None or date_col is None:
        raise EventsError(f"{source} : colonnes `symbol` (ou ticker) et `date` (ou published_at, trade_date…) introuvables.")
    price_col, group_col = _pick(by_name, PRICE_NAMES), _pick(by_name, GROUP_NAMES)
    out = pd.DataFrame({
        "symbol": raw[sym_col].astype(str).str.strip().str.upper(),
        "at": loader.to_dates(raw[date_col]),
        "entry_price": loader.to_number(raw[price_col]) if price_col else float("nan"),
        "group": raw[group_col].fillna("").astype(str).str.strip().replace("", "tous") if group_col else "tous",
    })
    valid = out["symbol"].str.match(SYMBOL_RE) & out["at"].notna()
    dropped = int((~valid).sum())
    out = out[valid].sort_values("at", kind="stable").reset_index(drop=True)
    if out.empty:
        raise EventsError(f"{source} : aucun événement exploitable ({dropped} lignes écartées).")
    if len(out) > MAX_EVENTS:
        raise EventsError(f"{source} : {len(out)} événements, au plus {MAX_EVENTS} sont acceptés.")
    out.attrs["dropped"] = dropped
    return out


# ---- préréglages
# Keynotes iPhone (heure de Cupertino, d'après `STRAT BTR-STN/apple_event_study_2.ipynb`) : 10 h, heure du Pacifique, sauf 2007 (9 h).
APPLE_KEYNOTES: tuple[tuple[str, str, str], ...] = (
    ("2007-01-09", "09:00", "Premier iPhone"), ("2008-06-09", "10:00", "iPhone 3G"), ("2009-06-08", "10:00", "iPhone 3GS"),
    ("2010-06-07", "10:00", "iPhone 4"), ("2011-10-04", "10:00", "iPhone 4S"), ("2012-09-12", "10:00", "iPhone 5"),
    ("2013-09-10", "10:00", "iPhone 5S / 5C"), ("2014-09-09", "10:00", "iPhone 6"), ("2015-09-09", "10:00", "iPhone 6S"),
    ("2016-09-07", "10:00", "iPhone 7"), ("2017-09-12", "10:00", "iPhone X / 8"), ("2018-09-12", "10:00", "iPhone XS / XR"),
    ("2019-09-10", "10:00", "iPhone 11"), ("2020-10-13", "10:00", "iPhone 12"), ("2021-09-14", "10:00", "iPhone 13"),
    ("2022-09-07", "10:00", "iPhone 14"), ("2023-09-12", "10:00", "iPhone 15"), ("2024-09-09", "10:00", "iPhone 16"),
)


def apple_keynotes() -> pd.DataFrame:
    """Les keynotes iPhone converties en heure de New York (la Bourse) : toutes tombent en séance, donc le jour 0 est le jour même."""
    pacific, new_york = ZoneInfo("America/Los_Angeles"), ZoneInfo("America/New_York")
    at = [pd.Timestamp(f"{d} {t}").tz_localize(pacific).tz_convert(new_york).tz_localize(None) for d, t, _ in APPLE_KEYNOTES]
    out = pd.DataFrame({"symbol": "AAPL", "at": at, "entry_price": float("nan"), "group": "keynote iPhone"})
    out.attrs["dropped"] = 0
    return out


PRESETS: dict[str, Callable[[], pd.DataFrame]] = {"apple_keynotes": apple_keynotes}


def yahoo_earnings_events(symbols: list[str], limit: int = 40, fetch: Callable | None = None) -> pd.DataFrame:
    """Résultats trimestriels publiés (horodatage Yahoo : après la clôture = 16 h 00 New York, géré par `event_day_zero`), groupés beat / miss / en ligne.

    `fetch(symbol, limit)` renvoie `DataFrame[published_at, label, group]` (par défaut `research.event_sources.yahoo_earnings`) ; un titre en échec est
    ignoré et listé dans `df.attrs["failed"]`."""
    if fetch is None:
        from patrick.research.event_sources import yahoo_earnings
        fetch = yahoo_earnings
    frames, failed = [], []
    for sym in symbols:
        try:
            ev = fetch(sym, limit)
        except Exception:  # noqa: BLE001 -- fournisseur externe : un titre en échec ne doit pas arrêter les autres
            failed.append(sym)
            continue
        if ev is None or ev.empty:
            failed.append(sym)
            continue
        at = pd.to_datetime(ev["published_at"], utc=True, errors="coerce").dt.tz_convert("America/New_York").dt.tz_localize(None)
        frames.append(pd.DataFrame({"symbol": sym, "at": at, "entry_price": float("nan"), "group": ev["group"].values}))
    if not frames:
        raise EventsError("Aucun résultat trimestriel récupéré : vérifiez les symboles et la connexion.")
    out = pd.concat(frames, ignore_index=True).dropna(subset=["at"]).sort_values("at", kind="stable").reset_index(drop=True)
    out.attrs["dropped"] = 0
    out.attrs["failed"] = failed
    return out


def parse_symbols(text: str) -> list[str]:
    """`"AAPL, msft ; ^GSPC"` -> `["AAPL", "MSFT", "^GSPC"]` (symboles valides seulement, sans doublon, ordre conservé)."""
    seen: dict[str, None] = {}
    for token in re.split(r"[\s,;]+", text or ""):
        token = token.strip().upper()
        if token and SYMBOL_RE.match(token):
            seen.setdefault(token)
    return list(seen)[:MAX_SYMBOLS]
