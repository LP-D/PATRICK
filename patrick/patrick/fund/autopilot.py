"""Fonds, chantier 3 : pilote automatique. Spécification : `docs/superpowers/specs/2026-10-16-fonds-pilote-automatique-design.md`.

Une stratégie en pilote automatique choisit seule les modèles à trader (`fund.selection`), leur donne un instrument et une
taille (volatilité inverse, exposition brute `gross`), puis fait tourner pour chacun une règle « direction + sortie à
l'horizon » (`fund.systematic`) : une position par signal, fermée à l'horizon du modèle, renouvelée tant que le signal tient.
Un cycle (`run`) est idempotent et se relance chaque jour après les prédictions.

Les règles du pilote (`config.managed`) sont à sens unique : une règle neuve démarre le jour de sa création (jamais de
rejeu du passé avec une sélection faite aujourd'hui), et une règle dont le modèle, l'instrument ou un réglage de
comportement change n'est pas réécrite : elle est retirée (elle ne prend plus de signal après la veille, ses positions
ouvertes se ferment à leur échéance) et une règle neuve prend la suite. Les règles saisies à la main ne sont jamais touchées.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from patrick.config import universe_extension as UX
from patrick.fund import instruments, prices, selection, service, store, systematic

logger = logging.getLogger("patrick.fund.autopilot")

MANAGER = "autopilot"
MAX_GROSS = 2.0
VOL_WINDOW = 60                  # séances de la volatilité qui pondère les cibles
SIZING_TOLERANCE = 0.10          # une taille ne change que si le budget a bougé de plus de 10 %

LABELS = {
    "pea": "PEA : seulement des actions et ETF au comptant",
    "no_quotes": "cotation indisponible",
    "too_small": "budget trop petit pour une position",
}


# --------------------------------------------------------------------------- réglages

@dataclass(frozen=True)
class Settings:
    selection: selection.Policy = field(default_factory=selection.Policy)
    gross: float = 1.0
    allow_short: bool = True
    min_confidence: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict | None) -> Settings:
        raw = raw or {}
        if not isinstance(raw, dict):
            raise store.FundError("réglages du pilote invalides : objet attendu")
        base = cls()
        gross = _number(raw.get("gross", base.gross), "gross")
        if not 0.0 < gross <= MAX_GROSS:
            raise store.FundError(f"gross invalide : entre 0 (exclu) et {MAX_GROSS:g} (inclus) attendu")
        allow_short = raw.get("allow_short", base.allow_short)
        if not isinstance(allow_short, bool):
            raise store.FundError("allow_short invalide : booléen attendu")
        confidence = _number(raw.get("min_confidence", base.min_confidence), "min_confidence")
        if not 0.0 <= confidence < 1.0:
            raise store.FundError("min_confidence invalide : entre 0 (inclus) et 1 (exclu) attendu")
        return cls(selection=selection.Policy.from_dict(raw), gross=gross, allow_short=allow_short,
                   min_confidence=confidence)

    def to_dict(self) -> dict:
        return {**self.selection.to_dict(), "gross": self.gross, "allow_short": self.allow_short,
                "min_confidence": self.min_confidence}


def _number(value, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise store.FundError(f"{name} invalide : nombre attendu ({value!r})") from exc
    if isinstance(value, bool) or not math.isfinite(out):
        raise store.FundError(f"{name} invalide : nombre fini attendu")
    return out


def configure(conn: sqlite3.Connection, strategy_id: str, raw: dict | None) -> dict:
    """Active le pilote automatique de la stratégie avec ces réglages (les absents prennent leur défaut)."""
    if store.get_strategy(conn, strategy_id) is None:
        raise store.FundError("stratégie introuvable")
    settings = Settings.from_dict(raw)
    stored = {**(store.get_autopilot(conn, strategy_id) or {}), "enabled": True, "settings": settings.to_dict()}
    store.set_autopilot(conn, strategy_id, stored)
    return stored


def _enabled(conn: sqlite3.Connection, strategy_id: str) -> tuple[dict, dict, Settings]:
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        raise store.FundError("stratégie introuvable")
    stored = store.get_autopilot(conn, strategy_id)
    if not stored or not stored.get("enabled"):
        raise store.FundError("le pilote automatique n'est pas activé sur cette stratégie")
    return strategy, stored, Settings.from_dict(stored.get("settings"))


# --------------------------------------------------------------------------- instrument et taille

def _instrument_for(symbol: str, wrapper: str, settings: Settings, groups: dict[str, str]) -> tuple[dict | None, bool, str | None]:
    """`(instrument, allow_short, motif d'exclusion)`. Comptant (action ou ETF, achat seulement) quand c'est possible et
    que la vente à découvert n'est pas demandée, sinon CFD ; en PEA, comptant et achat seulement."""
    sym = symbol.upper()
    cash_ok = instruments.classify_cfd_underlying(sym) == "equity" and not sym.endswith(".NYB")
    kind = "etf" if "ETF" in groups.get(symbol, "") else "equity"
    if wrapper == "PEA":
        if not cash_ok:
            return None, False, LABELS["pea"]
        return {"kind": kind, "symbol": sym, "spec": {}}, False, None
    if cash_ok and not settings.allow_short:
        return {"kind": kind, "symbol": sym, "spec": {}}, False, None
    return {"kind": "cfd", "symbol": sym, "spec": {}}, settings.allow_short, None


