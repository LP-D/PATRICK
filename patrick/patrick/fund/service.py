"""Cas d'usage du fonds : aperçu et passage d'ordres, correction, instantané
d'une stratégie, vue d'ensemble. Une fonction par écran/route ; la couche web
reste mince."""
from __future__ import annotations

import datetime as dt
import math
import re
import sqlite3
import threading

import pandas as pd

from patrick.clock import utc_today
from patrick.fund import engine, instruments, kpis, prices, rules, store
from patrick.fund import fees as fees_mod

TICK_HALF = 0.5
POSITION_ID_RE = re.compile(r"^pos_[0-9a-f]{10}$")      # format des identifiants que le serveur attribue
TEXT_FIELDS = ("strategy_id", "position_id", "symbol", "instrument_kind", "side", "action", "note", "date")
CONTINUOUS_SERIES_WARNING = "série continue, sauts de roll non corrigés"
MAX_STALE_DAYS = 4        # écart toléré entre aujourd'hui et la dernière séance (week-end prolongé, matin)
_WRITE_LOCK = threading.RLock()   # validation + écriture d'un ordre : jamais deux à la fois dans ce processus


class FundRuleError(ValueError):
    """Ordre refusé : `blocking` liste les motifs (422 à l'API)."""

    def __init__(self, blocking: list[str]):
        super().__init__("; ".join(blocking))
        self.blocking = blocking


def current_date() -> dt.date:
    """Date du jour, isolée pour que les tests de routes puissent la figer."""
    return utc_today()


def _today(today: dt.date | None) -> dt.date:
    return today or current_date()


def _opening(orders: list[dict], position_id: str) -> dict | None:
    return next((o for o in orders if o["position_id"] == position_id and o["action"] == "open"), None)


def _number(value, name: str, *, positive: bool = False) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError as exc:
        raise store.FundError(f"{name} invalide : {value!r}") from exc
    if not math.isfinite(out) or (positive and out <= 0):
        raise store.FundError(f"{name} invalide : {value!r}")
    return out


def _day(value, name: str = "date") -> pd.Timestamp:
    """Jour (sans heure ni fuseau) ; une valeur illisible est un refus lisible, jamais une exception."""
    try:
        day = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise store.FundError(f"{name} invalide : {value!r}") from exc
    if pd.isna(day):
        raise store.FundError(f"{name} invalide : {value!r}")
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    return day.normalize()


def _contract(spec: dict) -> tuple[int, int]:
    try:
        year, month = int(spec["year"]), int(spec["month"])
    except (KeyError, TypeError, ValueError) as exc:
        raise store.FundError("année et mois du contrat requis") from exc
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        raise store.FundError(f"contrat hors limites : {month}/{year}")
    return year, month


def _clean(req: dict) -> dict:
    """Types d'un corps de requête : texte, objet, entiers. Un champ mal typé est refusé avec son nom."""
    out = dict(req)
    for key in TEXT_FIELDS:
        if out.get(key) is not None and not isinstance(out[key], str):
            raise store.FundError(f"{key} invalide : texte attendu")
    if out.get("spec") is not None and not isinstance(out["spec"], dict):
        raise store.FundError("spec invalide : objet attendu")
    if out.get("note"):
        out["note"] = out["note"][:500]
    seed = out.get("fee_seed")
    if seed in (None, ""):
        out["fee_seed"] = None
    else:
        try:
            out["fee_seed"] = int(seed)
        except (TypeError, ValueError, OverflowError) as exc:
            raise store.FundError(f"graine des frais invalide : {seed!r}") from exc
        if not 0 <= out["fee_seed"] < 2**63:
            raise store.FundError(f"graine des frais invalide : {seed!r}")
    order_id = out.get("order_id")
    if order_id is not None and (isinstance(order_id, bool) or not isinstance(order_id, int)):
        raise store.FundError("order_id invalide : entier attendu")
    return out


def _check_new_position_id(conn: sqlite3.Connection, position_id: str, replace_order_id: int | None) -> None:
    """Un identifiant proposé par le client à l'ouverture : bien formé, et pas déjà celui d'une autre position
    (de n'importe quelle stratégie : la suppression d'une position se fait par cet identifiant)."""
    if not POSITION_ID_RE.fullmatch(position_id):
        raise store.FundError(f"identifiant de position invalide : {position_id[:40]!r}")
    own = store.get_order(conn, replace_order_id) if replace_order_id is not None else None
    if own is not None and own["position_id"] == position_id:           # correction de sa propre ouverture
        return
    if conn.execute("SELECT 1 FROM fund_order WHERE position_id = ? LIMIT 1", (position_id,)).fetchone():
        raise store.FundError("identifiant de position déjà utilisé")


