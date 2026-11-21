"""Grilles brutes de cellules à partir d'un fichier téléversé, quel que soit son format.

Rien n'est supposé sur la mise en page (titre, lignes vides, en-têtes sur plusieurs lignes) : `detect` s'en charge. Les formats :
- `.csv` `.txt` `.tsv` `.prn` : encodage UTF-8 ou Windows-1252 (exports Excel français), séparateur `;` `,` tabulation ou `|` choisi sur sa
  régularité ligne à ligne, lignes de longueurs inégales tolérées (titre d'une seule cellule au-dessus du tableau) ;
- `.xlsx` `.xlsm` : toutes les feuilles (openpyxl), valeurs calculées ;
- `.xls` : vrai classeur Excel 97 (xlrd) ou page HTML déguisée en .xls, comme en exportent beaucoup de banques et de teneurs de compte (lxml) ;
- `.ods` : tableur LibreOffice (odfpy).
Les lecteurs `.xls`, HTML et `.ods` sont facultatifs (extra `imports`) : s'ils manquent, le message dit quoi installer.
"""
from __future__ import annotations

import csv
import io
import zipfile

import pandas as pd

MAX_BYTES = 150 * 1024 * 1024
MAX_ROWS = 300_000
MAX_SHEETS = 40
SEPARATORS = (";", ",", "\t", "|")
TEXT_EXT = (".csv", ".txt", ".tsv", ".prn")
EXCEL_EXT = (".xlsx", ".xlsm")
ALL_EXT = TEXT_EXT + EXCEL_EXT + (".xls", ".ods")


class TabularError(ValueError):
    """Fichier illisible : message en français, affiché tel quel."""


def decode(data: bytes) -> str:
    """Texte d'un fichier : UTF-8 (avec ou sans BOM), sinon Windows-1252, encodage des CSV exportés par Excel en français."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def sniff_separator(lines: list[str]) -> str:
    """Le séparateur le plus régulier : celui qui revient le même nombre de fois (au moins une) sur le plus de lignes non vides.

    La régularité départage `,` et `;` dans un CSV français où la virgule est aussi le séparateur décimal (« 12,5;13,1 »)."""
    sample = [ln for ln in lines[:60] if ln.strip()]
    if not sample:
        raise TabularError("Fichier vide.")
    best, best_score = None, (0, 0)
    for sep in SEPARATORS:
        counts = [ln.count(sep) for ln in sample]
        positive = [c for c in counts if c > 0]
        if not positive:
            continue
        mode = max(set(positive), key=positive.count)
        score = (positive.count(mode), mode)
        if score > best_score:
            best, best_score = sep, score
    if best is None:
        return "\t"       # une seule colonne : le détecteur dira qu'il manque les dates ou les valeurs
    return best


def read_text(data: bytes) -> pd.DataFrame:
    text = decode(data)
    lines = text.splitlines()
    sep = sniff_separator(lines)
    rows = list(csv.reader(io.StringIO(text), delimiter=sep))[:MAX_ROWS]
    width = max((len(r) for r in rows), default=0)
    if not width:
        raise TabularError("Fichier vide.")
    return pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=object)


def read_xlsx(data: bytes) -> list[tuple[str, pd.DataFrame]]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise TabularError(f"classeur Excel illisible ({exc}).") from exc
    out = []
    try:
        for ws in wb.worksheets[:MAX_SHEETS]:
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_ROWS:
                    break
                rows.append(list(row))
            if rows:
                width = max(len(r) for r in rows)
                out.append((ws.title, pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=object)))
    finally:
        wb.close()
    return out


def _looks_html(data: bytes) -> bool:
    head = data[:2048].lstrip().lower()
    return head.startswith((b"<", b"\xef\xbb\xbf<")) and (b"<html" in head or b"<table" in head or b"<!doctype" in head or b"<?xml" in head)


def read_html(data: bytes) -> list[tuple[str, pd.DataFrame]]:
    try:
        import lxml  # noqa: F401
    except ImportError as exc:
        raise TabularError("ce fichier .xls est une page web : installez le lecteur facultatif (`pip install lxml`).") from exc
    try:
        tables = pd.read_html(io.StringIO(decode(data)), header=None, thousands=None, decimal="§")
    except ValueError as exc:
        raise TabularError("aucun tableau trouvé dans ce fichier.") from exc
    return [(f"Tableau {i + 1}", t.astype(object)) for i, t in enumerate(tables[:MAX_SHEETS])]


def read_xls(data: bytes) -> list[tuple[str, pd.DataFrame]]:
    if _looks_html(data):
        return read_html(data)
    try:
        import xlrd
    except ImportError as exc:
        raise TabularError("ancien format Excel (.xls) : installez le lecteur facultatif (`pip install xlrd`) ou enregistrez le fichier en .xlsx.") from exc
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:  # xlrd lève ses propres types selon la version
        raise TabularError(f"classeur .xls illisible ({exc}).") from exc
    out = []
    for sheet in book.sheets()[:MAX_SHEETS]:
        rows = []
        for r in range(min(sheet.nrows, MAX_ROWS)):
            row = []
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                    except (ValueError, OverflowError):
                        row.append(cell.value)
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                else:
                    row.append(cell.value)
            rows.append(row)
        if rows:
            out.append((sheet.name, pd.DataFrame(rows, dtype=object)))
    return out


def read_ods(data: bytes) -> list[tuple[str, pd.DataFrame]]:
    try:
        import odf  # noqa: F401
    except ImportError as exc:
        raise TabularError("tableur LibreOffice (.ods) : installez le lecteur facultatif (`pip install odfpy`) ou enregistrez le fichier en .xlsx.") from exc
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine="odf")
    except Exception as exc:
        raise TabularError(f"tableur .ods illisible ({exc}).") from exc
    return [(name, df.astype(object)) for name, df in list(sheets.items())[:MAX_SHEETS]]


def read_tables(filename: str, data: bytes) -> list[tuple[str, pd.DataFrame]]:
    """`[(nom de la feuille, grille brute)]` ; `TabularError` si le format n'est pas pris en charge ou le fichier illisible."""
    if len(data) > MAX_BYTES:
        raise TabularError(f"fichier trop volumineux (au plus {MAX_BYTES // (1024 * 1024)} Mo).")
    if not data:
        raise TabularError("fichier vide.")
    lower = (filename or "").lower()
    if lower.endswith(TEXT_EXT):
        return [(filename.rsplit(".", 1)[0], read_text(data))]
    if lower.endswith(EXCEL_EXT):
        if not data.startswith(b"PK"):
            if _looks_html(data):
                return read_html(data)
            return [(filename.rsplit(".", 1)[0], read_text(data))]     # CSV renommé en .xlsx : cela arrive
        return read_xlsx(data)
    if lower.endswith(".xls"):
        return read_xls(data)
    if lower.endswith(".ods"):
        return read_ods(data)
    raise TabularError("format non pris en charge (CSV, TXT, Excel .xlsx/.xls ou LibreOffice .ods attendus).")