def _volatility(conn: sqlite3.Connection, symbol: str, today: dt.date) -> float | None:
    """σ des rendements des `VOL_WINDOW` dernières séances connues à `today` (jamais le futur), ou None sans cotation."""
    df = prices.ensure_bars(conn, symbol).df
    if df is None or df.empty:
        return None
    close = df["close"].dropna()
    close = close[close.index <= pd.Timestamp(today)]
    vol = float(close.pct_change().dropna().tail(VOL_WINDOW).std()) if len(close) > 2 else float("nan")
    return vol if math.isfinite(vol) and vol > 0 else None


def _unit_notional(conn: sqlite3.Connection, strategy_id: str, symbol: str, today: dt.date) -> float | None:
    """Valeur, en devise de la stratégie, d'une unité de CFD au dernier cours connu (cotation de sonde : rien n'est placé)."""
    quote = service.quote(conn, {"strategy_id": strategy_id, "action": "open", "instrument_kind": "cfd", "symbol": symbol,
                                 "side": "long", "quantity": 1}, today)
    preview = quote.get("preview")
    value = preview.get("notional_base") if preview else None
    return float(value) if value else None


def _stable_sizing(old: dict | None, new: dict) -> dict:
    """Garde l'ancienne taille tant que le nouveau budget ne l'écarte pas de plus de `SIZING_TOLERANCE`."""
    if old:
        for key in ("amount", "quantity"):
            if key in old and key in new and old[key] and abs(new[key] - old[key]) / old[key] < SIZING_TOLERANCE:
                return old
    return new


def _reject(excluded: list[dict], model: dict, code: str, detail: str | None = None) -> None:
    excluded.append({"target": model["target"], "horizon": model["horizon"], "code": code, "label": LABELS[code],
                     "detail": detail or LABELS[code]})


