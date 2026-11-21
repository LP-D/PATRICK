"""Nombres et dates écrits de toutes les façons qu'on rencontre dans les exports de banques, d'assureurs et de gestionnaires.

Nombres : « 1 234,56 € », « 1.234,56 », « 1,234.56 », « 1'234.5 », « 12,5 % », « (3,2) » (négatif), « −0,4 » (moins typographique),
« n.d. » / « - » / « #N/A » (vides). Le séparateur décimal se décide pour la COLONNE entière, pas cellule par cellule : « 1,234 » seul est
ambigu, la colonne ne l'est presque jamais.

Dates : objets date d'Excel, numéros de série Excel (45291 = 31/12/2023), ISO, « 31/12/2023 » (jour d'abord, sauf si la colonne prouve le
contraire avec un « 12/31/2023 »), « 31.12.23 », « 20231231 », « 2023-12 », « déc. 2023 », « 31 décembre 2023 », « Dec 31, 2023 »,
« T4 2023 » / « Q4 2023 », « 2023 » (une année). Les périodes (mois, trimestre, année) sont datées à leur dernier jour.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime

import numpy as np
import pandas as pd

MISSING = {"", "-", "--", "—", "–", "n.d.", "nd", "n/a", "na", "nan", "none", "null", "#n/a", "#n/d", "#value!", "#valeur!", "#div/0!", "s.o.", "x"}
CURRENCY_RE = re.compile(r"(eur|usd|gbp|chf|jpy|€|\$|£|¥)", re.IGNORECASE)
MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "january": 1, "fevrier": 2, "fevr": 2, "fev": 2, "feb": 2, "february": 2, "mars": 3, "mar": 3, "march": 3,
    "avril": 4, "avr": 4, "apr": 4, "april": 4, "mai": 5, "may": 5, "juin": 6, "jun": 6, "june": 6, "juillet": 7, "juil": 7, "jul": 7, "july": 7,
    "aout": 8, "aou": 8, "aug": 8, "august": 8, "septembre": 9, "sept": 9, "sep": 9, "september": 9, "octobre": 10, "oct": 10, "october": 10,
    "novembre": 11, "nov": 11, "november": 11, "decembre": 12, "dec": 12, "december": 12,
}
EXCEL_ORIGIN = pd.Timestamp("1899-12-30")
SERIAL_MIN, SERIAL_MAX = 18_264, 80_000          # 1950-01-01 .. 2119 : en dehors, un nombre n'est pas une date Excel plausible
YEAR_MIN, YEAR_MAX = 1950, 2100


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


# ------------------------------------------------------------------------------------------------ nombres

def _clean_number_text(s: str) -> tuple[str, bool, bool]:
    """`(texte réduit aux chiffres et séparateurs, était un pourcentage, était entre parenthèses)`."""
    t = s.strip().replace("−", "-").replace("–", "-").replace("\xa0", "").replace(" ", "").replace(" ", "")
    pct = "%" in t
    t = t.replace("%", "")
    t = CURRENCY_RE.sub("", t).replace(" ", "").replace("'", "").replace("’", "")
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    if t.endswith("-") and t[:-1].replace(",", "").replace(".", "").isdigit():
        t, neg = t[:-1], True       # « 12,5- » : notation comptable
    t = t.removeprefix("+")
    return t, pct, neg


def decimal_separator(texts: list[str]) -> str:
    """`,` ou `.` pour toute une colonne de nombres écrits en texte.

    Une cellule qui contient les deux tranche (le dernier est décimal). Sinon la virgule est décimale si une cellule a une virgule suivie d'un
    nombre de chiffres différent de 3, ou si aucune cellule n'a de point ; « 1,234 » seul dans une colonne sans autre indice reste décimal à la
    française (contexte de l'application)."""
    votes = {",": 0, ".": 0}
    has_dot = has_comma = False
    for t in texts:
        if "," in t and "." in t:
            votes["," if t.rfind(",") > t.rfind(".") else "."] += 3
            continue
        if "," in t:
            has_comma = True
            parts = t.split(",")
            if len(parts) > 2:
                votes["."] += 2          # « 1,234,567 » : virgules de milliers
            elif len(parts[1]) != 3:
                votes[","] += 1
        if "." in t:
            has_dot = True
            parts = t.split(".")
            if len(parts) > 2:
                votes[","] += 2          # « 1.234.567 » : points de milliers
            elif len(parts[1]) != 3:
                votes["."] += 1
    if votes[","] != votes["."]:
        return "," if votes[","] > votes["."] else "."
    if has_comma and not has_dot:
        return ","
    return "."


def to_numbers(values) -> tuple[pd.Series, dict]:
    """`(nombres, infos)` : infos = `{decimal, percent_share, parsed_share}`. Les cellules illisibles deviennent NaN."""
    s = pd.Series(list(values), dtype=object)
    out = np.full(len(s), np.nan)
    texts, positions, flags = [], [], []
    n_text = 0
    for i, v in enumerate(s):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float, np.integer, np.floating)):
            out[i] = float(v)
            continue
        if isinstance(v, (datetime, date, pd.Timestamp)):
            continue
        raw = str(v).strip()
        if raw.lower() in MISSING:
            continue
        n_text += 1
        t, pct, neg = _clean_number_text(raw)
        if not t or not re.fullmatch(r"-?[0-9.,]+(e[-+]?\d+)?", t, flags=re.IGNORECASE):
            continue
        texts.append(t)
        positions.append(i)
        flags.append((pct, neg))
    dec = decimal_separator(texts)
    thousands = "." if dec == "," else ","
    n_pct = 0
    for t, i, (pct, neg) in zip(texts, positions, flags):
        try:
            x = float(t.replace(thousands, "").replace(dec, "."))
        except ValueError:
            continue
        out[i] = -x if neg else x
        n_pct += pct
    non_empty = int(sum(1 for v in s if v is not None and not (isinstance(v, float) and math.isnan(v)) and str(v).strip().lower() not in MISSING))
    parsed = int(np.isfinite(out).sum())
    return pd.Series(out), {"decimal": dec, "percent_share": n_pct / max(len(texts), 1), "parsed_share": parsed / max(non_empty, 1), "text_cells": n_text}


