"""Places de cotation : fuseau, horaires, indice local, région des facteurs, et jour de réaction J0.

Piège confirmé sur Yahoo (2026-11-03) : `Ticker.get_earnings_dates` renvoie TOUS les horodatages en heure de New York, y
compris pour Paris, Copenhague ou Tokyo (Novo Nordisk à 07:00 CET sort en `01:00-05:00`). Lire l'heure telle quelle classerait
à tort une publication européenne avant l'ouverture américaine ; `classify_timing` reconvertit dans le fuseau de la place.

J0 est le jour de RÉACTION (première séance dont le cours intègre la nouvelle), pas le jour de l'annonce :
- avant l'ouverture (BMO) ou un jour sans séance (samedi, férié) -> première séance à partir du jour de l'annonce ;
- après la clôture (AMC) -> première séance strictement après le jour de l'annonce ;
- pendant la séance ou heure inconnue -> le jour même, mais la réaction déborde sur J+1 : fenêtre [0, +1] et drapeau.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

import pandas as pd

SOURCE_TZ = "America/New_York"          # fuseau des horodatages Yahoo, quelle que soit la place


@dataclass(frozen=True)
class Venue:
    key: str
    tz: str
    open: time
    close: time
    benchmarks: tuple[str, ...]         # indice local d'abord, replis ensuite
    region: str                         # US | EU | JP | OTHER (jeu de facteurs Ken French)
    currency: str
    country: str


_EU_TAIL = ("^STOXX",)
VENUES: dict[str, Venue] = {
    "": Venue("us", "America/New_York", time(9, 30), time(16, 0), ("^GSPC",), "US", "USD", "États-Unis"),
    "PA": Venue("pa", "Europe/Paris", time(9, 0), time(17, 30), ("^FCHI", *_EU_TAIL), "EU", "EUR", "France"),
    "AS": Venue("as", "Europe/Amsterdam", time(9, 0), time(17, 30), ("^AEX", *_EU_TAIL), "EU", "EUR", "Pays-Bas"),
    "BR": Venue("br", "Europe/Brussels", time(9, 0), time(17, 30), ("^BFX", *_EU_TAIL), "EU", "EUR", "Belgique"),
    "LS": Venue("ls", "Europe/Lisbon", time(8, 0), time(16, 30), _EU_TAIL, "EU", "EUR", "Portugal"),
    "DE": Venue("de", "Europe/Berlin", time(9, 0), time(17, 30), ("^GDAXI", *_EU_TAIL), "EU", "EUR", "Allemagne"),
    "F": Venue("f", "Europe/Berlin", time(8, 0), time(20, 0), ("^GDAXI", *_EU_TAIL), "EU", "EUR", "Allemagne"),
    "L": Venue("l", "Europe/London", time(8, 0), time(16, 30), ("^FTSE", *_EU_TAIL), "EU", "GBP", "Royaume-Uni"),
    "IR": Venue("ir", "Europe/Dublin", time(8, 0), time(16, 30), ("^ISEQ", *_EU_TAIL), "EU", "EUR", "Irlande"),
    "MI": Venue("mi", "Europe/Rome", time(9, 0), time(17, 30), ("FTSEMIB.MI", *_EU_TAIL), "EU", "EUR", "Italie"),
    "MC": Venue("mc", "Europe/Madrid", time(9, 0), time(17, 30), ("^IBEX", *_EU_TAIL), "EU", "EUR", "Espagne"),
    "CO": Venue("co", "Europe/Copenhagen", time(9, 0), time(17, 0), ("^OMXC25", *_EU_TAIL), "EU", "DKK", "Danemark"),
    "ST": Venue("st", "Europe/Stockholm", time(9, 0), time(17, 30), ("^OMX", *_EU_TAIL), "EU", "SEK", "Suède"),
    "HE": Venue("he", "Europe/Helsinki", time(10, 0), time(18, 30), ("^OMXH25", *_EU_TAIL), "EU", "EUR", "Finlande"),
    "OL": Venue("ol", "Europe/Oslo", time(9, 0), time(16, 20), ("OSEBX.OL", *_EU_TAIL), "EU", "NOK", "Norvège"),
    "SW": Venue("sw", "Europe/Zurich", time(9, 0), time(17, 30), ("^SSMI", *_EU_TAIL), "EU", "CHF", "Suisse"),
    "VI": Venue("vi", "Europe/Vienna", time(9, 0), time(17, 30), ("^ATX", *_EU_TAIL), "EU", "EUR", "Autriche"),
    "T": Venue("t", "Asia/Tokyo", time(9, 0), time(15, 30), ("^N225",), "JP", "JPY", "Japon"),
    "HK": Venue("hk", "Asia/Hong_Kong", time(9, 30), time(16, 0), ("^HSI",), "OTHER", "HKD", "Hong Kong"),
    "TO": Venue("to", "America/Toronto", time(9, 30), time(16, 0), ("^GSPTSE",), "OTHER", "CAD", "Canada"),
    "AX": Venue("ax", "Australia/Sydney", time(10, 0), time(16, 0), ("^AXJO",), "OTHER", "AUD", "Australie"),
}
FALLBACK_BENCHMARK = "^GSPC"
_TOKYO_CLOSE_CHANGE = date(2024, 11, 5)  # la Bourse de Tokyo a prolongé sa séance de 15:00 à 15:30


def suffix_of(symbol: str) -> str:
    """Suffixe de place d'un symbole Yahoo (`NOVO-B.CO` -> `CO`, `AAPL` -> ``, `BRK-B` -> ``, `BF.B` -> ``)."""
    if "." not in symbol:
        return ""
    tail = symbol.rsplit(".", 1)[1].upper()
    return tail if tail in VENUES else ""


