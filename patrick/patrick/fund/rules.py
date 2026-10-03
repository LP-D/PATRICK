"""Règles d'enveloppe et de marge (spec §9).

Deux étages : `static_checks` (propres à l'ordre : sens, type, devise,
plafond de levier) et `validate`, qui rejoue TOUTE la chronologie de la
stratégie avec l'ordre candidat et ne retient que les violations nouvelles
par rapport à la chronologie existante -- un ordre antidaté est refusé s'il
invalide un événement postérieur, sans que d'anciennes anomalies de données
bloquent définitivement la stratégie."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from patrick.fund import engine, instruments
from patrick.wealth.ledger import PEA_LIKELY_ELIGIBLE_SUFFIXES


@dataclass
class Check:
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def static_checks(strategy: dict, order: dict, today: dt.date) -> Check:
    chk = Check()
    action, kind, side = order["action"], order["instrument_kind"], order["side"]
    spec = order.get("spec") or {}
    if order["ts"] > today.isoformat():
        chk.blocking.append("date d'exécution dans le futur")
    if order["ts"] < strategy["opened_on"]:
        chk.blocking.append(f"date antérieure à l'ouverture de la stratégie ({strategy['opened_on']})")
    if action in ("open", "increase", "reduce") and not (order.get("quantity") and order["quantity"] > 0):
        chk.blocking.append("quantité strictement positive requise")
    if action != "modify" and not (order.get("price") and order["price"] > 0):
        chk.blocking.append("prix indisponible")
    if kind in engine.EQUITY_KINDS and side == "short":
        chk.blocking.append("vente à découvert impossible sur action/ETF (compte comptant) : passer par un CFD "
                            "ou un future")
    if strategy["wrapper"] == "PEA":
        if side == "short":
            chk.blocking.append("PEA : positions longues seulement")
        if kind in engine.DERIV_KINDS:
            chk.blocking.append("PEA : ni future ni CFD")
        if order["currency"] != "EUR":
            chk.blocking.append("PEA : titres cotés en euro seulement")
        if kind in engine.EQUITY_KINDS and not order["symbol"].endswith(PEA_LIKELY_ELIGIBLE_SUFFIXES):
            chk.warnings.append(f"PEA : {order['symbol']} probablement non éligible (place hors UE/EEE)")
    if kind == "cfd" and action in ("open", "modify") and spec.get("leverage") is not None:
        cap = instruments.cfd_leverage_cap(order["symbol"])
        if float(spec["leverage"]) > cap:
            chk.blocking.append(f"CFD : levier {float(spec['leverage']):g}:1 > plafond {cap:g}:1 pour cette classe "
                                "d'actifs (client non professionnel)")
        if float(spec["leverage"]) < 1:
            chk.blocking.append("CFD : levier minimal 1:1")
    return chk


def validate(strategy: dict, orders: list[dict], candidate: dict, market: engine.MarketData, today: dt.date,
             baseline: engine.SimResult | None = None) -> tuple[Check, engine.SimResult]:
    """`orders` = chronologie SANS le candidat ; si le candidat porte un `order_id`
    déjà présent dans `orders`, il le remplace (correction)."""
    chk = static_checks(strategy, candidate, today)
    cid = candidate.get("order_id")
    timeline = [o for o in orders if cid is None or o.get("order_id") != cid] + [candidate]
    result = engine.simulate(strategy, timeline, market, end=today)
    if baseline is None:
        baseline = engine.simulate(strategy, orders, market, end=today)
    known = {v["message"] for v in baseline.violations}
    chk.blocking.extend(v["message"] for v in result.violations if v["message"] not in known)
    if result.alert_days:
        chk.warnings.append(f"marge : la valeur nette passe sous 50 % de la marge requise "
                            f"({len(result.alert_days)} jour(s), dès le {result.alert_days[0]})")
    return chk, result