# ------------------------------------------------------------------------------------------------ dates

def _month_end(y: int, m: int) -> pd.Timestamp:
    return pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)


def _year4(y: int) -> int:
    return y + (2000 if y < 70 else 1900) if y < 100 else y


def _valid(ts) -> pd.Timestamp | None:
    if ts is None or ts is pd.NaT:
        return None
    try:
        ts = pd.Timestamp(ts)
    except (ValueError, OverflowError, TypeError):
        return None
    if pd.isna(ts) or not YEAR_MIN <= ts.year <= YEAR_MAX:
        return None
    return ts.tz_localize(None).normalize() if ts.tzinfo else ts.normalize()


NUMERIC_DMY = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})(?:[ t]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)?$")
YM = re.compile(r"^(\d{4})[/.\-](\d{1,2})$")
MY = re.compile(r"^(\d{1,2})[/.\-](\d{4})$")
QUARTER = re.compile(r"^(?:t|q)([1-4])[ \-/]?(\d{2,4})$|^(\d{4})[ \-/]?(?:t|q)([1-4])$")
COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
YEAR = re.compile(r"^(\d{4})$")
WORDS = re.compile(r"[a-z]+|\d+")


def _parse_words(t: str) -> tuple[pd.Timestamp | None, str]:
    """« 31 déc. 2023 », « déc-23 », « Dec 31, 2023 », « décembre 2023 » ; `(date, granularité)`."""
    tokens = WORDS.findall(t)
    month = next((MONTHS[w] for w in tokens if w in MONTHS), None)
    if month is None:
        return None, ""
    nums = [int(w) for w in tokens if w.isdigit()]
    if not nums:
        return None, ""
    year_candidates = [n for n in nums if n >= 1000] or [nums[-1]]
    year = _year4(year_candidates[-1])
    days = [n for n in nums if n != year_candidates[-1] and 1 <= n <= 31]
    if days:
        try:
            return _valid(pd.Timestamp(year=year, month=month, day=days[0])), "day"
        except ValueError:
            return None, ""
    return _valid(_month_end(year, month)), "month"


def classify_date_text(t: str) -> tuple[str, tuple]:
    """Forme d'une date écrite (sans la convertir) : utilisée pour décider jour/mois sur toute la colonne."""
    m = NUMERIC_DMY.match(t)
    if m:
        return "dmy", tuple(int(x) for x in m.groups()[:3])
    for name, rx in (("ym", YM), ("my", MY), ("compact", COMPACT), ("year", YEAR)):
        m = rx.match(t)
        if m:
            return name, tuple(int(x) for x in m.groups())
    m = QUARTER.match(t)
    if m:
        g = m.groups()
        q, y = (int(g[0]), int(g[1])) if g[0] else (int(g[3]), int(g[2]))
        return "quarter", (q, _year4(y))
    return "other", ()


