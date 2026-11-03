"""Calendrier d'annonces d'un titre : horodatage Yahoo -> (date locale, BMO/AMC), saisie manuelle, jours macro.

Priorité des sources du timing : (1) l'utilisateur (`user`, jamais écrasé), (2) l'heure Yahoo reconvertie dans le fuseau de la
place (`yahoo_time`), (3) l'heuristique de la place (`heuristic`, toujours marquée incertaine), (4) rien (`UNKNOWN`). Sans
certitude, la fenêtre de réaction est [0, +1] et le drapeau « timing incertain » reste affiché sur toutes les statistiques.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

from patrick.earnings import exchanges
from patrick.earnings.config import EarningsConfig

TIMINGS = ("BMO", "AMC", "DURING", "UNKNOWN")

# Décisions du FOMC (jour de la décision, 14:00 à New York). Source : calendrier publié par la Réserve fédérale. À compléter
# chaque année ; une date absente n'est pas détectée (le contrôle est signalé « partiel » dans l'étude de recoupement).
FOMC_DECISIONS = (
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13", "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
)


def macro_days(start, end) -> dict[pd.Timestamp, str]:
    """Jours macro majeurs entre deux dates : décisions du FOMC (liste ci-dessus) et emploi américain (NFP, approximé au
    premier vendredi du mois : exact la plupart du temps, décalé les semaines de jour férié). L'inflation (CPI) n'a pas de règle
    fiable et gratuite : non couverte, et dit comme telle."""
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    out: dict[pd.Timestamp, str] = {}
    for d in FOMC_DECISIONS:
        ts = pd.Timestamp(d)
        if lo <= ts <= hi:
            out[ts] = "FOMC"
    for month in pd.period_range(lo, hi, freq="M"):
        first = month.start_time
        friday = first + pd.Timedelta(days=(4 - first.weekday()) % 7)
        if lo <= friday <= hi:
            out.setdefault(friday, "NFP~")
    return out


def calendar_rows(symbol: str, raw: pd.DataFrame, now=None) -> list[dict]:
    """Lignes `earn_calendar` d'un titre depuis `provider.calendar` (colonnes ts, eps_estimate, eps_actual, surprise_pct)."""
    rows: dict[str, dict] = {}
    for rec in raw.itertuples(index=False):
        info = exchanges.classify_timing(rec.ts, symbol)
        timing, source, uncertain, reason = info["timing"], "yahoo_time", info["uncertain"], info["reason"]
        ny = pd.Timestamp(rec.ts).tz_convert(exchanges.SOURCE_TZ) if pd.Timestamp(rec.ts).tzinfo is not None else None
        # Yahoo met 11:00 (New York) sur beaucoup de dates à venir dont l'heure n'est pas connue : constaté sur LVMH, Diageo, Interparfums, Air France.
        # Pour un événement pas encore publié, cette heure précise n'est pas une information.
        placeholder = ny is not None and (ny.hour, ny.minute) == (11, 0) and pd.isna(rec.eps_actual)
        if placeholder:
            timing = "UNKNOWN"
        if timing == "UNKNOWN":
            guess = exchanges.heuristic_timing(symbol)
            timing, source, uncertain = guess, "heuristic", True
            what = "heure provisoire de Yahoo (11:00 New York)" if placeholder else "heure absente"
            reason = f"{what} : repli « {guess} » par place de cotation" if guess != "UNKNOWN" else what
        row = {"symbol": symbol, "ann_date": info["local_date"].isoformat(), "ann_local_time": info["local_time"],
               "timing": timing, "timing_source": source, "uncertain": int(uncertain), "reason": reason,
               "eps_estimate": rec.eps_estimate, "eps_actual": rec.eps_actual, "surprise_pct": rec.surprise_pct, "source": "yahoo"}
        previous = rows.get(row["ann_date"])
        if previous is None or pd.isna(previous["eps_actual"]) or not pd.isna(row["eps_actual"]):
            rows[row["ann_date"]] = row
    return sorted(rows.values(), key=lambda r: r["ann_date"])


def user_override(row: dict, timing: str | None) -> dict:
    """Applique le timing choisi par l'utilisateur sur une ligne de calendrier (jamais écrasé ensuite par Yahoo)."""
    if not timing or timing.upper() == "AUTO":
        return row
    timing = timing.upper()
    if timing not in TIMINGS:
        raise ValueError(f"timing inconnu : {timing!r}")
    return {**row, "timing": timing, "timing_source": "user", "uncertain": int(timing in ("DURING", "UNKNOWN")),
            "reason": "choisi par l'utilisateur"}


_MANUAL = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})(?:[ T]+(\d{1,2}:\d{2}))?(?:\s+(BMO|AMC))?\s*$", re.IGNORECASE)


def parse_manual_dates(symbol: str, text: str) -> list[dict]:
    """Saisie manuelle de dates passées quand Yahoo n'en donne pas (Diageo, LVMH...) : une par ligne, `AAAA-MM-JJ [HH:MM] [BMO|AMC]`.
    L'heure est LOCALE à la place de cotation ; sans heure ni mention, le repli par place s'applique et le drapeau reste levé."""
    venue = exchanges.venue_for(symbol)
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = _MANUAL.match(line)
        if not m:
            raise ValueError(f"ligne illisible : {line.strip()!r} (attendu : AAAA-MM-JJ [HH:MM] [BMO|AMC])")
        day, clock, mention = m.group(1), m.group(2), (m.group(3) or "").upper()
        if mention:
            timing, uncertain, reason = mention, 0, "saisi à la main"
        elif clock:
            hh, mm = (int(x) for x in clock.split(":"))
            t = pd.Timestamp(f"{day} {hh:02d}:{mm:02d}").time()
            timing = "BMO" if t < venue.open else "AMC" if t >= exchanges.venue_close(venue, date.fromisoformat(day)) else "DURING"
            uncertain, reason = int(timing == "DURING"), "saisi à la main"
        else:
            timing = exchanges.heuristic_timing(symbol)
            uncertain, reason = 1, "heure absente : repli par place de cotation"
        rows.append({"symbol": symbol, "ann_date": day, "ann_local_time": clock or "", "timing": timing, "timing_source": "user",
                     "uncertain": uncertain, "reason": reason, "eps_estimate": None, "eps_actual": None,
                     "surprise_pct": None, "source": "manual"})
    return rows


def reaction_window(timing: str, uncertain: bool, cfg: EarningsConfig) -> tuple[int, int]:
    """Fenêtre de réaction immédiate en séances à partir de J0 : [0] si le timing est certain, [0, +1] sinon (ou si réglé ainsi)."""
    if cfg.reaction == "d0":
        return (0, 0)
    if cfg.reaction == "d01":
        return (0, 1)
    return (0, 1) if (uncertain or timing in ("DURING", "UNKNOWN")) else (0, 0)