def venue_for(symbol: str) -> Venue:
    return VENUES[suffix_of(symbol)]


def is_us(symbol: str) -> bool:
    return suffix_of(symbol) == ""


def venue_close(venue: Venue, day: date) -> time:
    if venue.key == "t" and day < _TOKYO_CLOSE_CHANGE:
        return time(15, 0)
    return venue.close


def classify_timing(ts, symbol: str) -> dict:
    """Classe une publication Yahoo : BMO, AMC, DURING (pendant la séance) ou UNKNOWN (heure absente).

    `ts` : horodatage tz-aware (Yahoo, heure de New York) ; naïf = déjà heure locale de la place, sans heure connue si 00:00.
    Renvoie `{timing, local_date, local_time, uncertain, reason}`. Minuit pile à New York = heure absente (jamais une vraie
    publication) : timing UNKNOWN, incertain."""
    venue = venue_for(symbol)
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        local = stamp
        time_known = bool(stamp.hour or stamp.minute)
    else:
        time_known = not (stamp.tz_convert(SOURCE_TZ).hour == 0 and stamp.tz_convert(SOURCE_TZ).minute == 0)
        local = stamp.tz_convert(venue.tz).tz_localize(None)
    day = local.date()
    if not time_known:
        return {"timing": "UNKNOWN", "local_date": day, "local_time": "", "uncertain": True, "reason": "heure absente"}
    t = local.time()
    if t < venue.open:
        timing, uncertain, reason = "BMO", False, ""
    elif t >= venue_close(venue, day):
        timing, uncertain, reason = "AMC", False, ""
    else:
        timing, uncertain, reason = "DURING", True, "publication pendant la séance"
    return {"timing": timing, "local_date": day, "local_time": t.strftime("%H:%M"), "uncertain": uncertain, "reason": reason}


def heuristic_timing(symbol: str) -> str:
    """Repli sans heure connue, par place : les émetteurs européens publient avant l'ouverture, les japonais après la
    clôture ; aux États-Unis (mélange de BMO et d'AMC) il n'y a pas de défaut honnête : UNKNOWN."""
    region = venue_for(symbol).region
    if region == "EU":
        return "BMO"
    if region == "JP":
        return "AMC"
    return "UNKNOWN"


def day_zero(ann_date, timing: str, sessions: pd.DatetimeIndex) -> pd.Timestamp | None:
    """Jour de réaction J0 : voir la docstring du module. `sessions` : séances (normalisées, triées). None au-delà."""
    days = pd.DatetimeIndex(sessions).normalize()
    day = pd.Timestamp(ann_date).normalize()
    pos = days.searchsorted(day, side="right" if timing == "AMC" else "left")
    return days[pos] if pos < len(days) else None


def project_sessions(sessions: pd.DatetimeIndex, until) -> pd.DatetimeIndex:
    """Séances connues prolongées par des jours ouvrés jusqu'à `until` (calendrier à venir, fériés ignorés)."""
    days = pd.DatetimeIndex(sessions).normalize()
    until = pd.Timestamp(until).normalize()
    if not len(days) or days[-1] >= until:
        return days
    extra = pd.bdate_range(days[-1] + pd.Timedelta(days=1), until)
    return days.append(extra)


def benchmark_candidates(symbol: str) -> tuple[str, ...]:
    return (*venue_for(symbol).benchmarks, FALLBACK_BENCHMARK)


SECTOR_ETF_US = {
    "Technology": "XLK", "Healthcare": "XLV", "Financial Services": "XLF", "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP", "Energy": "XLE", "Industrials": "XLI", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB", "Communication Services": "XLC",
}
