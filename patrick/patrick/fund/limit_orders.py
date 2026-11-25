"""Ordres limite et exécutions partielles des fonds simulés (A12).

Un ordre limite est une intention en attente (`fund_limit_order`, migration 0059), pas un ordre exécuté. `resolve` examine chaque séance
écoulée depuis la précédente vérification (jamais la séance du placement : avec des barres quotidiennes, on ne sait pas si le cours a touché
la limite avant ou après l'ordre) :
- achat : exécuté si le plus bas de la séance atteint la limite, au plus bas des deux entre l'ouverture et la limite (une ouverture sous la
  limite exécute à l'ouverture, comme un vrai carnet) ; vente : symétrique, sur le plus haut ;
- quantité : au plus `participation` du volume de la séance (10 % par défaut) ; le reste attend la séance suivante (exécution partielle).
  Sans volume connu (indices, change), tout est exécuté d'un coup. Pour une quantité entière (actions), les tranches restent entières ;
- validité : jusqu'à `expires_on` inclus (30 jours calendaires par défaut), puis l'ordre expire, ses exécutions déjà faites restant.
Chaque exécution passe par `service.place_order` (mêmes règles, frais et contrôles qu'un ordre saisi, prix « manual » = prix d'exécution,
note `limit:<id>`). Un refus (liquidités insuffisantes, règle de l'enveloppe) arrête l'ordre avec son motif (`rejected`).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3

import pandas as pd

from patrick.fund import prices, service, store

DEFAULT_VALIDITY_DAYS = 30
DEFAULT_PARTICIPATION = 0.10
LIVE = ("open", "partial")
EPS = 1e-9


def _direction(conn: sqlite3.Connection, req: dict) -> str:
    action = req.get("action") or "open"
    if action in ("open", "increase"):
        side = req.get("side")
        if action == "increase" or side is None:
            side = _position_side(conn, req)
        return "buy" if side == "long" else "sell"
    if action in ("reduce", "close"):
        return "sell" if _position_side(conn, req) == "long" else "buy"
    raise store.FundError(f"un ordre limite ne peut pas être de type {action!r}")


def _position_side(conn: sqlite3.Connection, req: dict) -> str:
    pid = req.get("position_id")
    for o in store.list_orders(conn, req["strategy_id"]):
        if o["position_id"] == pid and o["action"] == "open":
            return o["side"]
    raise store.FundError("position introuvable pour cet ordre limite")


def create(conn: sqlite3.Connection, req: dict, limit_price, *, expires_on=None, participation: float = DEFAULT_PARTICIPATION,
           today: dt.date | None = None) -> dict:
    """Enregistre un ordre limite (`req` : la demande de `service.place_order`, sans prix) ; renvoie la ligne créée."""
    today = service._today(today)
    try:
        limit = float(limit_price)
    except (TypeError, ValueError):
        raise store.FundError("prix limite invalide") from None
    if not math.isfinite(limit) or limit <= 0:
        raise store.FundError("le prix limite doit être positif")
    if not 0 < participation <= 1:
        raise store.FundError("la part du volume doit être comprise entre 0 et 100 %")
    if store.get_strategy(conn, req.get("strategy_id") or "") is None:
        raise store.FundError("stratégie introuvable")
    qty = float(req.get("quantity") or 0)
    if qty <= 0:
        raise store.FundError("quantité invalide pour un ordre limite")
    request = {k: v for k, v in req.items() if k not in ("price", "date", "limit_price", "expires_on", "participation")}
    if (request.get("action") or "open") == "open":
        request["position_id"] = request.get("position_id") or store.new_id("pos")
        request["symbol"] = str(request.get("symbol") or "").strip().upper()
    else:
        opening = next((o for o in store.list_orders(conn, request["strategy_id"])
                        if o["position_id"] == request.get("position_id") and o["action"] == "open"), None)
        if opening is None:
            raise store.FundError("position introuvable pour cet ordre limite")
        request["symbol"] = opening["symbol"]
    expires = pd.Timestamp(expires_on).date() if expires_on else today + dt.timedelta(days=DEFAULT_VALIDITY_DAYS)
    if expires < today:
        raise store.FundError("la date de validité est déjà passée")
    direction = _direction(conn, request)
    with conn:
        cur = conn.execute(
            "INSERT INTO fund_limit_order (strategy_id, symbol, direction, quantity, limit_price, participation, placed_on, expires_on, "
            "request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (request["strategy_id"], request["symbol"], direction, qty, limit, float(participation), today.isoformat(),
             expires.isoformat(), json.dumps(request, ensure_ascii=False)))
    return get(conn, cur.lastrowid)


def _row(r: sqlite3.Row | tuple, cols: list[str]) -> dict:
    d = dict(zip(cols, r, strict=True))
    d["request"] = json.loads(d.pop("request_json"))
    d["fills"] = json.loads(d.pop("fills_json") or "[]")
    d["remaining"] = max(d["quantity"] - d["filled_quantity"], 0.0)
    return d


def get(conn: sqlite3.Connection, limit_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM fund_limit_order WHERE limit_id = ?", (limit_id,))
    r = cur.fetchone()
    return _row(r, [c[0] for c in cur.description]) if r else None


def list_for(conn: sqlite3.Connection, strategy_id: str, live_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM fund_limit_order WHERE strategy_id = ?" + (" AND status IN ('open', 'partial')" if live_only else "")
    cur = conn.execute(sql + " ORDER BY limit_id DESC", (strategy_id,))
    cols = [c[0] for c in cur.description]
    return [_row(r, cols) for r in cur.fetchall()]


def cancel(conn: sqlite3.Connection, limit_id: int) -> dict:
    row = get(conn, limit_id)
    if row is None:
        raise store.FundError("ordre limite introuvable")
    if row["status"] not in LIVE:
        raise store.FundError("cet ordre limite n'est plus en attente")
    _update(conn, limit_id, status="cancelled", message="annulé")
    return get(conn, limit_id)


def _update(conn: sqlite3.Connection, limit_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = datetime('now')"
    with conn:
        conn.execute(f"UPDATE fund_limit_order SET {sets} WHERE limit_id = ?", (*fields.values(), limit_id))  # noms de colonnes internes


def fill_on_bar(direction: str, limit: float, bar: pd.Series) -> float | None:
    """Prix d'exécution sur une séance (ouverture, plus haut, plus bas), ou None si la limite n'est pas touchée."""
    o, h, lo = float(bar.get("open", bar["close"])), float(bar.get("high", bar["close"])), float(bar.get("low", bar["close"]))
    if direction == "buy":
        return min(o, limit) if lo <= limit + EPS else None
    return max(o, limit) if h >= limit - EPS else None


def _tranche(remaining: float, volume, participation: float, integral: bool) -> float:
    if volume is None or not math.isfinite(float(volume)) or float(volume) <= 0:
        return remaining
    cap = participation * float(volume)
    qty = min(remaining, math.floor(cap) if integral else cap)
    return qty if qty > EPS else 0.0


def resolve(conn: sqlite3.Connection, strategy_id: str | None = None, today: dt.date | None = None, bars_loader=None) -> list[dict]:
    """Examine les séances écoulées de chaque ordre limite en attente ; renvoie les ordres qui ont bougé (exécution, expiration, refus)."""
    today = service._today(today)
    bars_loader = bars_loader or (lambda symbol: prices.ensure_bars(conn, symbol).df)
    sql = "SELECT limit_id FROM fund_limit_order WHERE status IN ('open', 'partial')" + (" AND strategy_id = ?" if strategy_id else "")
    ids = [r[0] for r in conn.execute(sql + " ORDER BY limit_id", (strategy_id,) if strategy_id else ())]
    changed = []
    for limit_id in ids:
        row = get(conn, limit_id)
        before = (row["status"], row["filled_quantity"])
        _resolve_one(conn, row, today, bars_loader)
        after = get(conn, limit_id)
        if (after["status"], after["filled_quantity"]) != before:
            changed.append(after)
    return changed


def _resolve_one(conn: sqlite3.Connection, row: dict, today: dt.date, bars_loader) -> None:
    req, limit_id = row["request"], row["limit_id"]
    df = bars_loader(row["symbol"])
    start = pd.Timestamp(row["checked_through"] or row["placed_on"])
    last_day = min(pd.Timestamp(today), pd.Timestamp(row["expires_on"]))
    sessions = df.loc[(df.index > start) & (df.index <= last_day)] if df is not None and not df.empty else pd.DataFrame()
    filled, fills = float(row["filled_quantity"]), list(row["fills"])
    integral = float(row["quantity"]).is_integer()
    status, message, checked = row["status"], row.get("message"), row["checked_through"]
    for day, bar in sessions.iterrows():
        checked = day.date().isoformat()
        price = fill_on_bar(row["direction"], float(row["limit_price"]), bar)
        if price is None:
            continue
        remaining = float(row["quantity"]) - filled
        qty = _tranche(remaining, bar.get("volume"), float(row["participation"]), integral)
        if qty <= 0:
            continue
        last = remaining - qty <= EPS
        action = req.get("action") or "open"
        if action == "open" and filled > EPS:
            action = "increase"
        elif action == "close" and not last:
            action = "reduce"
        order = {**req, "action": action, "quantity": qty, "price": round(price, 6), "date": checked, "note": f"limit:{limit_id}"}
        if action in ("increase", "reduce"):
            order.pop("instrument_kind", None)
            order.pop("side", None)
        try:
            placed = service.place_order(conn, order, today=today)
        except (service.FundRuleError, store.FundError) as exc:
            detail = getattr(exc, "blocking", None) or str(exc)
            status, message = "rejected", f"refusé le {checked} : {detail}"
            break
        filled += qty
        fills.append({"day": checked, "quantity": qty, "price": round(price, 6), "order_id": placed.get("order_id")})
        status = "filled" if last else "partial"
        if last:
            break
    if status in LIVE and pd.Timestamp(today) >= pd.Timestamp(row["expires_on"]):
        status, message = "expired", ("expiré après exécution partielle" if filled > EPS else "expiré sans exécution")
    _update(conn, limit_id, status=status, filled_quantity=filled, fills_json=json.dumps(fills), checked_through=checked, message=message)
