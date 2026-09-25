"""Accounts and movements (migration 0023) -- the ledger is the ONLY source
of truth: positions, cash and cost basis are always recomputed from the
movements, never stored.

Conventions
-----------
- `amount` is the signed cash impact in the account currency. For
  `buy`/`sell` it is derived from quantity x price and fees when the caller
  does not give it (`normalize_movement`), so an imported broker statement
  and a hand-typed movement end up with the same row.
- Cost basis is the French *prix de revient unitaire* (PRU): weighted
  average purchase price, purchase fees included; a sale realises
  (price - PRU) x quantity - sale fees and leaves the PRU unchanged.
- A term deposit (`term_deposit`, *dépôt à terme*) moves `-amount` out of
  cash into a position `symbol` (default `DAT:<id>`) carrying `rate` and
  `maturity`; it has no price history (see performance.py).
- Real vs fictive: a fictive account is a sandbox (blank, or a clone of a
  real one). A movement never goes from a fictive account into a real one;
  dragging a real movement onto a fictive account copies it.
"""
from __future__ import annotations

import math
import sqlite3
import uuid
from dataclasses import dataclass, field

import pandas as pd

ACCOUNT_KINDS = ("PEA", "CTO", "AV", "LIVRET", "DAT", "AUTRE")
ACCOUNT_MODES = ("real", "fictive")
MOVEMENT_KINDS = ("deposit", "withdrawal", "buy", "sell", "dividend", "fee", "interest", "term_deposit")
EXTERNAL_FLOW_KINDS = ("deposit", "withdrawal")
MOVEMENT_LABELS_FR = {"deposit": "Versement", "withdrawal": "Retrait", "buy": "Achat", "sell": "Vente",
                      "dividend": "Dividende", "fee": "Frais", "interest": "Intérêts", "term_deposit": "Dépôt à terme"}

# Default benchmark per wrapper: what a passive investor in that wrapper
# would typically hold. Editable per account.
DEFAULT_BENCHMARK = {"PEA": "^STOXX50E", "CTO": "URTH", "AV": "URTH", "LIVRET": None, "DAT": None, "AUTRE": None}

PEA_DEPOSIT_CAP_EUR = 150_000.0
# Exchange suffixes of EU/EEA venues on Yahoo Finance. A ticker without one
# of these is *probably* not PEA-eligible -- a heuristic warning, never a
# block (eligibility depends on the issuer's seat, not the venue).
PEA_LIKELY_ELIGIBLE_SUFFIXES = (".PA", ".DE", ".F", ".AS", ".BR", ".MI", ".MC", ".LS", ".VI", ".HE",
                                ".IR", ".ST", ".CO", ".OL", ".AT", ".WA", ".PR", ".BD", ".LU")


class LedgerError(ValueError):
    """Invalid account/movement input (400 at the API)."""


def _iso_date(value) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"date invalide : {value!r}") from exc


def _num(value, name: str, required: bool = False) -> float | None:
    if value is None or value == "":
        if required:
            raise LedgerError(f"{name} manquant")
        return None
    try:
        out = float(str(value).replace(",", ".").replace(" ", "").replace(" ", ""))
    except ValueError as exc:
        raise LedgerError(f"{name} invalide : {value!r}") from exc
    if not math.isfinite(out):
        raise LedgerError(f"{name} non fini : {value!r}")
    return out


# ---------------------------------------------------------------- accounts

def create_account(conn: sqlite3.Connection, name: str, kind: str, mode: str = "real",
                   currency: str = "EUR", benchmark: str | None = "__default__",
                   opened_on: str | None = None, source_account_id: str | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise LedgerError("nom de compte manquant")
    if kind not in ACCOUNT_KINDS:
        raise LedgerError(f"type de compte inconnu : {kind!r} ({ACCOUNT_KINDS})")
    if mode not in ACCOUNT_MODES:
        raise LedgerError(f"mode inconnu : {mode!r} ({ACCOUNT_MODES})")
    if benchmark == "__default__":
        benchmark = DEFAULT_BENCHMARK.get(kind)
    account_id = f"acc_{uuid.uuid4().hex[:10]}"
    with conn:
        conn.execute(
            "INSERT INTO wealth_account (account_id, name, kind, mode, currency, benchmark, opened_on, "
            "source_account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, name[:120], kind, mode, (currency or "EUR").upper()[:3], benchmark or None,
             _iso_date(opened_on) if opened_on else None, source_account_id),
        )
    return account_id