def build_plan(conn: sqlite3.Connection, strategy: dict, settings: Settings, today: dt.date) -> dict:
    """Sélection, instruments, volatilités et tailles : tout ce que le cycle appliquera, sans rien écrire (hors cache des
    cotations). `selected` : modèles retenus avec `instrument`, `allow_short`, `sizing`, `notional`, `weight`, `vol` ;
    `excluded` : toutes les cellules écartées (sélection puis pilote) avec leur motif."""
    chosen = selection.select_models(conn, settings.selection, today)
    excluded = list(chosen["excluded_cells"])
    groups = {sym: group for group, items in UX.all_target_groups().items() for sym, _ in items}
    capital = float(strategy["initial_capital"])
    priced: list[dict] = []
    for model in chosen["selected"]:
        instrument, allow_short, why = _instrument_for(model["target"], strategy["wrapper"], settings, groups)
        if instrument is None:
            _reject(excluded, model, "pea", why)
            continue
        vol = _volatility(conn, model["target"], today)
        unit = _unit_notional(conn, strategy["strategy_id"], instrument["symbol"], today) if instrument["kind"] == "cfd" else None
        if vol is None or (instrument["kind"] == "cfd" and unit is None):
            _reject(excluded, model, "no_quotes")
            continue
        priced.append({**model, "instrument": instrument, "allow_short": allow_short, "vol": vol, "unit_notional": unit})
    inverse = {target: 1.0 / next(m["vol"] for m in priced if m["target"] == target) for target in {m["target"] for m in priced}}
    total, per_target = sum(inverse.values()), {t: sum(1 for m in priced if m["target"] == t) for t in inverse}
    selected = []
    for model in priced:
        weight = inverse[model["target"]] / total / per_target[model["target"]]
        notional = settings.gross * capital * weight
        if model["instrument"]["kind"] == "cfd":
            quantity = round(notional / model["unit_notional"], 4)
            sizing = {"quantity": quantity}
            if quantity < systematic.MIN_CFD_QUANTITY:
                _reject(excluded, model, "too_small")
                continue
        else:
            sizing = {"amount": round(notional, 2)}
        selected.append({**{k: v for k, v in model.items() if k != "unit_notional"}, "weight": weight,
                         "notional": notional, "sizing": sizing})
    counts: dict[str, int] = {}
    for cell in excluded:
        counts[cell["code"]] = counts.get(cell["code"], 0) + 1
    return {"settings": settings.to_dict(), "n_cells": chosen["n_cells"], "capital": capital, "gross": settings.gross,
            "selected": selected, "excluded": excluded,
            "excluded_summary": [{"code": code, "label": selection.LABELS.get(code) or LABELS[code], "n": n}
                                 for code, n in counts.items()]}


def preview(conn: sqlite3.Connection, strategy_id: str, today: dt.date | None = None,
            settings: Settings | None = None) -> dict:
    """Ce que le pilote ferait aujourd'hui avec `settings` (sinon les réglages enregistrés, sinon ceux par défaut) :
    rien n'est écrit."""
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        raise store.FundError("stratégie introuvable")
    if settings is None:
        settings = Settings.from_dict((store.get_autopilot(conn, strategy_id) or {}).get("settings"))
    return build_plan(conn, strategy, settings, service._today(today))


def status(conn: sqlite3.Connection, strategy_id: str, rules: list[dict] | None = None) -> dict:
    """État du pilote d'une stratégie : activé ou non, réglages (par défaut si jamais configuré), dernier cycle, règles du
    pilote (résumés de `systematic.rule_summaries`, passés par l'appelant s'il les a déjà)."""
    if store.get_strategy(conn, strategy_id) is None:
        raise store.FundError("stratégie introuvable")
    stored = store.get_autopilot(conn, strategy_id) or {}
    if rules is None:
        rules = systematic.rule_summaries(conn, strategy_id)
    return {"enabled": bool(stored.get("enabled")), "settings": Settings.from_dict(stored.get("settings")).to_dict(),
            "last_run": stored.get("last_run"),
            "rules": [r for r in rules if (r["config"].get("managed") or {}).get("by") == MANAGER]}


# --------------------------------------------------------------------------- cycle

def _rule_config(model: dict, settings: Settings, since: str) -> dict:
    return {"trial_id": model["trial_id"], "segment": "live", "allow_short": model["allow_short"],
            "signal": {"mode": "direction", "min_confidence": settings.min_confidence},
            "hold": {"mode": "horizon", "sessions": model["horizon"]},
            "instrument": model["instrument"], "sizing": model["sizing"], "since": since,
            "managed": {"by": MANAGER, "target": model["target"], "horizon": model["horizon"]}}


def _signature(cfg: dict) -> tuple:
    """Ce qui fait le comportement d'une règle : si cela change, on ne la réécrit pas, on en commence une autre."""
    instrument = cfg["instrument"]
    return (cfg["trial_id"], instrument["kind"], instrument["symbol"].upper(), bool(cfg["allow_short"]),
            cfg["signal"].get("min_confidence", 0.0), cfg["hold"].get("sessions"))