def _execution_day(df: pd.DataFrame, requested, today: dt.date) -> tuple[pd.Timestamp, bool]:
    day = _day(requested)
    if day.date() > today:
        raise FundRuleError(["date d'exécution dans le futur"])
    known = df[df.index <= pd.Timestamp(today)]                  # jamais de cotation postérieure à aujourd'hui
    if known.empty or day < known.index[0]:
        first = (known.index[0] if not known.empty else df.index[0]).date()
        raise FundRuleError([f"pas de cotation avant le {first} pour ce symbole"])
    i = known.index.searchsorted(day)
    if i < len(known):
        exec_day = known.index[i]
    else:
        last = known.index[-1]
        if (pd.Timestamp(today) - last).days > MAX_STALE_DAYS:
            raise FundRuleError([(f"pas de cotation après le {last.date()} pour ce symbole "
                                  "(contrat échu ou données hors ligne)")])
        exec_day = last
    return exec_day, exec_day.date() == today


def _prepare(conn: sqlite3.Connection, req: dict, today: dt.date, replace_order_id: int | None = None) -> dict:
    req = _clean(req)
    strategy = store.get_strategy(conn, req.get("strategy_id") or "")
    if strategy is None:
        raise store.FundError("stratégie introuvable")
    base = strategy["base_currency"]
    orders = store.list_orders(conn, strategy["strategy_id"])
    action = req.get("action") or "open"
    if action not in store.ACTIONS:
        raise store.FundError(f"action inconnue : {action!r}")
    req_spec = dict(req.get("spec") or {})
    position_id = req.get("position_id")
    fut = None
    year = month = None
    if action == "open":
        kind, side = req.get("instrument_kind"), req.get("side")
        if kind not in store.INSTRUMENT_KINDS:
            raise store.FundError(f"type d'instrument inconnu : {kind!r}")
        if side not in ("long", "short"):
            raise store.FundError("sens requis : long ou short")
        if kind == "future":
            fut = instruments.FUTURES_CATALOG.get(str(req_spec.get("root") or ""))
            if fut is None:
                raise store.FundError("racine de future inconnue (voir le catalogue)")
            year, month = _contract(req_spec)
            if month not in fut.months:
                raise store.FundError(f"{fut.root} : pas de contrat en mois {month}")
            symbol = fut.yahoo_symbol(year, month)
        else:
            symbol = str(req.get("symbol") or "").strip().upper()
            if not symbol:
                raise store.FundError("symbole manquant")
        if position_id:
            _check_new_position_id(conn, position_id, replace_order_id)
        position_id = position_id or store.new_id("pos")
        opening = None
    else:
        opening = _opening(orders, position_id or "")
        if opening is None:
            raise store.FundError("position introuvable")
        kind, side, symbol = opening["instrument_kind"], opening["side"], opening["symbol"]
        if kind == "future":
            fut = instruments.FUTURES_CATALOG.get(opening["spec"].get("root"))

    bars = prices.ensure_bars(conn, symbol)
    if bars.df is None or bars.df.empty:
        raise FundRuleError([f"{symbol} : aucune cotation disponible"])
    currency = opening["currency"] if opening else bars.currency
    if not currency:
        raise FundRuleError([f"{symbol} : devise inconnue"])
    requested = _day(req.get("date") or today.isoformat())
    exec_day, provisional = _execution_day(bars.df, requested, today)
    expiry_iso = None
    if kind == "future":
        expiry_iso = opening["spec"].get("expiry") if opening else fut.expiry(year, month).isoformat()
    if expiry_iso and action in ("open", "increase") and exec_day.date().isoformat() >= expiry_iso:
        raise FundRuleError([f"contrat échu le {expiry_iso} : ordre impossible à partir de cette date"])
    manual_price = _number(req.get("price"), "prix", positive=True)
    price = manual_price if manual_price is not None else float(bars.df["close"].loc[exec_day])
    price_source = "manual" if manual_price is not None else "market"
    fx = 1.0
    if currency != base:
        series = prices.fx_series(conn, base, currency)
        if series is None or series[series.index <= exec_day].empty:
            raise FundRuleError([f"change {base}/{currency} indisponible"])
        fx = float(series[series.index <= exec_day].iloc[-1])

    mult = fut.multiplier if fut else 1.0
    quantity = _number(req.get("quantity"), "quantité", positive=True)
    amount = _number(req.get("amount"), "montant", positive=True)
    sized_by_amount = False
    if action in ("open", "increase"):
        if kind in engine.EQUITY_KINDS and quantity is None and amount is not None:
            sized_by_amount = True          # la quantité se calcule plus bas, une fois les frais connus
        elif quantity is None:
            raise store.FundError("quantité ou montant requis")
    elif action == "reduce" and quantity is None:
        raise store.FundError("quantité requise")
    elif action == "close" or action == "modify":
        quantity = 0.0
    if (action in ("open", "increase", "reduce") and kind in ("equity", "etf", "future")
            and quantity is not None):
        if abs(quantity - round(quantity)) > 1e-9 or round(quantity) < 1:
            raise store.FundError("quantité entière >= 1 requise")
        quantity = float(round(quantity))

    # --- composantes
    spec: dict = {}
    fee_ctx: dict = dict(opening["spec"].get("fee_ctx", {})) if opening else {}
    if action == "open":
        if kind == "future":
            spec.update({"root": fut.root, "year": year, "month": month,
                         "multiplier": fut.multiplier, "margin_per_unit": fut.margin,
                         "expiry": fut.expiry(year, month).isoformat()})
            fee_ctx = {"commission_per_contract_base": fut.commission * fx,
                       "tick_bps": TICK_HALF * fut.tick_size / price * 1e4}
        elif kind == "cfd":
            cls = instruments.classify_cfd_underlying(symbol)
            cap = instruments.CFD_LEVERAGE_CAPS[cls]
            leverage = _number(req_spec.get("leverage"), "levier", positive=True) or min(cap, 5.0)
            spec.update({"leverage": leverage, "underlying_class": cls})
            fee_ctx = {"fee_class": instruments.CFD_FEE_CLASS[cls]}
            if symbol.endswith("=F"):
                spec["price_quality"] = "continuous_roll_unadjusted"
        if kind in engine.DERIV_KINDS:
            spec["fee_ctx"] = fee_ctx
    if kind in engine.DERIV_KINDS and action in ("open", "modify"):
        for key in ("stop", "target"):
            if key in req_spec:
                spec[key] = _number(req_spec[key], key, positive=True)
        if action == "modify" and req_spec.get("leverage") not in (None, ""):
            spec["leverage"] = _number(req_spec["leverage"], "levier", positive=True)
        ref = price if action == "open" else bars.df["close"].iloc[-1]
        stop, target = spec.get("stop"), spec.get("target")
        if action == "open":
            if side == "long" and ((stop and stop >= ref) or (target and target <= ref)):
                raise FundRuleError(["long : stop sous le prix et objectif au-dessus"])
            if side == "short" and ((stop and stop <= ref) or (target and target >= ref)):
                raise FundRuleError(["short : stop au-dessus du prix et objectif en dessous"])

    # --- frais (fonction de la quantité : le dimensionnement par montant en a besoin)
    n_orders = sum(1 for o in orders if o["position_id"] == position_id) + 1
    fee_seed = req.get("fee_seed")
    if action != "modify" and req.get("fees_mode") != "manual":
        fee_seed = fee_seed or fees_mod.make_seed(strategy["strategy_id"], position_id,
                                                  exec_day.date().isoformat(), n_orders)
    adv = None
    vol = bars.df["volume"].tail(20).mean()
    if kind in engine.EQUITY_KINDS and vol and not math.isnan(vol):
        adv = float(vol) * price * fx

    def fees_for(qty: float):
        """(frais, origine, détail) d'un ordre de `qty` ; frais saisis, nuls (modification) ou estimés."""
        if action == "modify":
            return 0.0, "manual", None
        if req.get("fees_mode") == "manual":
            typed = _number(req.get("fees"), "frais")
            if typed is None or typed < 0:
                raise store.FundError("frais manuels : montant >= 0 requis")
            return typed, "manual", None
        ctx = fees_mod.FeeContext(kind=kind, notional_base=qty * mult * price * fx, quantity=qty,
                                  currency=currency, base_currency=base, adv_notional_base=adv, **fee_ctx)
        breakdown = fees_mod.estimate_fees(ctx, fee_seed)
        return breakdown.total, "estimated", breakdown

    if sized_by_amount:
        # « investir ce montant » : titres ET frais tiennent dans le montant (sinon « tout mon cash » serait refusé)
        unit = price * fx
        qty = math.floor(amount / unit)
        for _ in range(100):
            if qty < 1:
                break
            if qty * unit + fees_for(float(qty))[0] <= amount + 1e-9:
                break
            qty = min(qty - 1, math.floor((amount - fees_for(float(qty))[0]) / unit))
        else:
            qty = 0
        if qty < 1:
            raise FundRuleError(["montant insuffisant pour une action entière"])
        quantity = float(qty)

    if action == "close":
        quantity = _remaining(conn, strategy, orders, position_id, today)
    fees, fees_source, breakdown = fees_for(quantity)
    candidate = {
        "order_id": replace_order_id, "strategy_id": strategy["strategy_id"], "position_id": position_id,
        "ts": exec_day.date().isoformat(), "action": action, "instrument_kind": kind, "symbol": symbol,
        "side": side, "quantity": quantity, "price": None if action == "modify" else price,
        "price_source": None if action == "modify" else price_source, "currency": currency, "fx_rate": fx,
        "fees": fees, "fees_source": fees_source, "fee_seed": fee_seed, "spec": spec, "note": req.get("note"),
        "requested": requested.date().isoformat(),   # date demandée (≠ ts quand il n'y a pas de séance)
    }
    return {"strategy": strategy, "orders": orders, "candidate": candidate, "provisional": provisional,
            "breakdown": breakdown, "multiplier": mult, "opening": opening, "future": fut}


