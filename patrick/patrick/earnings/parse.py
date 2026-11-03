"""Newsletter collée -> liste (jour, nom). Aucun réseau, aucune devinette sur les tickers (c'est `resolve.py`).

Le texte brut contient des en-têtes de jour (« Lundi », « 📅 Mardi 4 novembre : », « **Mercredi** ») suivis de noms séparés par des
virgules, sur la même ligne ou les suivantes. Sont reconnus : lundi à dimanche (le samedi existe : Berkshire publie le
samedi, la réaction est le lundi), les jours anglais, les puces, emojis et marques Markdown. Une parenthèse après un nom est
un INDICE conservé tel quel (« Novo Nordisk (Copenhague) », « Ryanair (ADR) », « Apple (AAPL) », « SAP (avant ouverture) »).

La date de chaque jour = lundi de référence + position du jour. Le lundi par défaut est celui de la semaine COURANTE
(`default_anchor_monday`) : une newsletter collée un mardi concerne cette semaine, pas la suivante. Champ modifiable à l'écran.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from patrick.clock import local_now

DAY_INDEX = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
             "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
             "lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6}
DAY_LABEL = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")

_BMO_WORDS = ("avant ouverture", "avant l'ouverture", "avant bourse", "pre-market", "premarket", "pre market", "bmo",
              "before open", "before the open", "matin")
_AMC_WORDS = ("apres cloture", "après clôture", "apres la cloture", "après la clôture", "apres bourse", "amc", "after close",
              "after the close", "after-market", "aftermarket", "soir")
_TICKER_HINT = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
_LEADING = re.compile(r"^[\s•▪►›·*_#>\-–—|•▪►›·]+|[\s•*_#]+$")
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")
_SPLIT = re.compile(r"[,;]|\s+[·•|]\s+|\n")
_STOP = {"", "et", "and", "etc", "etc.", "autres", "others", "…", "..."}
_LISTING_WORDS = {"adr": "adr", "us": "us", "usa": "us", "nyse": "us", "nasdaq": "us", "local": "local", "paris": "pa",
                  "dublin": "ir", "copenhague": "co", "copenhagen": "co", "londres": "l", "london": "l", "francfort": "de",
                  "xetra": "de", "milan": "mi", "madrid": "mc", "amsterdam": "as", "stockholm": "st", "zurich": "sw",
                  "tokyo": "t", "toronto": "to"}


@dataclass(frozen=True)
class ParsedItem:
    day_index: int
    day_label: str
    plan_date: date
    name: str
    hint: str = ""                      # texte de la parenthèse, tel quel
    timing_hint: str = ""               # BMO | AMC | ""
    listing_hint: str = ""              # adr | us | local | pa | ir | co ... | ""
    symbol_hint: str = ""               # ticker explicite entre parenthèses


@dataclass(frozen=True)
class ParseResult:
    items: list[ParsedItem]
    anchor: date
    ignored: list[str]                  # lignes de texte avant le premier jour (introduction)
    warnings: list[str]


def default_anchor_monday(today: date | None = None) -> date:
    """Lundi de la semaine courante (ISO). Pas de « prochain lundi » : collée un mardi, la liste est celle de la semaine en cours."""
    today = today or local_now().date()
    return today - timedelta(days=today.weekday())


def snap_to_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


_HEADER = re.compile(
    r"^\W*(?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|lun|mar|mer|jeu|ven|sam|dim)\b\.?(?P<date>\s*\(?\s*\d{1,2}(?:[/.]\d{1,2}(?:[/.]\d{2,4})?|\s+[^\W\d_]+\.?)?\)?)?"
    r"\s*[:\-–—]?\s*(?P<rest>.*)$", re.IGNORECASE)


def _clean_line(line: str) -> str:
    line = _EMOJI.sub(" ", line.replace(" ", " ").replace(" ", " "))
    line = re.sub(r"[*_`#]+", " ", line)
    return _LEADING.sub("", line).strip()


def _hint_fields(hint: str) -> tuple[str, str, str]:
    """(timing_hint, listing_hint, symbol_hint) d'un texte de parenthèse."""
    folded = _fold(hint)
    timing = "BMO" if any(_fold(w) in folded for w in _BMO_WORDS) else "AMC" if any(_fold(w) in folded for w in _AMC_WORDS) else ""
    listing = ""
    for word, code in _LISTING_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", folded):
            listing = code
            break
    symbol = hint.strip() if (not timing and not listing and _TICKER_HINT.match(hint.strip())) else ""
    return timing, listing, symbol


def _split_names(text: str) -> list[str]:
    """Découpe sur virgules/points-virgules sans casser une parenthèse (« Novo Nordisk (Copenhague, ADR) »)."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(depth - 1, 0)
        if depth == 0 and ch in ",;":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _item(raw: str, day_index: int, anchor: date) -> ParsedItem | None:
    raw = _LEADING.sub("", raw.strip())
    raw = re.sub(r"^(et|and)\s+", "", raw, flags=re.IGNORECASE).strip()
    hint = ""
    match = re.search(r"[(\[]([^)\]]*)[)\]]?\s*$", raw)
    if match and ("(" in raw or "[" in raw):
        hint = match.group(1).strip()
        raw = raw[:match.start()].strip()
    name = re.sub(r"\s+", " ", raw).strip(" .:-–—")
    if _fold(name) in _STOP or len(name) < 2:
        return None
    timing, listing, symbol = _hint_fields(hint) if hint else ("", "", "")
    return ParsedItem(day_index, DAY_LABEL[day_index], anchor + timedelta(days=day_index), name, hint, timing, listing, symbol)


def parse_newsletter(text: str, anchor: date | None = None) -> ParseResult:
    anchor = snap_to_monday(anchor) if anchor else default_anchor_monday()
    items: list[ParsedItem] = []
    ignored: list[str] = []
    warnings: list[str] = []
    current: int | None = None
    seen: set[tuple[int, str]] = set()
    for line in text.splitlines():
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        header = _HEADER.match(cleaned)
        rest = cleaned
        if header:
            current = DAY_INDEX[header.group("day").lower()]
            rest = header.group("rest")
        elif current is None:
            ignored.append(cleaned)
            continue
        for piece in _split_names(rest):
            item = _item(piece, current, anchor)
            if item and (item.day_index, _fold(item.name)) not in seen:
                seen.add((item.day_index, _fold(item.name)))
                items.append(item)
    if not items:
        warnings.append("aucun jour de la semaine suivi de noms n'a été reconnu")
    return ParseResult(items, anchor, ignored, warnings)
