"""CSV import of movements (the drag-and-drop target on /patrimoine and
/mouvements).

As tolerant as possible on the format -- a broker export goes in as it is:
- UTF-8 (with or without BOM) or Windows-1252 (French Excel); delimiter
  sniffed among `;`, `,`, tab, `|`; lines above the header (the preamble of
  a bank statement) skipped;
- French or English headers, broker-specific ones included (Trade Republic:
  `datetime` + `date`, `type`, `symbol` = ISIN, `shares`, `fee`, `tax`,
  `account_type`); when two columns claim a field, the alias listed first
  wins (`date` over `datetime`, `type` over `category`);
- movement type: exact label first, then keywords (`TRANSFER_INSTANT_INBOUND`
  -> deposit, `REFERRAL` -> income), then the signs of quantity/amount -- an
  unknown type is imported with a warning, never rejected for that alone;
- numbers: decimal comma or point, thousands separators, currency signs,
  `(12,50)` and `12,50-` negatives; the signs are normalised per movement
  type (a sell exported with -1 shares is a sale of 1 share);
- fees and taxes (TTF, withholding) summed; on a cash line they become a
  separate `fee` movement, so the cash matches the broker's;
- dates ISO (with a time), `DD/MM/YYYY`, `DD/MM/YY`, `18 sept. 2026` --
  day first, never the US order (03/01/2024 is the 3rd of January);
- symbols resolved to a Yahoo quote by `wealth.symbols` (crypto `AXS` ->
  `AXS-EUR`, ISIN -> its EUR listing), so every position gets a price;
- an account column (`account_type`: DEFAULT / PEA) splits the file into
  sources the caller maps onto accounts (`plan_import`);
- a net amount column (`Montant net`, LCL) includes the fees: the unit
  price is derived from it net of fees, not gross;
- bonds (`asset_class` BOND, an `O.A.T.` in the label): quantity = nominal,
  price as a fraction of nominal, the broker's amount kept (accrued interest
  included), maturity and coupon read from the line (`OAT 2% 25/11/2032`,
  `Nov. 2032` for an OAT) or the coupon inferred from the accrued interest
  paid (wealth/bonds.py) -- with a warning, never silently;
- an IPO subscription (Trade Republic `IPO_SUBSCRIPTION`: the pre-payment,
  then the reimbursement of what was not allotted) only reserves cash: not
  booked, the allotted BUY line is (its fee is).

Strict where it matters: every row still goes through
`ledger.normalize_movement`; a row that fails is reported with its line
number, and NOTHING is written here -- the caller commits after the user
saw the preview.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter

import pandas as pd

from patrick.wealth import bonds, symbols
from patrick.wealth.ledger import LedgerError, normalize_movement

MAX_BYTES = 1_000_000
MAX_ROWS = 5_000
HEADER_SCAN_LINES = 30

# Most specific alias first: the rank decides between two columns claiming
# the same field.
_HEADER_ALIASES = {
    "ts": ("date", "date operation", "date d'operation", "date de l'operation", "trade date", "date d'execution",
           "execution date", "date de valeur", "value date", "booking date", "date comptable", "jour", "datetime",
           "date/heure", "date et heure", "timestamp", "time", "ts", "settlement date", "date de reglement"),
    "kind": ("type", "kind", "operation", "type d'operation", "type de transaction", "transaction type",
             "type d'ordre", "sens", "nature", "transaction", "event", "libelle operation",
             "category", "categorie"),
    "symbol": ("symbole", "symbol", "ticker", "isin", "code isin", "code", "instrument", "valeur", "titre",
               "security", "asset", "actif"),
    "name": ("name", "nom", "nom de la valeur", "libelle valeur", "designation", "security name",
             "instrument name", "asset name", "produit", "product", "support"),
    "asset_class": ("asset class", "classe d'actif", "asset type", "type d'actif", "instrument type"),
    "quantity": ("quantite", "quantity", "shares", "qty", "qte", "nombre", "nombre de titres", "nombre de parts",
                 "parts", "units", "nb"),
    "price": ("prix", "price", "cours", "prix unitaire", "unit price", "prix d'execution", "execution price",
              "cours d'execution", "price per share", "valeur liquidative", "vl", "nav"),
    "amount": ("montant", "amount", "montant net", "net amount", "total", "montant brut", "gross amount",
               "valeur totale", "montant eur", "amount eur"),
    "debit": ("debit",),
    "credit": ("credit",),
    "fees": ("frais", "fees", "fee", "commission", "commissions", "courtage", "frais de courtage", "brokerage",
             "transaction fee", "frais de transaction"),
    "tax": ("tax", "taxes", "taxe", "ttf", "impot", "impots", "withholding tax", "retenue a la source",
            "prelevements sociaux"),
    "rate": ("taux", "rate"),
    "maturity": ("echeance", "maturity", "date d'echeance"),
    "note": ("description", "libelle", "note", "commentaire", "memo", "label", "details"),
    "account": ("account type", "account", "compte", "account name", "portefeuille", "portfolio", "sub account",
                "sous compte"),
}
# Exact labels. "income" (broker bonus, referral) is booked as `interest`.
_KIND_ALIASES = {
    "buy": ("buy", "achat", "achat comptant", "souscription", "purchase"),
    "sell": ("sell", "vente", "vente comptant", "rachat", "cession", "redemption"),
    "deposit": ("deposit", "versement", "apport", "depot", "virement entrant"),
    "withdrawal": ("withdrawal", "retrait", "virement sortant"),
    "dividend": ("dividend", "dividende", "coupon", "distribution"),
    "fee": ("fee", "frais", "droits de garde", "commission"),
    "interest": ("interest", "interets", "interet"),
    "term_deposit": ("term deposit", "dat", "depot a terme"),
}
# Keywords (prefix of a word), first match wins -- the order matters.
_KIND_KEYWORDS = (
    ("term_deposit", ("depot a terme", "term deposit")),
    ("dividend", ("dividend", "coupon", "distribution")),
    ("interest", ("interest", "interet", "remuneration")),
    ("income", ("referral", "parrainage", "marketing", "reward", "bonus", "cashback", "prime", "gift", "cadeau",
                "promo")),
    ("fee", ("fee", "frais", "commission", "droits de garde", "tax", "taxe", "impot", "ttf")),
    ("sell", ("sell", "vente", "cession", "rachat", "redemption")),
    ("buy", ("buy", "achat", "purchase", "souscription", "savings plan", "round up")),
    ("deposit", ("inbound", "inpayment", "incoming", "deposit", "versement", "apport", "top up", "entrant", "recu")),
    ("withdrawal", ("outbound", "outgoing", "withdraw", "retrait", "payout", "sortant", "card", "carte")),
    ("transfer", ("transfer", "virement")),
)
_KIND_KEYWORD_RES = tuple((kind, re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + ")"))
                          for kind, words in _KIND_KEYWORDS)
_FR_MONTHS = {"janv": 1, "fevr": 2, "fev": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "aout": 8,
              "sept": 9, "oct": 10, "nov": 11, "dec": 12}
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2})[A-Z0-9]{7,26}([A-Z0-9]{4})\b")
_IPO_RE = re.compile(r"\bipo\b")
# Amount columns that include the fees (a buy's total debit, a sale's net credit).
_NET_AMOUNT_HEADERS = {"montant net", "net amount"}
# A column beaten for the symbol becomes the name when nothing claims it (LCL: ISIN + "Valeur").
_FALLBACK_FIELD = {"symbol": "name"}
_UNKNOWN_COUPON = "coupon inconnu"
_NUMERIC = ("quantity", "price", "amount", "debit", "credit", "fees", "tax", "rate")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[_\-]+", " ", text.strip().lower())
    return re.sub(r"\s+", " ", text).strip()


_HEADER_RANK = {_fold(alias): (key, rank) for key, aliases in _HEADER_ALIASES.items()
                for rank, alias in enumerate(aliases)}
_KIND_LOOKUP = {_fold(alias): key for key, aliases in _KIND_ALIASES.items() for alias in aliases}


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _parse_date(value: str) -> str:
    v = (value or "").strip()
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?:[ T,].*)?", v)
    if m:
        day, month, year = (int(g) for g in m.groups())
        if year < 100:
            year += 2000
        try:
            return pd.Timestamp(year=year, month=month, day=day).date().isoformat()
        except ValueError as exc:
            raise LedgerError(f"date invalide : {value!r}") from exc
    m = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})", _fold(v))
    month = m and (_FR_MONTHS.get(m.group(2)[:4]) or _FR_MONTHS.get(m.group(2)[:3]))
    if month:
        try:
            return pd.Timestamp(year=int(m.group(3)), month=month, day=int(m.group(1))).date().isoformat()
        except ValueError as exc:
            raise LedgerError(f"date invalide : {value!r}") from exc
    try:
        return pd.Timestamp(v).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"date invalide : {value!r}") from exc


def _clean_number(value) -> str:
    """'1 234,56 €' -> '1234.56'; '(12,50)' and '12,50-' -> '-12.50'."""
    s = str(value or "").strip()
    try:
        float(s)
        return s
    except ValueError:
        pass
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d,.+\-]", "", s)
    if s.endswith("-") and not s.startswith("-"):
        neg, s = True, s[:-1]
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    return "-" + s.lstrip("+") if neg and s and not s.startswith("-") else s


def _num(value) -> float | None:
    s = _clean_number(value)
    if s in ("", "-", "+", "."):
        return None
    try:
        return float(s)
    except ValueError as exc:
        raise LedgerError(f"nombre invalide : {value!r}") from exc


def _mask_ibans(text: str) -> str:
    return _IBAN_RE.sub(lambda m: f"{m.group(1)}…{m.group(2)}", text)


def _classify(label: str, note: str) -> tuple[str | None, bool]:
    """(kind, exact): the exact label, else keywords of the type then of the
    note. `kind` may be the pseudo-kinds `income` and `transfer`."""
    folded = _fold(label)
    if folded in _KIND_LOOKUP:
        return _KIND_LOOKUP[folded], True
    for text in (folded, _fold(note)):
        if not text:
            continue
        for kind, rx in _KIND_KEYWORD_RES:
            if rx.search(text):
                return kind, False
    return None, False


def _find_header(rows: list[list[str]]) -> int:
    for i, cells in enumerate(rows[:HEADER_SCAN_LINES]):
        if any(_HEADER_RANK.get(_fold(c), (None,))[0] == "ts" for c in cells):
            return i
    raise LedgerError("colonne de date introuvable (en-têtes reconnus : "
                      + ", ".join(sorted(_HEADER_ALIASES)) + ")")


def _map_columns(header: list[str]) -> dict[str, int]:
    """field -> column index, the best-ranked alias winning; a beaten column
    falls back on a related free field (`_FALLBACK_FIELD`)."""
    best: dict[str, tuple[int, int]] = {}
    beaten: list[tuple[str, int]] = []
    for idx, h in enumerate(header):
        hit = _HEADER_RANK.get(_fold(h))
        if hit is None:
            continue
        key, rank = hit
        if key not in best or rank < best[key][0]:
            if key in best:
                beaten.append((key, best[key][1]))
            best[key] = (rank, idx)
        else:
            beaten.append((key, idx))
    cols = {key: idx for key, (_, idx) in best.items()}
    for key, idx in beaten:
        fallback = _FALLBACK_FIELD.get(key)
        if fallback and fallback not in cols:
            cols[fallback] = idx
    return cols


def parse_csv(data: bytes | str, resolve=None) -> dict:
    """{"rows": [normalized movements + "line", "source"], "errors": [{"line",
    "error"}], "warnings": [{"line", "warning"}], "columns": {csv header ->
    field}, "delimiter", "sources": {source: n rows}}. `resolve` =
    `symbols.make_resolver(...)` (default: offline, crypto mapping only).
    Raises LedgerError only for a file that cannot be read at all."""
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise LedgerError(f"fichier trop volumineux ({len(data)} octets, max {MAX_BYTES})")
        text = _decode(data)
    else:
        text = data.lstrip("﻿")
    if not text.strip():
        raise LedgerError("fichier vide")
    resolve = resolve or symbols.make_resolver(search=None)
    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        delimiter = max(";,\t|", key=sample.count)
    all_rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    start = _find_header(all_rows)
    header = all_rows[start]
    cols = _map_columns(header)
    if not ({"kind", "amount", "quantity", "debit", "credit"} & set(cols)):
        raise LedgerError("ni type, ni montant, ni quantité : rien à importer")
    net_amount = "amount" in cols and _fold(header[cols["amount"]]) in _NET_AMOUNT_HEADERS

    records = []
    for line_no, cells in enumerate(all_rows[start + 1:], start=start + 2):
        if not any(c.strip() for c in cells):
            continue
        records.append((line_no, {k: (cells[i].strip() if i < len(cells) else "") for k, i in cols.items()}))
    signed = False
    for _, raw in records:
        try:
            if (_num(raw.get("amount")) or 0) < 0:
                signed = True
                break
        except LedgerError:
            continue

    out = {"rows": [], "errors": [], "warnings": [], "delimiter": delimiter,
           "columns": {header[i]: k for k, i in cols.items()}, "sources": Counter()}
    for line_no, raw in records:
        if len(out["rows"]) + len(out["errors"]) >= MAX_ROWS:
            out["errors"].append({"line": line_no, "error": f"au-delà de {MAX_ROWS} lignes, ignoré"})
            break
        try:
            rows, warnings = _parse_row(raw, signed, resolve, net_amount)
        except LedgerError as exc:
            out["errors"].append({"line": line_no, "error": str(exc)})
            continue
        source = raw.get("account") or None
        for row in rows:
            row.update(line=line_no, source=source)
            out["rows"].append(row)
        if source is not None:
            out["sources"][source] += 1
        out["warnings"].extend({"line": line_no, "warning": w} for w in warnings)
    out["sources"] = dict(out["sources"])
    _share_bond_coupons(out)
    return out


def _share_bond_coupons(out: dict) -> None:
    """A bond line without a coupon takes the one found on another line of
    the same bond (a 0.03 EUR remainder line has too little accrued interest
    to infer it), and loses its "coupon inconnu" warning."""
    known = {}
    for r in out["rows"]:
        if r.get("maturity") and r["kind"] in ("buy", "sell") and r.get("rate") is not None:
            known.setdefault(r["symbol"], r["rate"])
    filled = set()
    for r in out["rows"]:
        if r.get("maturity") and r["kind"] in ("buy", "sell") and r.get("rate") is None and r["symbol"] in known:
            r["rate"] = known[r["symbol"]]
            filled.add(r["line"])
    out["warnings"] = [w for w in out["warnings"] if not (w["line"] in filled and _UNKNOWN_COUPON in w["warning"])]


def _bond_fields(raw: dict, note: str, ts: str, qty: float | None, price: float | None,
                 ex_fees: float | None) -> tuple[dict, list[str]]:
    """{"price", "maturity", "rate"} of a bond line (price as a fraction of
    nominal) and the warnings about what had to be read or inferred.
    `ex_fees` = the trade's cash before fees (nominal x price + accrued)."""
    warnings = []
    name = raw.get("name") or ""
    price = bonds.quote_as_fraction(price) if price else price
    if price is None and qty and ex_fees:
        price = bonds.quote_as_fraction(ex_fees / qty)
    maturity = _parse_date(raw["maturity"]) if raw.get("maturity") else bonds.maturity_from_text(name, note)
    rate = raw.get("rate_value")
    if rate is None:
        rate = bonds.coupon_from_text(name, note)
    label = name or raw.get("symbol") or "obligation"
    if maturity is None:
        warnings.append(f"{label} : obligation sans échéance lisible, valorisée au prix payé coupon couru compris "
                        "-- renseigner échéance et coupon du mouvement pour le coupon couru et le rendement")
        return {"price": ex_fees / qty if qty and ex_fees else price, "maturity": None, "rate": rate}, warnings
    if rate is None and qty and price and ex_fees:
        accrued = ex_fees - qty * price
        rate = bonds.infer_coupon(accrued, qty, maturity, ts)
        if rate is not None:
            warnings.append(f"{label} : coupon {rate:.3%} déduit du coupon couru ({accrued:.2f}) et de "
                            f"l'échéance {maturity} -- à vérifier")
    if rate is None:
        warnings.append(f"{label} : {_UNKNOWN_COUPON} (échéance {maturity}) -- valorisé au dernier prix, sans coupon "
                        "couru ; le renseigner dans le mouvement")
    elif not raw.get("maturity"):
        warnings.append(f"{label} : obligation, échéance {maturity} lue dans le libellé")
    return {"price": price, "maturity": maturity, "rate": rate}, warnings


