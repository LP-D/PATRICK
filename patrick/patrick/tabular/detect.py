"""Trouver les séries datées dans n'importe quelle grille de cellules, deviner ce qu'elles mesurent et les rendre comparables.

Mises en page reconnues :
- tableau large : une colonne de dates, une colonne par support (en-tête = nom du support, de son ISIN ou générique « VL ») ;
- blocs côte à côte : « Date | VL | Date | VL » (exports de comparateurs), chaque bloc a ses propres dates ;
- format long : une ligne par date et par support (`date ; fonds ; valeur`), éventuellement trié par fonds puis par date ;
- tableau transposé : les dates en ligne, un support par ligne ;
- titre au-dessus du tableau (« Liste des valeurs liquidatives du fonds X en date du… »), lignes vides, en-têtes sur deux lignes,
  tableau du plus récent au plus ancien.

Ce que mesurent les valeurs (`KINDS`) : un cours ou une VL, un indice base 100, une performance périodique (en % ou en décimal), une
performance cumulée, ou un taux annuel (fonds en euros, livret). Les indices des en-têtes (« perf. », « % », « cumul », « taux ») passent
avant la forme des nombres ; quand seule la forme décide, la confiance baisse et la note le dit : l'utilisateur peut corriger le type,
`levels` recalcule l'indice à partir des valeurs brutes conservées.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from patrick.tabular import parse, reader

KINDS = ("price", "base100", "return_pct", "return_dec", "cum_pct", "cum_dec", "annual_rate")
MIN_POINTS = 6
MIN_RATE_POINTS = 2
SAMPLE_ROWS = 400
GENERIC = {
    "vl", "nav", "valeur liquidative", "valeurs liquidatives", "valeur", "valeurs", "value", "values", "cours", "cours de cloture", "cloture",
    "close", "adj close", "adjusted close", "prix", "price", "dernier", "last", "montant", "performance", "perf", "rendement", "variation",
    "taux", "taux servi", "rate", "indice", "index", "base 100", "valeur part", "valeur de la part", "valeur de part", "vl en euros", "vl (eur)", "vl eur",
    "date", "dates", "periode", "mois", "annee", "year", "unnamed", "colonne", "column",
}
DEFAULT_SHEETS = re.compile(r"^(feuil|sheet|feuille|tableau|table|onglet|blad|hoja)\s*\d*$", re.IGNORECASE)
TITLE_PREFIX = re.compile(
    r"^(liste des valeurs liquidatives (du|de la|des) (fonds|support|fcpe|sicav)?|historique (des|de la) (vl|valeurs? liquidatives?|cours)( (du|de|de la))?|"
    r"valeurs? liquidatives?( (du|de|de la))?( fonds)?|cours (du|de|de la)|evolution (du|de|de la)|performances? (du|de|de la))\s*", re.IGNORECASE)
TITLE_SUFFIX = re.compile(r"\s*(en date du|au|du|arr[eê]t[eé]e? au|as of)\s+\d.*$", re.IGNORECASE)
ID_HINTS = ("fonds", "support", "fund", "isin", "code", "libelle", "nom", "name", "symbol", "symbole", "ticker", "produit", "instrument")
PRICE_HINTS = ("adj close", "close", "cloture", "vl", "nav", "valeur liquidative", "valeur", "cours", "prix", "price", "value", "dernier", "last")
RETURN_HINTS = ("perf", "rendement", "variation", "var.", "var ", "return", "evolution", "%")
CUM_HINTS = ("cumul", "depuis", "since", "cumulative", "ytd", "total")
RATE_HINTS = ("taux", "rate", "remuneration", "rendement annuel", "taux servi", "participation aux benefices", "pb")
BASE100_HINTS = ("base 100", "base100", "indice", "index")
FREQ_PLURAL = {"daily": "quotidiennes", "weekly": "hebdomadaires", "monthly": "mensuelles", "quarterly": "trimestrielles", "annual": "annuelles",
               "irregular": "irrégulières"}
FREQ_LABELS = {"daily": "quotidienne", "weekly": "hebdomadaire", "monthly": "mensuelle", "quarterly": "trimestrielle", "annual": "annuelle",
               "irregular": "irrégulière"}


@dataclass
class Found:
    """Une série trouvée : valeurs brutes (index = dates croissantes), type deviné, d'où elle vient et ce qui a été supposé."""
    name: str
    raw: pd.Series
    kind: str
    frequency: str
    sheet: str
    column: str
    isin: str | None = None
    notes: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def levels(self) -> pd.Series:
        return levels(self.raw, self.kind)

    def describe(self) -> dict:
        lv = self.levels()
        return {"name": self.name, "kind": self.kind, "frequency": self.frequency, "frequency_label": FREQ_LABELS.get(self.frequency, self.frequency),
                "sheet": self.sheet, "column": self.column, "isin": self.isin, "notes": list(self.notes), "confidence": round(float(self.confidence), 2),
                "start": lv.index[0].date().isoformat(), "end": lv.index[-1].date().isoformat(), "points": len(lv)}


