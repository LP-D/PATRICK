"""Lecture et contrôle d'intégrité des valeurs liquidatives importées.

Deux formats, comme dans le notebook d'origine :
- CSV avec une colonne de dates et une colonne de VL (`date,nav` ; séparateur `,` `;` ou tabulation, virgule décimale tolérée) ;
- export Excel d'une VL (titre « Liste des valeurs liquidatives du fonds X en date du … », puis date `jj/mm/aaaa` et VL), tel que le fournissent les
  gestionnaires de PEE.
Toute série est nettoyée de la même façon : VL strictement positives, une seule VL par date (la dernière), ordre chronologique.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

KEY_RE = re.compile(r"^[a-z0-9_]{1,80}$")                    # clé d'un fonds : sert de nom de fichier, jamais autre chose
DATE_NAMES = ("date", "jour", "day", "datetime", "time", "dates")
NAV_NAMES = ("nav", "vl", "valeur liquidative", "valeur_liquidative", "close", "adj close", "adj_close", "prix", "price", "cours", "value", "valeur")
MIN_POINTS = 24


class LoaderError(ValueError):
    """Fichier illisible ou incohérent : le message est affiché tel quel à l'utilisateur (en français)."""


@dataclass(frozen=True)
class ParsedFund:
    key: str
    label: str
    series: pd.Series          # VL, index = dates, nom = clé
    source: str                # nom du fichier d'origine
    kind: str                  # "csv" ou "xlsx"


def slugify(label: str) -> str:
    """`Finama Actions Internationales` -> `finama_actions_internationales` (ASCII minuscule, `_` entre les mots)."""
    label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:80]