def _parse_row(raw: dict, signed: bool, resolve, net_amount: bool = False) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    ts = _parse_date(raw.get("ts", ""))
    nums = {k: _num(raw.get(k)) for k in _NUMERIC}
    amount = nums["amount"]
    if amount is None and (nums["credit"] is not None or nums["debit"] is not None):
        amount = abs(nums["credit"] or 0.0) - abs(nums["debit"] or 0.0)
    qty, price = nums["quantity"], nums["price"]
    costs = abs(nums["fees"] or 0.0) + abs(nums["tax"] or 0.0)
    label = raw.get("kind", "")
    note = _mask_ibans(raw.get("note", ""))
    has_asset = bool(raw.get("symbol") or raw.get("name") or symbols.ISIN_RE.search(note.upper()))

    if _IPO_RE.search(_fold(label)) or (_IPO_RE.search(_fold(note)) and not qty):
        rows = []
        if costs:
            rows.append(normalize_movement({"ts": ts, "kind": "fee", "amount": costs,
                                            "note": f"frais de souscription : {note}" if note else "frais de souscription"}))
        warnings.append(f"souscription IPO ({amount if amount is not None else 0:+.2f}) : réservation de liquidités, "
                        "non comptabilisée -- seul l'achat attribué compte")
        return rows, warnings

    kind, exact = _classify(label, note)
    if kind is None:
        if has_asset and qty:
            kind = "sell" if qty < 0 or (signed and (amount or 0) > 0) else "buy"
        elif amount:
            kind = "deposit" if amount > 0 else "withdrawal"
        else:
            raise LedgerError(f"type d'opération inconnu : {label!r}, sans quantité ni montant pour le deviner")
        warnings.append(f"type {label!r} inconnu : classé « {kind} » d'après les signes")
    elif kind == "transfer":
        kind = "withdrawal" if (amount or 0) < 0 else "deposit"
    elif not exact and signed and amount:
        # A keyword may name the flow, not its direction: the sign decides.
        if kind == "deposit" and amount < 0:
            kind = "withdrawal"
        elif kind == "withdrawal" and amount > 0:
            kind = "deposit"
        elif kind == "fee" and amount > 0:
            kind = "income"
        elif kind in ("dividend", "interest", "income") and amount < 0:
            kind = "fee"
    if kind == "income":
        kind = "interest"
    if not exact and label:
        note = f"{label} — {note}" if note else label

    base = {"ts": ts, "kind": kind, "note": note, "rate": nums["rate"], "maturity": raw.get("maturity") or None}
    if base["maturity"]:
        base["maturity"] = _parse_date(base["maturity"])

    if kind in ("buy", "sell"):
        qty = abs(qty) if qty else None
        price = abs(price) if price else None
        symbol, warning = resolve(raw.get("symbol"), raw.get("name"), raw.get("asset_class"), note)
        if warning:
            warnings.append(warning)
        if bonds.looks_like_bond(raw.get("asset_class"), raw.get("name"), note):
            ex_fees = None
            if amount:
                ex_fees = abs(amount) - (costs if kind == "buy" else -costs) if net_amount else abs(amount)
            fields, bond_warnings = _bond_fields({**raw, "rate_value": nums["rate"]}, note, ts, qty, price, ex_fees)
            warnings.extend(bond_warnings)
            cash = None
            if ex_fees is not None and fields["maturity"]:
                cash = ex_fees + costs if kind == "buy" else ex_fees - costs
            return [normalize_movement({**base, **fields, "symbol": symbol, "quantity": qty, "fees": costs,
                                        "amount": cash})], warnings
        if price is None and qty and amount:
            net = abs(amount) - costs if kind == "buy" else abs(amount) + costs
            price = (net if net_amount else abs(amount)) / qty
        if qty is None and price and amount:
            qty = abs(amount) / price
        return [normalize_movement({**base, "symbol": symbol, "quantity": qty, "price": price, "fees": costs})], warnings

    if kind == "term_deposit":
        return [normalize_movement({**base, "symbol": raw.get("symbol"), "amount": amount, "fees": costs})], warnings

    if amount is None and kind == "fee" and costs:
        amount, costs = costs, 0.0
    symbol = raw.get("symbol") or None
    if kind == "dividend" and (symbol or raw.get("name")):
        symbol = resolve(symbol, raw.get("name"), raw.get("asset_class"), note)[0]
    rows = [normalize_movement({**base, "symbol": symbol, "amount": amount})]
    if costs:
        rows.append(normalize_movement({"ts": ts, "kind": "fee", "amount": costs,
                                        "note": f"frais/taxe sur : {note}" if note else "frais/taxe"}))
    return rows, warnings