class DetectError(ValueError):
    """Aucune série exploitable : le message dit ce qui manque."""


def norm(text) -> str:
    t = parse._strip_accents(str(text or "")).lower().strip()
    return re.sub(r"\s+", " ", t)


FILLER = re.compile(r"\b(mensuelles?|annuelles?|hebdomadaires?|quotidiennes?|journalieres?|trimestrielles?|monthly|weekly|daily|annual|yearly|"
                    r"en|in|eur|euros?|usd|nette?s?|brute?s?|de|du|la|le|des|the|of)\b|%")


def is_generic(text: str) -> bool:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", norm(text)).strip(" :.-_()[]")
    reduced =re.sub(r"\s+", " ", FILLER.sub(" ", t)).strip(" :.-_()[]")
    return (not t or t in GENERIC or reduced in GENERIC or not reduced or t.startswith("unnamed")
            or bool(re.fullmatch(r"(col(onne)?|column)?\s*\d+", t)))


def pretty(stem: str) -> str:
    """`groupama_euro_credit` -> `Groupama Euro Credit` (nom de fichier en minuscules) ; un nom déjà mis en forme est gardé."""
    t = re.sub(r"[_]+", " ", stem or "").strip()
    return t.title() if t == t.lower() else t


def clean_title(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = TITLE_SUFFIX.sub("", TITLE_PREFIX.sub("", t)).strip(" :-–—")
    return t[:120]


# ------------------------------------------------------------------------------------------------ conversion en niveaux

def period_days(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 365.0
    return float(np.median(np.diff(index.values).astype("timedelta64[D]").astype(float)))


def frequency(index: pd.DatetimeIndex) -> str:
    d = period_days(index)
    if d <= 4.5:
        return "daily"
    if d <= 10:
        return "weekly"
    if d <= 45:
        return "monthly"
    if d <= 120:
        return "quarterly"
    if d <= 400:
        return "annual"
    return "irregular"


def levels(raw: pd.Series, kind: str) -> pd.Series:
    """Niveaux comparables (cours ou indice base 100) à partir des valeurs brutes et de leur type."""
    raw = raw.dropna().sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    if kind in ("price", "base100"):
        return raw.astype(float)
    if kind == "annual_rate":
        rates = raw / 100 if (raw.abs() > 0.5).any() else raw
        start = pd.Timestamp(year=rates.index[0].year - 1, month=12, day=31)
        now = pd.Timestamp.today().normalize() + pd.offsets.MonthEnd(0)      # pas de points dans le futur (taux de l'année en cours)
        points, level = [(start, 100.0)], 100.0
        for ts, r in rates.items():
            monthly = (1 + float(r)) ** (1 / 12)
            for m in range(1, 13):
                when = pd.Timestamp(year=ts.year, month=m, day=1) + pd.offsets.MonthEnd(0)
                if when > now:
                    break
                level *= monthly
                points.append((when, level))
        s = pd.Series(dict(points)).sort_index()
        return s.astype(float)
    if kind in ("return_pct", "return_dec"):
        r = raw / 100 if kind == "return_pct" else raw
        idx = 100 * (1 + r).cumprod()
        first = raw.index[0] - pd.Timedelta(days=max(1.0, round(period_days(raw.index))))
        return pd.concat([pd.Series([100.0], index=[first]), idx]).astype(float)
    if kind in ("cum_pct", "cum_dec"):
        c = raw / 100 if kind == "cum_pct" else raw
        return (100 * (1 + c)).astype(float)
    raise ValueError(f"type de valeurs inconnu : {kind}")


# ------------------------------------------------------------------------------------------------ type des valeurs

def _autocorr(x: np.ndarray) -> float:
    if len(x) < 4 or np.std(x) == 0:
        return 0.0
    a, b = x[:-1] - x[:-1].mean(), x[1:] - x[1:].mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den else 0.0


def guess_kind(values: pd.Series, header: str, freq: str, percent_share: float) -> tuple[str, float, str]:
    """`(type, confiance, note)` des valeurs d'une colonne."""
    x = values.dropna().to_numpy(dtype=float)
    h = norm(header)
    has = lambda hints: any(k in h for k in hints)
    pct_unit = percent_share > 0.5 or "%" in h or (np.abs(x).max() > 1.5 if len(x) else False)      # « (%) » dans l'en-tête : unité explicite
    if freq in ("annual", "irregular") and (has(RATE_HINTS) or percent_share > 0.5) and len(x) and np.abs(x).max() <= 25:
        return "annual_rate", 0.9, "taux annuels (fonds en euros, livret) : capitalisés mois par mois"
    if has(CUM_HINTS) and (has(RETURN_HINTS) or percent_share > 0.5):
        return ("cum_pct" if pct_unit else "cum_dec"), 0.85, "performances cumulées depuis le début (converties en indice base 100)"
    if has(BASE100_HINTS) and (x > 0).all():
        return "base100", 0.95, "indice base 100"
    if has(RETURN_HINTS) or percent_share > 0.5:
        if (x > 0).all() and _autocorr(x) > 0.95 and np.median(x) > 20:
            return "price", 0.6, "en-tête évoquant une performance, mais les valeurs ressemblent à des cours"
        return ("return_pct" if pct_unit else "return_dec"), 0.85, (f"performances {FREQ_PLURAL.get(freq, '')} en {'%' if pct_unit else 'décimal'} "
                                                                      "(converties en indice base 100)")
    if (x > 0).all():
        ac = _autocorr(x)
        if x.max() < 2 and ac < 0.5:
            unit = "%" if x.max() > 0.2 else "décimal"
            return ("return_pct" if unit == "%" else "return_dec"), 0.5, f"petites valeurs sans tendance : lues comme des performances en {unit} (à vérifier)"
        return "price", 0.95 if ac > 0.8 or len(x) < 8 else 0.75, ""
    ac = _autocorr(x)
    if ac > 0.9:
        return ("cum_pct" if pct_unit else "cum_dec"), 0.6, "valeurs signées qui évoluent lentement : lues comme des performances cumulées (à vérifier)"
    return ("return_pct" if pct_unit else "return_dec"), 0.65, f"valeurs signées : lues comme des performances en {'%' if pct_unit else 'décimal'} (à vérifier)"


# ------------------------------------------------------------------------------------------------ structure de la grille

def _trim(grid: pd.DataFrame) -> pd.DataFrame:
    def empty(v) -> bool:
        return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())
    mask = grid.map(empty)
    grid = grid.loc[~mask.all(axis=1), ~mask.all(axis=0)]
    return grid.reset_index(drop=True).T.reset_index(drop=True).T


def _is_text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _date_score(cells: list, year_hint: bool) -> tuple[float, int, dict]:
    sample = cells[:SAMPLE_ROWS]
    dates, info = parse.to_dates(sample, year_cells=year_hint)
    valid = dates.dropna()
    n = len(valid)
    if n < MIN_RATE_POINTS:
        return 0.0, n, info
    diffs = np.diff(valid.values).astype("timedelta64[D]").astype(float)
    up, down = (diffs > 0).mean() if len(diffs) else 1, (diffs < 0).mean() if len(diffs) else 0
    monotone = max(up, down)
    if info["granularity"] == "year" and n >= 2:
        steps = np.abs(np.diff(valid.dt.year.values))
        if not ((steps >= 1) & (steps <= 2)).mean() >= 0.8:
            return 0.0, n, info
    if info["serial"] and not year_hint:
        nums = pd.to_numeric(pd.Series(sample), errors="coerce").dropna()
        if len(nums) and (nums % 1 != 0).mean() > 0.2:      # des décimales : des cours, pas des numéros de série
            return 0.0, n, info
    score = info["parsed_share"] * (0.5 + 0.5 * monotone) if monotone >= 0.75 else 0.0
    return score, n, info


def _year_hint(cells: list) -> bool:
    return any(_is_text(v) and norm(v) in ("annee", "annees", "year", "years", "exercice", "an", "millesime") for v in cells[:12])


def date_columns(grid: pd.DataFrame) -> list[tuple[int, dict]]:
    out = []
    for j in grid.columns:
        cells = list(grid[j])
        score, n, info = _date_score(cells, _year_hint(cells))
        if score >= 0.55 and (n >= MIN_POINTS or (info["granularity"] == "year" and n >= MIN_RATE_POINTS)):
            out.append((j, {**info, "score": score, "n": n}))
    return out


def _first_row(cells: list, year_hint: bool) -> int:
    dates, _ = parse.to_dates(cells, year_cells=year_hint)
    valid = dates.notna().to_numpy()
    return int(np.argmax(valid)) if valid.any() else 0


def _title_of(grid: pd.DataFrame, top_row: int) -> str:
    """Le titre au-dessus du tableau : la plus longue cellule de texte non générique des lignes d'en-tête."""
    best = ""
    for r in range(min(top_row, 12)):
        for v in grid.iloc[r]:
            if _is_text(v) and not is_generic(v) and len(str(v)) > len(best) and not parse.to_dates([v])[1]["parsed_share"]:
                best = str(v)
    return clean_title(best)


def _header_name(grid: pd.DataFrame, col: int, r0: int, left: int) -> tuple[str, str]:
    """`(nom, en-tête brut)` d'une colonne de valeurs : le texte non générique le plus proche au-dessus de la première date, en remontant la
    colonne puis vers la gauche jusqu'à la colonne des dates (cellule fusionnée au-dessus d'un bloc)."""
    raw_header = ""
    for r in range(r0 - 1, max(-1, r0 - 7), -1):
        v = grid.iat[r, col]
        if _is_text(v):
            if not raw_header:
                raw_header = str(v)
            if not is_generic(v):
                return clean_title(str(v)), raw_header
    for r in range(r0 - 1, max(-1, r0 - 7), -1):
        for c in range(col - 1, left - 1, -1):
            v = grid.iat[r, c]
            if _is_text(v) and not is_generic(v):
                return clean_title(str(v)), raw_header
    return "", raw_header


def _series(dates: pd.Series, values: pd.Series) -> pd.Series:
    frame = pd.DataFrame({"d": dates.to_numpy(), "v": values.to_numpy()}).dropna()
    s = pd.Series(frame["v"].to_numpy(dtype=float), index=pd.DatetimeIndex(frame["d"]))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def _finish(name: str, raw: pd.Series, header: str, percent_share: float, sheet: str, column: str, notes: list[str], base_conf: float,
            isin: str | None) -> Found | None:
    freq = frequency(raw.index)
    kind, conf, note = guess_kind(raw, header, freq, percent_share)
    minimum = MIN_RATE_POINTS if kind == "annual_rate" else MIN_POINTS
    if len(raw) < minimum or (kind in ("price", "base100") and raw.nunique() < 2):      # un « cours » constant est une colonne de quantités
        return None
    notes = list(notes) + ([note] if note else [])
    try:
        lv = levels(raw, kind)
    except (ValueError, OverflowError):
        return None
    if not np.isfinite(lv.to_numpy()).all() or (lv <= 0).any():
        if kind == "price":
            return None
        notes.append("indice négatif après conversion : type à corriger")
        conf *= 0.5
    return Found(name=name, raw=raw, kind=kind, frequency=freq, sheet=sheet, column=column, isin=isin, notes=notes, confidence=base_conf * conf)


def _fallback_name(sheet: str, filename: str, title: str, count: int, index: int) -> tuple[str, str]:
    stem = pretty((filename or "").rsplit(".", 1)[0])
    if title:
        base, how = title, "nom tiré du titre au-dessus du tableau"
    elif sheet and not DEFAULT_SHEETS.match(sheet.strip()) and norm(pretty(sheet)) != norm(stem):
        base, how = sheet, "nom tiré de l'onglet"
    else:
        base, how = stem or "Série", "nom tiré du nom du fichier"
    return (base if count == 1 else f"{base} ({index + 1})"), how


def _long_format(grid: pd.DataFrame, dcol: int, r0: int, sheet: str, notes: list[str]) -> list[Found]:
    body = grid.iloc[r0:]
    dates, _ = parse.to_dates(list(body[dcol]))
    valid = dates.notna()
    if valid.sum() < MIN_POINTS:
        return []
    header = {c: norm(grid.iat[r0 - 1, c]) if r0 > 0 else "" for c in grid.columns}
    id_col, best = None, -1.0
    for c in grid.columns:
        if c == dcol:
            continue
        col = body[c][valid.to_numpy()]
        nums, info = parse.to_numbers(list(col))
        if info["parsed_share"] > 0.5:
            continue
        distinct = col.astype(str).str.strip().nunique()
        if 2 <= distinct <= 500:
            score = (2.0 if any(k in header[c] for k in ID_HINTS) else 1.0) - distinct / 1000
            if score > best:
                id_col, best = c, score
    if id_col is None:
        return []
    value_col, best = None, -1.0
    for c in grid.columns:
        if c in (dcol, id_col):
            continue
        nums, info = parse.to_numbers(list(body[c][valid.to_numpy()]))
        if info["parsed_share"] < 0.8:
            continue
        hint = next((len(PRICE_HINTS) - i for i, k in enumerate(PRICE_HINTS) if k in header[c]), 0)
        if hint > best:
            value_col, best = c, hint
    if value_col is None:
        return []
    out = []
    ids = body[id_col].astype(str).str.strip()
    for ident in ids[valid.to_numpy()].unique():
        mask = (ids == ident).to_numpy() & valid.to_numpy()
        nums, info = parse.to_numbers(list(body[value_col][mask]))
        raw = _series(dates[mask].reset_index(drop=True), nums)
        isin = parse.find_isin(ident)
        found = _finish(ident, raw, header[value_col], info["percent_share"], sheet, f"{grid.iat[r0 - 1, value_col] if r0 else value_col}",
                        notes + ["format long : une ligne par date et par support"], 0.95, isin)
        if found:
            out.append(found)
    return out


def detect_grid(grid: pd.DataFrame, sheet: str, filename: str) -> tuple[list[Found], list[str]]:
    """`(séries trouvées, remarques sur la feuille)`."""
    grid = _trim(grid)
    remarks: list[str] = []
    if min(grid.shape) < 2 or max(grid.shape) < 3:          # 2 lignes x 13 colonnes : peut-être un tableau transposé
        return [], [f"{sheet} : pas de tableau"]
    notes: list[str] = []
    dcols = date_columns(grid)
    rows_t = None
    if not dcols or max(i["n"] for _, i in dcols) < MIN_POINTS:
        rows_t = _trim(grid.T.astype(object))
        tcols = date_columns(rows_t)
        if tcols and max(i["n"] for _, i in tcols) > max([i["n"] for _, i in dcols] or [0]):
            grid, dcols = rows_t, tcols
            notes.append("tableau transposé (dates en ligne)")
    if not dcols:
        return [], [f"{sheet} : aucune colonne de dates reconnue"]
    info0 = dcols[0][1]
    if info0.get("serial"):
        notes.append("dates au format numéro de série Excel")
    first_d = dcols[0][0]
    r0 = _first_row(list(grid[first_d]), _year_hint(list(grid[first_d])))
    title = _title_of(grid, r0)

    # Format long : beaucoup de dates répétées dans la colonne de dates principale.
    dates0, _ = parse.to_dates(list(grid[first_d].iloc[r0:]))
    valid0 = dates0.dropna()
    if len(dcols) == 1 and len(valid0) and valid0.duplicated().mean() > 0.3:
        found = _long_format(grid, first_d, r0, sheet, notes)
        if found:
            return found, remarks

    date_set = [j for j, _ in dcols]
    assignments: dict[int, list[int]] = {j: [] for j in date_set}
    for c in grid.columns:
        if c in date_set:
            continue
        cells = list(grid[c].iloc[r0:])
        nums, info = parse.to_numbers(cells)
        if info["parsed_share"] < 0.6 or np.isfinite(nums.to_numpy()).sum() < MIN_RATE_POINTS:
            continue
        left = [j for j in date_set if j < c]
        owner = max(left) if left else min(date_set, key=lambda j: abs(j - c))
        assignments[owner].append(c)
    if len([j for j in date_set if assignments[j]]) > 1:
        notes.append("blocs côte à côte : chaque support a ses propres dates")
    found: list[Found] = []
    total_cols = sum(len(v) for v in assignments.values())
    k = 0
    for dcol, value_cols in assignments.items():
        if not value_cols:
            continue
        year_hint = _year_hint(list(grid[dcol]))
        rd = _first_row(list(grid[dcol]), year_hint)
        dates, _dinfo = parse.to_dates(list(grid[dcol].iloc[rd:]), year_cells=year_hint)
        dates = dates.reset_index(drop=True)
        if len(dates.dropna()) >= 2 and dates.dropna().iloc[0] > dates.dropna().iloc[-1]:
            local_notes = notes + ["tableau du plus récent au plus ancien (remis dans l'ordre)"]
        else:
            local_notes = list(notes)
        for c in value_cols:
            nums, ninfo = parse.to_numbers(list(grid[c].iloc[rd:]))
            raw = _series(dates, nums.reset_index(drop=True))
            name, header = _header_name(grid, c, rd, dcol)
            conf = 1.0
            these = list(local_notes)
            if ninfo["decimal"] == "," and ninfo["text_cells"]:
                these.append("virgule décimale")
            isin = parse.find_isin(" ".join(str(grid.iat[r, c]) for r in range(max(0, rd - 6), rd))) or parse.find_isin(name) or parse.find_isin(title)
            if not name:
                name, how = _fallback_name(sheet, filename, title, total_cols, k)
                these.append(how)
                conf = 0.85
            if isin and (not name or is_generic(name) or name.upper() == isin):
                name = isin
            item = _finish(name, raw, header, ninfo["percent_share"], sheet, header or str(c), these, conf, isin)
            if item:
                found.append(item)
            k += 1
    if not found:
        remarks.append(f"{sheet} : des dates mais aucune colonne de valeurs exploitable")
    return found, remarks


def detect(filename: str, data: bytes) -> tuple[list[Found], list[str]]:
    """Toutes les séries d'un fichier (toutes feuilles), avec les remarques sur ce qui n'a rien donné. `DetectError` si rien n'est exploitable."""
    try:
        sheets = reader.read_tables(filename, data)
    except reader.TabularError as exc:
        raise DetectError(f"{filename} : {exc}") from exc
    found: list[Found] = []
    remarks: list[str] = []
    for sheet, grid in sheets:
        try:
            items, notes = detect_grid(grid, sheet, filename)
        except (ValueError, IndexError, KeyError, TypeError) as exc:     # une feuille bizarre ne doit pas empêcher de lire les autres
            items, notes = [], [f"{sheet} : illisible ({exc})"]
        found.extend(items)
        remarks.extend(notes)
    if not found:
        detail = " ; ".join(remarks[:4]) or "aucune feuille exploitable"
        raise DetectError(f"{filename} : aucune série datée trouvée ({detail}). Il faut au moins une colonne de dates et une colonne de valeurs.")
    names: dict[str, int] = {}
    for f in found:                       # noms uniques dans un même fichier
        n = names.get(f.name, 0)
        names[f.name] = n + 1
        if n:
            f.name = f"{f.name} ({n + 1})"
    return found, remarks


# ------------------------------------------------------------------------------------------------ cours OHLC (laboratoire de stratégies)

OHLC_NAMES = {
    "open": ("open", "ouverture", "ouv", "premier"), "high": ("high", "plus haut", "haut", "max"), "low": ("low", "plus bas", "bas", "min"),
    "close": ("adj close", "adjusted close", "close", "cloture", "clôture", "dernier", "last", "cours", "price", "prix", "vl", "nav"),
    "volume": ("volume", "vol", "quantite", "titres echanges"),
}


def _ohlc_header(grid: pd.DataFrame) -> tuple[int, dict[str, int]] | None:
    for r in range(min(len(grid), 30)):
        labels = {c: norm(grid.iat[r, c]) for c in grid.columns if _is_text(grid.iat[r, c])}
        found: dict[str, int] = {}
        for field_name, names in OHLC_NAMES.items():
            for name in names:
                hit = next((c for c, lab in labels.items() if lab == name and c not in found.values()), None)
                if hit is not None:
                    found[field_name] = hit
                    break
        if "close" in found and ("open" in found or "high" in found):
            return r, found
    return None


def detect_prices(filename: str, data: bytes) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Cours d'un fichier pour le laboratoire de stratégies : `({symbole: DataFrame[open, high, low, close, volume]}, notes)`.

    En-têtes OHLC reconnus (une ligne par date, avec ou sans colonne de symbole) ; sinon toute série de cours trouvée par `detect` donne un
    cours de clôture seul (ouverture = clôture, plus haut / plus bas = clôture)."""
    sheets = reader.read_tables(filename, data)
    out: dict[str, pd.DataFrame] = {}
    notes: list[str] = []
    stem = re.sub(r"[_]+", " ", filename.rsplit(".", 1)[0]).strip().upper()
    for sheet, grid in sheets:
        grid = _trim(grid)
        if grid.shape[0] < 3:
            continue
        head = _ohlc_header(grid)
        if head is None:
            continue
        r, cols = head
        labels = {c: norm(grid.iat[r, c]) for c in grid.columns}
        dcol = next((c for c, lab in labels.items() if lab in ("date", "dates", "jour", "day", "datetime", "seance", "timestamp")), None)
        if dcol is None:
            dcols = date_columns(grid.iloc[r + 1:].reset_index(drop=True))
            dcol = dcols[0][0] if dcols else None
        if dcol is None:
            continue
        scol = next((c for c, lab in labels.items() if lab in ("symbol", "symbole", "ticker", "code", "isin", "mnemo", "mnemonique")), None)
        body = grid.iloc[r + 1:].reset_index(drop=True)
        dates, _ = parse.to_dates(list(body[dcol]))
        frame = pd.DataFrame({"date": dates})
        for field_name, c in cols.items():
            frame[field_name] = parse.to_numbers(list(body[c]))[0]
        frame["symbol"] = body[scol].astype(str).str.strip().str.upper() if scol is not None else (sheet if not DEFAULT_SHEETS.match(sheet) else stem)
        frame = frame.dropna(subset=["date", "close"])
        for sym, g in frame.groupby("symbol"):
            g = g.drop_duplicates("date", keep="last").set_index("date").sort_index()
            for c in ("open", "high", "low"):
                if c not in g:
                    g[c] = g["close"]
                g[c] = g[c].fillna(g["close"])
            if "volume" not in g:
                g["volume"] = np.nan
            if len(g) >= MIN_POINTS:
                out[str(sym)] = g[["open", "high", "low", "close", "volume"]].astype(float)
    if out:
        notes.append(f"cours OHLC lus pour {len(out)} symbole(s)")
        return out, notes
    found, remarks = detect(filename, data)
    for f in found:
        lv = f.levels()
        key = (f.isin or f.name).upper()
        out[key] = pd.DataFrame({"open": lv, "high": lv, "low": lv, "close": lv, "volume": np.nan})
    notes.append("pas d'en-têtes OHLC : clôtures seules (ouverture = clôture)")
    return out, notes + remarks