def _to_number(values: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(values):
        return values.astype(float)
    cleaned = (values.astype(str).str.replace(" ", "", regex=False).str.replace("\xa0", "", regex=False)
               .str.replace(" ", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(cleaned, errors="coerce")


def _sane(dates: pd.Series) -> pd.Series:
    """Une date hors de 1900-2200 est une erreur de saisie (« 120-11-01 ») : elle devient NaT au lieu de casser la conversion en nanosecondes."""
    return dates.where((dates.dt.year >= 1900) & (dates.dt.year <= 2200))


def _one_date(value: str) -> pd.Timestamp:
    try:
        ts = pd.to_datetime(value, dayfirst=True, errors="coerce", format="mixed")
    except (pd.errors.OutOfBoundsDatetime, OverflowError, ValueError):
        return pd.NaT
    return ts if ts is not pd.NaT and 1900 <= ts.year <= 2200 else pd.NaT


def _to_dates(values: pd.Series) -> pd.Series:
    """Dates ISO (`2026-09-17`) ou françaises (`17/09/2026`) ; une cellule illisible ou aberrante devient NaT (ligne écartée)."""
    if pd.api.types.is_datetime64_any_dtype(values):
        return values
    text = values.astype(str).str.strip()
    iso = text.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if iso.any():
        out[iso] = _sane(pd.to_datetime(text[iso].str.slice(0, 10), format="%Y-%m-%d", errors="coerce")).astype("datetime64[ns]")
    if (~iso).any():
        rest = text[~iso]
        try:
            out[~iso] = _sane(pd.to_datetime(rest, dayfirst=True, errors="coerce", format="mixed")).astype("datetime64[ns]")
        except (pd.errors.OutOfBoundsDatetime, OverflowError, ValueError, TypeError):
            out[~iso] = pd.Series([_one_date(v) for v in rest], index=rest.index).astype("datetime64[ns]")
    return out


def clean_series(dates: pd.Series, navs: pd.Series, name: str, source: str) -> pd.Series:
    """Série de VL propre, ou `LoaderError`. Les lignes sans date ou sans VL sont écartées (en-têtes, totaux, cellules vides)."""
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "nav": navs}).dropna()
    if len(frame) < MIN_POINTS:
        raise LoaderError(f"{source} : {len(frame)} VL lisibles seulement (au moins {MIN_POINTS} sont nécessaires).")
    if (frame["nav"] <= 0).any():
        raise LoaderError(f"{source} : contient une VL négative ou nulle.")
    return frame.drop_duplicates("date", keep="last").set_index("date")["nav"].sort_index().astype(float).rename(name)


def read_csv_nav(data: bytes, source: str = "fichier.csv") -> pd.Series:
    """Série de VL d'un CSV. Colonnes reconnues par leur nom (`date`/`nav`, `Date`/`VL`, `Close`…) ; à défaut, les deux premières."""
    # Séparateur : celui des quatre usuels qui revient le plus dans la première ligne (le détecteur automatique de pandas peut choisir une lettre).
    head = data[:4096].decode("utf-8", errors="replace").lstrip("﻿").splitlines()
    first_line = head[0] if head else ""
    sep = max((",", ";", "\t", "|"), key=first_line.count)
    if first_line.count(sep) == 0:
        raise LoaderError(f"{source} : il faut une colonne de dates et une colonne de VL.")
    try:
        raw = pd.read_csv(io.BytesIO(data), sep=sep, encoding="utf-8-sig", encoding_errors="replace", dtype=str, on_bad_lines="skip")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise LoaderError(f"{source} : fichier CSV illisible ({exc}).") from exc
    if raw.shape[1] < 2:
        raise LoaderError(f"{source} : il faut une colonne de dates et une colonne de VL.")
    by_name = {str(c).strip().lower(): c for c in raw.columns}
    date_col = next((by_name[n] for n in DATE_NAMES if n in by_name), raw.columns[0])
    nav_col = next((by_name[n] for n in NAV_NAMES if n in by_name), None)
    if nav_col is None:
        nav_col = next(c for c in raw.columns if c != date_col)
    return clean_series(_to_dates(raw[date_col]), _to_number(raw[nav_col]), slugify(source.rsplit(".", 1)[0]), source)


def read_xlsx_nav(data: bytes, source: str = "fichier.xlsx") -> tuple[pd.Series, str]:
    """`(série de VL, nom du fonds)` d'un export Excel de VL. Le nom vient du titre de la première cellule ; les VL commencent à la
    première ligne dont la première cellule est une date (3 lignes d'en-tête dans les exports de PEE)."""
    try:
        raw = pd.read_excel(io.BytesIO(data), header=None)
    except Exception as exc:
        raise LoaderError(f"{source} : classeur Excel illisible ({exc}).") from exc
    if raw.shape[1] < 2 or raw.empty:
        raise LoaderError(f"{source} : il faut une colonne de dates et une colonne de VL.")
    title = str(raw.iloc[0, 0]) if pd.notna(raw.iloc[0, 0]) else ""
    label = re.sub(r"^Liste des valeurs liquidatives du fonds ", "", title, flags=re.IGNORECASE)
    label = re.sub(r" en date du .*", "", label, flags=re.IGNORECASE).strip()
    dates = _to_dates(raw.iloc[:, 0])
    first = dates.first_valid_index()
    if first is None:
        raise LoaderError(f"{source} : aucune date reconnue dans la première colonne.")
    body = raw.loc[first:]
    label = label or source.rsplit(".", 1)[0]
    return clean_series(dates.loc[first:], _to_number(body.iloc[:, 1]), slugify(label), source), label


def parse_upload(filename: str, data: bytes) -> ParsedFund:
    """Un fichier téléversé -> un fonds. Le type se déduit de l'extension ; la clé du fonds est le nom normalisé (fichier ou titre Excel)."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        series, label = read_xlsx_nav(data, filename)
        kind = "xlsx"
    elif lower.endswith((".csv", ".txt")):
        series = read_csv_nav(data, filename)
        label = filename.rsplit(".", 1)[0].replace("_", " ").strip().title()
        kind = "csv"
    else:
        raise LoaderError(f"{filename} : format non pris en charge (CSV ou Excel .xlsx attendus).")
    key = slugify(label) or slugify(filename)
    if not KEY_RE.match(key):
        raise LoaderError(f"{filename} : nom de fonds inexploitable.")
    return ParsedFund(key=key, label=label, series=series.rename(key), source=filename, kind=kind)


def merge_series(old: pd.Series | None, new: pd.Series) -> tuple[pd.Series, dict]:
    """Fusionne deux séries du même fonds (l'ancienne l'emporte sur les dates communes, comme le notebook) et contrôle leur cohérence :
    `{points_communs, ecart_max, nouveaux_points}`. Un écart important sur les dates communes signale deux fonds différents sous le même nom."""
    if old is None or old.empty:
        return new, {"points_communs": 0, "ecart_max": 0.0, "nouveaux_points": len(new)}
    both = pd.concat([new.rename("new"), old.rename("old")], axis=1, sort=True).dropna()
    gap = float((both["new"] - both["old"]).abs().max()) if len(both) else 0.0
    merged = old.combine_first(new).rename(old.name)
    return merged, {"points_communs": len(both), "ecart_max": gap, "nouveaux_points": int((~new.index.isin(old.index)).sum())}


# Alias publics : les autres modules d'import (événements des stratégies) lisent des dates et des nombres de la même façon.
to_dates = _to_dates
to_number = _to_number
