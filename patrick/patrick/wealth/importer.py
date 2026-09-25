"""CSV import of movements (the drag-and-drop target on /patrimoine).

Tolerant on the format brokers actually export, strict on the content:
- delimiter sniffed among `;`, `,`, tab; UTF-8 with or without BOM;
- French or English headers and movement labels (aliases below);
- decimal comma and thin/normal spaces in numbers;
- dates `YYYY-MM-DD` or `DD/MM/YYYY` (day first -- never the US order: a
  French statement dated 03/01/2024 is the 3rd of January);
- every row goes through `ledger.normalize_movement`; a row that fails is
  reported with its line number and NOTHING is written by `parse_csv` --
  the caller commits the valid rows only after the user saw the preview.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata

import pandas as pd

from patrick.wealth.ledger import LedgerError, normalize_movement

MAX_BYTES = 1_000_000
MAX_ROWS = 5_000

_HEADER_ALIASES = {
    "ts": ("date", "ts", "date operation", "date d'operation", "date de l'operation", "jour", "trade date"),
    "kind": ("type", "kind", "operation", "sens", "nature", "type d'operation", "transaction"),
    "symbol": ("symbole", "symbol", "ticker", "code", "valeur", "titre", "instrument"),
    "quantity": ("quantite", "quantity", "qty", "qte", "nombre", "shares"),
    "price": ("prix", "price", "cours", "prix unitaire", "unit price"),
    "amount": ("montant", "amount", "montant net", "net amount", "total"),
    "fees": ("frais", "fees", "commission", "commissions", "courtage"),
    "rate": ("taux", "rate"),
    "maturity": ("echeance", "maturity", "date d'echeance"),
    "note": ("note", "libelle", "commentaire", "description", "memo"),
}
_KIND_ALIASES = {
    "buy": ("buy", "achat", "achat comptant", "souscription"),
    "sell": ("sell", "vente", "vente comptant", "rachat", "cession"),
    "deposit": ("deposit", "versement", "apport", "depot", "virement entrant"),
    "withdrawal": ("withdrawal", "retrait", "virement sortant"),
    "dividend": ("dividend", "dividende", "coupon"),
    "fee": ("fee", "frais", "droits de garde", "commission"),
    "interest": ("interest", "interets", "interet"),
    "term_deposit": ("term_deposit", "dat", "depot a terme"),
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.strip().lower())


_HEADER_LOOKUP = {_fold(alias): key for key, aliases in _HEADER_ALIASES.items() for alias in aliases}
_KIND_LOOKUP = {_fold(alias): key for key, aliases in _KIND_ALIASES.items() for alias in aliases}


def _parse_date(value: str) -> str:
    v = (value or "").strip()
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v)
    if m:
        day, month, year = (int(g) for g in m.groups())
        try:
            return pd.Timestamp(year=year, month=month, day=day).date().isoformat()
        except ValueError as exc:
            raise LedgerError(f"date invalide : {value!r}") from exc
    try:
        return pd.Timestamp(v).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"date invalide : {value!r}") from exc


def parse_csv(data: bytes | str) -> dict:
    """{"rows": [normalized movements], "errors": [{"line", "error"}],
    "columns": {csv header -> field}}. Raises LedgerError only for a file
    that cannot be read at all (size, no header, no date/type column)."""
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise LedgerError(f"fichier trop volumineux ({len(data)} octets, max {MAX_BYTES})")
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data.lstrip("﻿")
    if not text.strip():
        raise LedgerError("fichier vide")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    if not header:
        raise LedgerError("en-tête absent")
    columns = {h: _HEADER_LOOKUP.get(_fold(h)) for h in header}
    fields = [columns[h] for h in header]
    if "ts" not in fields or "kind" not in fields:
        raise LedgerError("colonnes obligatoires absentes : date et type (en-têtes reconnus : "
                          + ", ".join(sorted(_HEADER_ALIASES)) + ")")

    rows, errors = [], []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) + len(errors) >= MAX_ROWS:
            errors.append({"line": line_no, "error": f"au-delà de {MAX_ROWS} lignes, ignoré"})
            break
        raw = {f: c for f, c in zip(fields, cells) if f is not None}
        try:
            raw["ts"] = _parse_date(raw.get("ts", ""))
            if raw.get("maturity"):
                raw["maturity"] = _parse_date(raw["maturity"])
            kind = _KIND_LOOKUP.get(_fold(raw.get("kind", "")))
            if kind is None:
                raise LedgerError(f"type d'opération inconnu : {raw.get('kind')!r}")
            raw["kind"] = kind
            rows.append(normalize_movement(raw))
        except LedgerError as exc:
            errors.append({"line": line_no, "error": str(exc)})
    return {"rows": rows, "errors": errors,
            "columns": {h: f for h, f in columns.items() if f is not None}, "delimiter": delimiter}