def _remaining(conn, strategy, orders, position_id, today) -> float:
    market, _ = prices.build_market(conn, [o for o in orders if o["position_id"] == position_id],
                                    strategy["base_currency"], with_rates=False)
    res = engine.simulate(strategy, orders, market, end=today)
    pos = next((p for p in res.positions if p["position_id"] == position_id), None)
    return float(pos["quantity"]) if pos else 0.0


def _evaluate(conn: sqlite3.Connection, prep: dict, today: dt.date) -> tuple[rules.Check, engine.SimResult, list[str]]:
    strategy, orders, cand = prep["strategy"], prep["orders"], prep["candidate"]
    market, notes = prices.build_market(conn, orders + [cand], strategy["base_currency"])
    check, result = rules.validate(strategy, orders, cand, market, today)
    return check, result, notes


def _leverage_on(orders: list[dict], position_id: str, day: str) -> float | None:
    """Levier de la position à `day` : celui de l'ouverture, ou de la dernière modification datée au plus de ce jour."""
    leverage = None
    for o in sorted((o for o in orders if o["position_id"] == position_id), key=lambda o: (o["ts"], o["order_id"])):
        if o["ts"] > day:
            break
        if o["action"] in ("open", "modify") and o["spec"].get("leverage") is not None:
            leverage = o["spec"]["leverage"]
    return leverage