def managed_rules(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    """Règles du pilote (actives et retirées), les plus anciennes d'abord."""
    return [r for r in systematic.list_rules(conn, strategy_id) if (r["config"].get("managed") or {}).get("by") == MANAGER]


def run(conn: sqlite3.Connection, strategy_id: str, today: dt.date | None = None) -> dict:
    """Un cycle : sélectionner, ajuster les règles du pilote, appliquer chacune. Idempotent. Rend le compte rendu et
    l'enregistre (`last_run`) avec les réglages."""
    today = service._today(today)
    strategy, stored, settings = _enabled(conn, strategy_id)
    plan = build_plan(conn, strategy, settings, today)
    desired = {(m["target"], m["horizon"]): m for m in plan["selected"]}
    report: dict = {"day": today.isoformat(), "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                    "selected": len(desired), "created": [], "updated": [], "retired": [], "failed": [], "refused": [],
                    "placed": 0, "pending": 0}

    active: dict[tuple, dict] = {}
    for rule in managed_rules(conn, strategy_id):
        if "retired_on" not in rule["config"]:
            active[(rule["config"]["managed"]["target"], rule["config"]["managed"]["horizon"])] = rule
    yesterday, since = (today - dt.timedelta(days=1)).isoformat(), today.isoformat()
    for key, rule in list(active.items()):
        want = desired.get(key)
        if want is None or _signature(rule["config"]) != _signature(_rule_config(want, settings, since)):
            systematic.retire_rule(conn, rule["rule_id"], yesterday)
            report["retired"].append(rule["rule_id"])
            del active[key]
        elif (sizing := _stable_sizing(rule["config"]["sizing"], want["sizing"])) != rule["config"]["sizing"]:
            systematic.update_rule_config(conn, rule["rule_id"], {**rule["config"], "sizing": sizing})
            report["updated"].append(rule["rule_id"])
    for key, model in desired.items():
        if key in active:
            continue
        try:
            rule_id = systematic.create_rule(conn, strategy_id, f"Auto · {model['target']} h{model['horizon']}",
                                             _rule_config(model, settings, since))
        except store.FundError as exc:
            report["failed"].append({"target": model["target"], "horizon": model["horizon"], "reason": str(exc)})
        else:
            report["created"].append(rule_id)
            active[key] = {"rule_id": rule_id}
    report["rules"] = len(active)

    for rule in managed_rules(conn, strategy_id):                  # actives et retirées : une retirée finit de fermer
        meta = rule["config"]["managed"]
        try:
            result = systematic.apply(conn, rule["rule_id"], today)
        except store.FundError as exc:
            report["failed"].append({"target": meta["target"], "horizon": meta["horizon"], "reason": str(exc)})
            continue
        report["placed"] += len(result["placed"])
        report["pending"] += len(result["pending"])
        report["refused"] += [{"target": meta["target"], "horizon": meta["horizon"], **r} for r in result["refused"]]
    report["excluded"] = plan["excluded_summary"]

    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k != "excluded"}
    store.set_autopilot(conn, strategy_id, {**stored, "last_run": summary})
    return report


def run_all(conn: sqlite3.Connection, today: dt.date | None = None) -> list[dict]:
    """Un cycle pour chaque stratégie active dont le pilote est activé. Une erreur n'arrête pas les autres."""
    out: list[dict] = []
    for strategy in store.list_strategies(conn):
        stored = store.get_autopilot(conn, strategy["strategy_id"])
        if not stored or not stored.get("enabled"):
            continue
        try:
            out.append({"strategy_id": strategy["strategy_id"], **run(conn, strategy["strategy_id"], today)})
        except Exception as exc:                                   # isoler une stratégie des autres
            logger.exception("autopilot failed for %s", strategy["strategy_id"])
            out.append({"strategy_id": strategy["strategy_id"], "error": str(exc)})
    return out


def disable(conn: sqlite3.Connection, strategy_id: str) -> dict:
    """Désactive le pilote : ses règles sont supprimées, les ordres déjà passés restent (les positions ouvertes aussi : à
    fermer à la main)."""
    if store.get_strategy(conn, strategy_id) is None:
        raise store.FundError("stratégie introuvable")
    removed = 0
    for rule in managed_rules(conn, strategy_id):
        removed += int(systematic.delete_rule(conn, rule["rule_id"]))
    stored = store.get_autopilot(conn, strategy_id)
    if stored is not None:
        store.set_autopilot(conn, strategy_id, {**stored, "enabled": False})
    return {"removed_rules": removed}