def get_account(conn: sqlite3.Connection, account_id: str) -> dict | None:
    row = conn.execute(
        "SELECT account_id, name, kind, mode, currency, benchmark, opened_on, source_account_id, archived, "
        "created_at FROM wealth_account WHERE account_id = ?", (account_id,)).fetchone()
    if row is None:
        return None
    keys = ("account_id", "name", "kind", "mode", "currency", "benchmark", "opened_on",
            "source_account_id", "archived", "created_at")
    return dict(zip(keys, row))


def list_accounts(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    ids = [r[0] for r in conn.execute(
        "SELECT account_id FROM wealth_account " + ("" if include_archived else "WHERE archived = 0 ")
        + "ORDER BY mode, kind, name")]
    return [get_account(conn, i) for i in ids]


def update_account(conn: sqlite3.Connection, account_id: str, **fields) -> None:
    allowed = {"name", "benchmark", "opened_on", "archived"}
    unknown = set(fields) - allowed
    if unknown:
        raise LedgerError(f"champ(s) non modifiable(s) : {sorted(unknown)}")
    if not fields:
        return
    if fields.get("opened_on"):
        fields["opened_on"] = _iso_date(fields["opened_on"])
    sets = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE wealth_account SET {sets} WHERE account_id = ?", (*fields.values(), account_id))


def clone_as_fictive(conn: sqlite3.Connection, account_id: str, name: str | None = None) -> str:
    """Sandbox copy of an account (all its movements), mode `fictive`."""
    src = get_account(conn, account_id)
    if src is None:
        raise LedgerError(f"compte introuvable : {account_id}")
    new_id = create_account(conn, name or f"{src['name']} (fictif)", src["kind"], "fictive",
                            src["currency"], src["benchmark"], src["opened_on"], source_account_id=account_id)
    for mv in list_movements(conn, account_id):
        _insert_movement(conn, new_id, mv)
    return new_id


def delete_account(conn: sqlite3.Connection, account_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM wealth_account WHERE account_id = ?", (account_id,))


# --------------------------------------------------------------- movements

_MOVEMENT_COLUMNS = ("movement_id", "account_id", "ts", "kind", "symbol", "quantity", "price", "amount",
                     "fees", "rate", "maturity", "note")


def normalize_movement(raw: dict) -> dict:
    """Validates a movement and derives `amount` when it can be computed.
    Returns the canonical dict (no `movement_id`/`account_id`)."""
    kind = (raw.get("kind") or "").strip().lower()
    if kind not in MOVEMENT_KINDS:
        raise LedgerError(f"type de mouvement inconnu : {raw.get('kind')!r} ({MOVEMENT_KINDS})")
    ts = _iso_date(raw.get("ts"))
    symbol = (raw.get("symbol") or "").strip().upper() or None
    quantity = _num(raw.get("quantity"), "quantité")
    price = _num(raw.get("price"), "prix")
    fees = _num(raw.get("fees"), "frais") or 0.0
    amount = _num(raw.get("amount"), "montant")
    rate = _num(raw.get("rate"), "taux")
    maturity = _iso_date(raw["maturity"]) if raw.get("maturity") else None
    if fees < 0:
        raise LedgerError("frais négatifs")

    if kind in ("buy", "sell"):
        if not symbol:
            raise LedgerError(f"{kind} : symbole manquant")
        if quantity is None or quantity <= 0 or price is None or price <= 0:
            raise LedgerError(f"{kind} : quantité et prix strictement positifs requis")
        gross = quantity * price
        amount = -(gross + fees) if kind == "buy" else gross - fees
    elif kind == "term_deposit":
        if amount is None or amount == 0:
            raise LedgerError("dépôt à terme : montant requis")
        if rate is None or not maturity:
            raise LedgerError("dépôt à terme : taux et échéance requis")
        if maturity <= ts:
            raise LedgerError("dépôt à terme : l'échéance doit suivre la date de souscription")
        amount = -abs(amount)
        symbol = symbol or f"DAT:{ts}:{rate:g}"
        quantity, price = 1.0, abs(amount)
    else:
        if amount is None:
            raise LedgerError(f"{kind} : montant requis")
        amount = abs(amount) if kind in ("deposit", "dividend", "interest") else -abs(amount)
    return {"ts": ts, "kind": kind, "symbol": symbol, "quantity": quantity, "price": price,
            "amount": round(amount, 6), "fees": fees, "rate": rate, "maturity": maturity,
            "note": (raw.get("note") or "").strip()[:300] or None}


def _insert_movement(conn: sqlite3.Connection, account_id: str, mv: dict) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO wealth_movement (account_id, ts, kind, symbol, quantity, price, amount, fees, rate, "
            "maturity, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, mv["ts"], mv["kind"], mv["symbol"], mv["quantity"], mv["price"], mv["amount"],
             mv["fees"], mv["rate"], mv["maturity"], mv["note"]),
        )
    return int(cur.lastrowid)


def add_movement(conn: sqlite3.Connection, account_id: str, raw: dict) -> int:
    if get_account(conn, account_id) is None:
        raise LedgerError(f"compte introuvable : {account_id}")
    return _insert_movement(conn, account_id, normalize_movement(raw))


def get_movement(conn: sqlite3.Connection, movement_id: int) -> dict | None:
    row = conn.execute(f"SELECT {', '.join(_MOVEMENT_COLUMNS)} FROM wealth_movement WHERE movement_id = ?",
                       (movement_id,)).fetchone()
    return dict(zip(_MOVEMENT_COLUMNS, row)) if row else None


def list_movements(conn: sqlite3.Connection, account_id: str | None = None) -> list[dict]:
    sql = f"SELECT {', '.join(_MOVEMENT_COLUMNS)} FROM wealth_movement"
    params: tuple = ()
    if account_id is not None:
        sql += " WHERE account_id = ?"
        params = (account_id,)
    sql += " ORDER BY ts, movement_id"
    return [dict(zip(_MOVEMENT_COLUMNS, r)) for r in conn.execute(sql, params)]


def delete_movement(conn: sqlite3.Connection, movement_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM wealth_movement WHERE movement_id = ?", (movement_id,))


def transfer_movement(conn: sqlite3.Connection, movement_id: int, target_account_id: str) -> dict:
    """Drag-and-drop of a movement onto another account. Real -> real moves
    it, real/fictive -> fictive copies it (the original stays), fictive ->
    real is refused: a sandbox never writes into the real ledger."""
    mv = get_movement(conn, movement_id)
    if mv is None:
        raise LedgerError(f"mouvement introuvable : {movement_id}")
    src, dst = get_account(conn, mv["account_id"]), get_account(conn, target_account_id)
    if dst is None:
        raise LedgerError(f"compte introuvable : {target_account_id}")
    if src["account_id"] == dst["account_id"]:
        return {"action": "none", "movement_id": movement_id}
    if src["mode"] == "fictive" and dst["mode"] == "real":
        raise LedgerError("un mouvement fictif ne peut pas entrer dans un compte réel")
    if dst["mode"] == "fictive":
        new_id = _insert_movement(conn, target_account_id, mv)
        return {"action": "copied", "movement_id": new_id}
    with conn:
        conn.execute("UPDATE wealth_movement SET account_id = ? WHERE movement_id = ?",
                     (target_account_id, movement_id))
    return {"action": "moved", "movement_id": movement_id}


# --------------------------------------------------------------- positions

@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    cost: float = 0.0                 # total cost of the open quantity (PRU x quantity)
    realized: float = 0.0
    is_term_deposit: bool = False
    rate: float | None = None
    start: str | None = None
    maturity: str | None = None
    last_trade_price: float | None = None

    @property
    def pru(self) -> float | None:
        return self.cost / self.quantity if self.quantity > 0 else None


@dataclass
class LedgerState:
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    deposits: float = 0.0
    withdrawals: float = 0.0
    income: float = 0.0
    fees: float = 0.0
    warnings: list[str] = field(default_factory=list)


def replay(movements: list[dict], as_of=None, account: dict | None = None) -> LedgerState:
    """Positions, cash and PRU at `as_of` (inclusive), by replaying the
    movements in date order. Collects warnings (overselling, PEA cap, PEA
    early withdrawal, probably ineligible PEA security) instead of raising:
    the ledger records what happened, the checks inform."""
    cutoff = pd.Timestamp(as_of).date().isoformat() if as_of is not None else None
    st = LedgerState()
    for mv in sorted(movements, key=lambda m: (m["ts"], m.get("movement_id") or 0)):
        if cutoff and mv["ts"] > cutoff:
            break
        apply_movement(st, mv)
    st.positions = {s: p for s, p in st.positions.items() if p.quantity > 1e-9}
    if account is not None:
        st.warnings.extend(regulatory_warnings(account, movements, cutoff))
    return st


def apply_movement(st: LedgerState, mv: dict) -> None:
    """Applies one movement to a running state (incremental replay)."""
    kind, amount = mv["kind"], float(mv["amount"])
    st.cash += amount
    fees = float(mv.get("fees") or 0.0)
    st.fees += fees
    if kind == "deposit":
        st.deposits += amount
    elif kind == "withdrawal":
        st.withdrawals += -amount
    elif kind in ("dividend", "interest"):
        st.income += amount
    elif kind == "fee":
        st.fees += -amount
    elif kind in ("buy", "term_deposit"):
        pos = st.positions.setdefault(mv["symbol"], Position(mv["symbol"]))
        qty = float(mv["quantity"])
        pos.cost += -amount
        pos.quantity += qty
        pos.last_trade_price = float(mv["price"])
        if kind == "term_deposit":
            pos.is_term_deposit, pos.rate, pos.start, pos.maturity = True, mv["rate"], mv["ts"], mv["maturity"]
    elif kind == "sell":
        pos = st.positions.setdefault(mv["symbol"], Position(mv["symbol"]))
        qty = float(mv["quantity"])
        if qty > pos.quantity + 1e-9:
            st.warnings.append(f"{mv['ts']} : vente de {qty:g} {mv['symbol']} pour {pos.quantity:g} détenus")
        pru = pos.pru or 0.0
        sold = min(qty, pos.quantity)
        pos.realized += amount - pru * sold
        pos.cost -= pru * sold
        pos.quantity -= sold
        pos.last_trade_price = float(mv["price"])


def regulatory_warnings(account: dict, movements: list[dict], cutoff: str | None = None) -> list[str]:
    """PEA checks (French rules as understood on 2026-09-25 -- to confirm
    with the official source, service-public.fr): deposits capped at
    150 000 EUR; a withdrawal before the 5th anniversary closes the plan;
    EU-listed equities only (venue suffix heuristic)."""
    if account.get("kind") != "PEA":
        return []
    out: list[str] = []
    mvs = [m for m in movements if cutoff is None or m["ts"] <= cutoff]
    deposits = sum(float(m["amount"]) for m in mvs if m["kind"] == "deposit")
    if deposits > PEA_DEPOSIT_CAP_EUR:
        out.append(f"PEA : versements cumulés {deposits:,.0f} € > plafond {PEA_DEPOSIT_CAP_EUR:,.0f} €"
                   .replace(",", " "))
    opened = account.get("opened_on")
    if opened:
        fifth = (pd.Timestamp(opened) + pd.DateOffset(years=5)).date().isoformat()
        early = [m["ts"] for m in mvs if m["kind"] == "withdrawal" and m["ts"] < fifth]
        if early:
            out.append(f"PEA : retrait le {early[0]} avant le 5e anniversaire ({fifth}) — entraîne en principe "
                       "la clôture du plan")
    flagged = sorted({m["symbol"] for m in mvs if m["kind"] == "buy" and m["symbol"]
                      and not m["symbol"].endswith(PEA_LIKELY_ELIGIBLE_SUFFIXES)})
    if flagged:
        out.append("PEA : titre(s) probablement non éligible(s) (place hors UE/EEE) : " + ", ".join(flagged))
    return out