def _preview(prep: dict, check: rules.Check, result: engine.SimResult, notes: list[str]) -> dict:
    c, mult = prep["candidate"], prep["multiplier"]
    price = c["price"]
    notional_local = None if price is None else c["quantity"] * mult * price
    notional_base = None if notional_local is None else notional_local * c["fx_rate"]
    margin = None
    if c["instrument_kind"] == "future":
        margin = c["quantity"] * prep["future"].margin * c["fx_rate"]
    elif c["instrument_kind"] == "cfd" and notional_base is not None:
        leverage = c["spec"].get("leverage") or _leverage_on(prep["orders"], c["position_id"], c["ts"]) or 1.0
        margin = notional_base / float(leverage)
    underlying = None
    if c["instrument_kind"] == "cfd":
        underlying = c["spec"].get("underlying_class") or (prep["opening"] or {}).get("spec", {}).get("underlying_class")
    day = pd.Timestamp(c["ts"])
    row = result.daily.loc[day] if day in result.daily.index else None
    b = prep["breakdown"]
    warnings = check.warnings + notes
    if c["spec"].get("price_quality") or (prep["opening"] or {}).get("spec", {}).get("price_quality"):
        warnings = [*warnings, CONTINUOUS_SERIES_WARNING]
    return {
        "ok": not check.blocking, "blocking": check.blocking, "warnings": warnings,
        "order": {k: v for k, v in c.items() if k != "spec"} | {"spec": c["spec"]},
        "preview": {
            "symbol": c["symbol"], "exec_day": c["ts"], "price": price, "price_source": c["price_source"],
            "currency": c["currency"], "fx_rate": c["fx_rate"], "quantity": c["quantity"],
            "notional_local": notional_local, "notional_base": notional_base, "margin_required": margin,
            "fees": {"total": c["fees"], "source": c["fees_source"], "seed": c["fee_seed"],
                     "commission": b.commission if b else None, "spread": b.spread if b else None,
                     "fx": b.fx if b else None},
            "buying_power_after": None if row is None else float(row["buying_power"]),
            "cash_after": None if row is None else float(row["cash"]),
            "provisional": prep["provisional"], "position_id": c["position_id"],
            "underlying_class": underlying,
            "leverage_cap": instruments.CFD_LEVERAGE_CAPS.get(underlying) if underlying else None,
        },
    }