# ------------------------------------------------------------------ commit

def movement_key(mv: dict) -> tuple:
    """Identity of a movement for duplicate detection on re-import."""
    return (mv["ts"], mv["kind"], mv.get("symbol") or None, round(float(mv.get("quantity") or 0.0), 6),
            round(float(mv["amount"]), 2))


NEAR_DUPLICATE_DAYS = 5


def plan_import(rows: list[dict], mapping: dict, default_account: str, existing: dict[str, list[dict]]) -> list[dict]:
    """Target account and status of every parsed row. `mapping` = {source:
    account_id, or "" to skip that source}; unmapped sources go to
    `default_account`. Statuses: "" (to write), "ignoré" (source skipped),
    "virement interne" (a withdrawal of one source and a deposit of another,
    same day, same amount, landing in the same account: the pair cancels
    out), "doublon" (already in the target account: re-importing a file is
    idempotent), "doublon probable" (the same movement, amount and quantity
    included, already there at most `NEAR_DUPLICATE_DAYS` days apart and not
    matched otherwise: a statement dated by value date against a movement
    typed by hand -- not written, shown). `existing` = {account_id: its
    movements}."""
    plan = []
    for row in rows:
        target = mapping.get(row.get("source"), default_account) if row.get("source") is not None else default_account
        plan.append({**row, "target": target or None, "status": "" if target else "ignoré"})

    legs: dict[tuple, list[int]] = {}
    for i, p in enumerate(plan):
        if p["status"] == "" and p["kind"] == "withdrawal":
            legs.setdefault((p["target"], p["ts"], round(-p["amount"], 2)), []).append(i)
    for p in plan:
        if p["status"] == "" and p["kind"] == "deposit":
            pool = legs.get((p["target"], p["ts"], round(p["amount"], 2)), [])
            match = next((j for j in pool if plan[j]["source"] != p["source"]), None)
            if match is not None:
                pool.remove(match)
                p["status"] = plan[match]["status"] = "virement interne"

    seen = {acc: Counter(movement_key(m) for m in mvs) for acc, mvs in existing.items()}
    for p in plan:
        if p["status"] == "":
            counter = seen.setdefault(p["target"], Counter())
            key = movement_key(p)
            if counter[key] > 0:
                counter[key] -= 1
                p["status"] = "doublon"
    # What the exact pass left unmatched, by identity without the date.
    unmatched: dict[tuple, list[pd.Timestamp]] = {}
    for acc, mvs in existing.items():
        left = Counter(seen.get(acc, {}))
        for m in mvs:
            key = movement_key(m)
            if left[key] > 0:
                left[key] -= 1
                unmatched.setdefault((acc, *key[1:]), []).append(pd.Timestamp(m["ts"]))
    for p in plan:
        if p["status"] == "":
            days = unmatched.get((p["target"], *movement_key(p)[1:]), [])
            ts = pd.Timestamp(p["ts"])
            near = next((d for d in days if abs((d - ts).days) <= NEAR_DUPLICATE_DAYS), None)
            if near is not None:
                days.remove(near)
                p["status"] = "doublon probable"
    return plan