def to_dates(values, year_cells: bool = False) -> tuple[pd.Series, dict]:
    """`(dates, infos)` ; infos = `{parsed_share, granularity, dayfirst, serial}`.

    `year_cells=True` accepte qu'un entier entre 1950 et 2100 soit une année (colonne « Année » d'un tableau de taux) ; sinon un nombre n'est
    une date que s'il est un numéro de série Excel plausible."""
    s = list(values)
    out: list[pd.Timestamp | None] = [None] * len(s)
    shapes: list[tuple[int, str, tuple]] = []
    grains: dict[str, int] = {}
    n_serial = 0
    non_empty = 0
    for i, v in enumerate(s):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if isinstance(v, str) and v.strip().lower() in MISSING:
            continue
        non_empty += 1
        if isinstance(v, (datetime, pd.Timestamp)):
            out[i] = _valid(v)
            grains["day"] = grains.get("day", 0) + 1
            continue
        if isinstance(v, date):
            out[i] = _valid(pd.Timestamp(v))
            grains["day"] = grains.get("day", 0) + 1
            continue
        if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
            x = float(v)
            if year_cells and x.is_integer() and YEAR_MIN <= x <= YEAR_MAX:
                out[i] = pd.Timestamp(year=int(x), month=12, day=31)
                grains["year"] = grains.get("year", 0) + 1
            elif SERIAL_MIN <= x <= SERIAL_MAX:
                out[i] = _valid(EXCEL_ORIGIN + pd.Timedelta(days=int(x)))
                n_serial += 1
                grains["day"] = grains.get("day", 0) + 1
            continue
        t = _strip_accents(str(v).strip().lower()).replace(",", " ").strip()
        t = re.sub(r"\s+", " ", t)
        shape, parts = classify_date_text(t)
        shapes.append((i, shape, parts if shape != "other" else (t,)))
    # jour d'abord ou mois d'abord : décidé pour la colonne entière
    dmy = [p for _, sh, p in shapes if sh == "dmy" and p[0] <= 31]
    first_gt12 = sum(1 for p in dmy if p[0] > 12)
    second_gt12 = sum(1 for p in dmy if p[1] > 12)
    dayfirst = not (second_gt12 > 0 and first_gt12 == 0)
    for i, shape, p in shapes:
        ts, grain = None, "day"
        try:
            if shape == "dmy":
                a, b, c = p
                if a > 31:                                   # 2023/12/31
                    ts = pd.Timestamp(year=a, month=b, day=c)
                else:
                    d, m = (a, b) if dayfirst else (b, a)
                    ts = pd.Timestamp(year=_year4(c), month=m, day=d)
            elif shape == "ym":
                ts, grain = _month_end(p[0], p[1]), "month"
            elif shape == "my":
                ts, grain = _month_end(p[1], p[0]), "month"
            elif shape == "compact":
                ts = pd.Timestamp(year=p[0], month=p[1], day=p[2])
            elif shape == "year":
                if YEAR_MIN <= p[0] <= YEAR_MAX:
                    ts, grain = pd.Timestamp(year=p[0], month=12, day=31), "year"
            elif shape == "quarter":
                ts, grain = _month_end(p[1], 3 * p[0]), "quarter"
            else:
                ts, grain = _parse_words(p[0])
                if ts is None:
                    iso = re.match(r"^(\d{4}-\d{2}-\d{2})[t ]", p[0])
                    ts = pd.Timestamp(iso.group(1)) if iso else None
                    grain = "day"
        except (ValueError, OverflowError):
            ts = None
        ts = _valid(ts)
        if ts is not None:
            out[i] = ts
            grains[grain] = grains.get(grain, 0) + 1
    parsed = sum(1 for x in out if x is not None)
    granularity = max(grains, key=grains.get) if grains else ""
    series = pd.Series([x if x is not None else pd.NaT for x in out], dtype="datetime64[ns]")
    return series, {"parsed_share": parsed / max(non_empty, 1), "granularity": granularity, "dayfirst": dayfirst, "serial": n_serial > 0,
                    "non_empty": non_empty}


# ------------------------------------------------------------------------------------------------ codes ISIN

ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b")


def isin_valid(code: str) -> bool:
    """Clé de contrôle d'un ISIN (Luhn sur les chiffres obtenus en remplaçant chaque lettre par son rang + 9)."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", code or ""):
        return False
    digits = "".join(str(int(ch, 36)) for ch in code[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(code[-1])


def find_isin(text: str) -> str | None:
    for m in ISIN_RE.finditer((text or "").upper()):
        if isin_valid(m.group(1)):
            return m.group(1)
    return None