def quote(conn: sqlite3.Connection, req: dict, today: dt.date | None = None) -> dict:
    """Aperçu d'un ordre : ne bloque pas, n'écrit rien, renvoie motifs de refus et avertissements."""
    today = _today(today)
    try:
        prep = _prepare(conn, req, today, replace_order_id=req.get("order_id"))
    except FundRuleError as exc:
        return {"ok": False, "blocking": exc.blocking, "warnings": [], "order": None, "preview": None}
    except store.FundError as exc:       # saisie en cours : motif affiché, pas une erreur HTTP
        return {"ok": False, "blocking": [str(exc)], "warnings": [], "order": None, "preview": None}
    check, result, notes = _evaluate(conn, prep, today)
    return _preview(prep, check, result, notes)


def place_order(conn: sqlite3.Connection, req: dict, today: dt.date | None = None) -> dict:
    today = _today(today)
    with _WRITE_LOCK:
        prep = _prepare(conn, req, today)
        check, result, notes = _evaluate(conn, prep, today)
        if check.blocking:
            raise FundRuleError(check.blocking)
        order_id = store.insert_order(conn, prep["candidate"])
    return {"order_id": order_id, **_preview(prep, check, result, notes)}


def correct_order(conn: sqlite3.Connection, order_id: int, req: dict, today: dt.date | None = None) -> dict:
    """Corrige l'ordre d'ouverture d'une position (instrument et sens inchangés)."""
    today = _today(today)
    existing = store.get_order(conn, order_id)
    if existing is None or existing["action"] != "open":
        raise store.FundError("seul l'ordre d'ouverture d'une position peut être corrigé")
    merged = {**req, "strategy_id": existing["strategy_id"], "action": "open",
              "position_id": existing["position_id"], "instrument_kind": existing["instrument_kind"],
              "side": existing["side"], "symbol": existing["symbol"]}
    if req.get("spec") is not None and not isinstance(req["spec"], dict):
        raise store.FundError("spec invalide : objet attendu")
    if existing["instrument_kind"] == "future":
        merged["spec"] = {**{k: existing["spec"][k] for k in ("root", "year", "month")}, **(req.get("spec") or {})}
    # Ce que la correction ne mentionne pas reste tel quel : date, prix et frais saisis à la main, tirage des frais.
    merged.setdefault("date", existing["ts"])
    if "price" not in req and existing["price_source"] == "manual":
        merged["price"] = existing["price"]
    if "fees_mode" not in req:
        if existing["fees_source"] == "manual":
            merged["fees_mode"], merged["fees"] = "manual", existing["fees"]
        else:
            merged["fees_mode"] = "estimated"
    if merged["fees_mode"] != "manual":
        merged.setdefault("fee_seed", existing["fee_seed"])
    with _WRITE_LOCK:
        prep = _prepare(conn, merged, today, replace_order_id=order_id)
        check, result, notes = _evaluate(conn, prep, today)
        if check.blocking:
            raise FundRuleError(check.blocking)
        store.update_order(conn, order_id, prep["candidate"])
    return {"order_id": order_id, **_preview(prep, check, result, notes)}


# ------------------------------------------------------------- instantanés

def strategy_snapshot(conn: sqlite3.Connection, strategy: dict, today: dt.date | None = None) -> dict:
    today = _today(today)
    orders = store.list_orders(conn, strategy["strategy_id"])
    market, notes = prices.build_market(conn, orders, strategy["base_currency"])
    result = engine.simulate(strategy, orders, market, end=today)
    return {"strategy": strategy, "kpis": kpis.compute(strategy, result), "positions": result.positions,
            "series": kpis.series_points(result.daily), "orders": orders, "notes": notes,
            "violations": [v["message"] for v in result.violations],
            "alert_days": result.alert_days}


def overview(conn: sqlite3.Connection, today: dt.date | None = None) -> dict:
    snaps = [strategy_snapshot(conn, s, today) for s in store.list_strategies(conn)]
    capital = sum(s["kpis"]["capital"] for s in snaps)
    nav = sum(s["kpis"]["nav"] for s in snaps)
    breakdown = [{"strategy_id": s["strategy"]["strategy_id"], "name": s["strategy"]["name"],
                  "wrapper": s["strategy"]["wrapper"], "nav": s["kpis"]["nav"],
                  "share": s["kpis"]["nav"] / nav if nav > 0 else None} for s in snaps]
    return {"strategies": snaps,
            "fund": {"nav": nav, "capital": capital, "pnl": nav - capital,
                     "pnl_pct": (nav - capital) / capital if capital else None, "n_strategies": len(snaps),
                     "breakdown": breakdown}}
