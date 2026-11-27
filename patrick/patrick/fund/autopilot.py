"""Fonds, chantier 3 : pilote automatique. Spécification : `docs/superpowers/specs/2026-10-16-fonds-pilote-automatique-design.md`.

Une stratégie en pilote automatique choisit seule les modèles à trader (`fund.selection`), leur donne un instrument et une
taille (volatilité inverse, exposition brute `gross`), puis fait tourner pour chacun une règle « direction + sortie à
l'horizon » (`fund.systematic`) : une position par signal, fermée à l'horizon du modèle, renouvelée tant que le signal tient.
Un cycle (`run`) est idempotent et se relance chaque jour après les prédictions.

Les règles du pilote (`config.managed`) sont à sens unique : une règle neuve démarre le jour de sa création (jamais de
rejeu du passé avec une sélection faite aujourd'hui), et une règle dont l'instrument ou un réglage de comportement change
n'est pas réécrite : elle est retirée (elle ne prend plus de signal après la veille, ses positions ouvertes se ferment à leur
échéance) et une règle neuve prend la suite. Quand c'est le MODÈLE d'une cellule qui change (nouveau champion), la règle de
l'ancien modèle est supprimée avec ses ordres (`_purge_previous_models`) : son P&L sort du fonds, celui des autres cellules
reste. Les règles saisies à la main ne sont jamais touchées.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import math
import sqlite3
import threading
from dataclasses import dataclass, field

import pandas as pd

from patrick.config import universe_extension as UX
from patrick.data.session_calendar import classify_asset_class
from patrick.fund import (
    combo as combo_mod,
)
from patrick.fund import (
    envelopes,
    insight,
    instruments,
    prices,
    selection,
    service,
    store,
    systematic,
)
from patrick.system import interprocess_lock
from patrick.tracking import db as trackdb

logger = logging.getLogger("patrick.fund.autopilot")

MANAGER = "autopilot"
MAX_GROSS = 2.0
VOL_WINDOW = 60                  # séances de la volatilité qui pondère les cibles
VOL_MODELS = ("trailing", "har")  # volatilité glissante, ou prévision HAR du lendemain (`fund/vol_forecast.py`, A1)
WEIGHTINGS = ("inverse_vol", "risk_parity")
RISK_PARITY_WINDOW = 250          # séances de rendements communs pour la covariance de la parité de risque
SIZING_TOLERANCE = 0.10          # une taille ne change que si le budget a bougé de plus de 10 %

LABELS = {
    "pea": "PEA : seulement des actions cotées au comptant (ni indice, ni devise, ni matière première, ni crypto, ni future)",
    "pea_etf": "PEA : ETF exclus (seuls certains ETF sont éligibles, la base ne dit pas lesquels)",
    "pea_zone": "PEA : action hors UE/EEE (États-Unis, Asie, Royaume-Uni, Suisse...)",
    "pea_devise": "PEA : action de l'UE/EEE cotée hors euro (refusée par la règle « euro seulement »)",
    "no_quotes": "cotation indisponible",
    "too_small": "budget trop petit pour une position",
    "min_size": "capital insuffisant pour une position d'au moins la taille minimale (les frais forfaitaires la rongeraient)",
}


# --------------------------------------------------------------------------- réglages

@dataclass(frozen=True)
class Settings:
    selection: selection.Policy = field(default_factory=selection.Policy)
    gross: float = 1.0
    allow_short: bool = True
    min_confidence: float = 0.0
    max_class_share: float = 1.0                     # part maximale de l'exposition brute sur une même classe d'actifs (1 = sans plafond)
    max_drawdown: float | None = None                # repli sous le plus haut au-delà duquel le pilote n'ouvre plus rien (None = sans arrêt)
    min_position: float | None = None                # € : taille minimale d'une position ; les modèles les moins bien classés qui n'y atteignent pas sont écartés (None = aucune)
    combo: dict | None = None                        # fonds de test combiné (`fund/combo.py`) : {rl, vol, cost_multiple} ; None = signal de direction brut
    vol_model: str = "trailing"                      # volatilité qui dimensionne : « trailing » (60 séances) ou « har » (prévision HAR, A1)
    weighting: str = "inverse_vol"                   # « inverse_vol » (corrélations ignorées) ou « risk_parity » (contributions égales, A30)

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
        share = _number(raw.get("max_class_share", base.max_class_share), "max_class_share")
        if not 0.0 < share <= 1.0:
            raise store.FundError("max_class_share invalide : entre 0 (exclu) et 1 (inclus) attendu")
        drawdown = raw.get("max_drawdown", base.max_drawdown)
        if drawdown is not None:
            drawdown = _number(drawdown, "max_drawdown")
            if not 0.0 < drawdown < 1.0:
                raise store.FundError("max_drawdown invalide : entre 0 et 1 (exclus) attendu, ou vide")
        minimum = raw.get("min_position", base.min_position)
        if minimum is not None:
            minimum = _number(minimum, "min_position")
            if minimum <= 0:
                raise store.FundError("min_position invalide : montant strictement positif attendu, ou vide")
        vol_model = raw.get("vol_model", base.vol_model)
        if vol_model not in VOL_MODELS:
            raise store.FundError(f"vol_model invalide : {', '.join(VOL_MODELS)} attendu")
        weighting = raw.get("weighting", base.weighting)
        if weighting not in WEIGHTINGS:
            raise store.FundError(f"weighting invalide : {', '.join(WEIGHTINGS)} attendu")
        return cls(selection=selection.Policy.from_dict(raw), gross=gross, allow_short=allow_short,
                   min_confidence=confidence, max_class_share=share, max_drawdown=drawdown, min_position=minimum,
                   combo=combo_mod.check_settings(raw.get("combo")), vol_model=vol_model, weighting=weighting)

    def to_dict(self) -> dict:
        return {**self.selection.to_dict(), "gross": self.gross, "allow_short": self.allow_short,
                "min_confidence": self.min_confidence, "max_class_share": self.max_class_share, "max_drawdown": self.max_drawdown,
                "min_position": self.min_position, "combo": self.combo, "vol_model": self.vol_model, "weighting": self.weighting}


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
    before = store.get_autopilot(conn, strategy_id) or {}
    stored = {**before, "enabled": True, "settings": settings.to_dict()}
    store.set_autopilot(conn, strategy_id, stored)
    if not before.get("enabled") or before.get("settings") != stored["settings"]:
        _log_settings(conn, strategy_id, "update" if before.get("enabled") else "enable", before.get("settings"), stored["settings"])
    return stored


def _log_settings(conn: sqlite3.Connection, strategy_id: str, action: str, before: dict | None, after: dict | None) -> None:
    """FO12 (25/11) : historique daté des réglages (`fund_settings_log`, migration 0060). Une base plus ancienne sans la table : rien."""
    with contextlib.suppress(sqlite3.Error):
        conn.execute("INSERT INTO fund_settings_log (strategy_id, action, before_json, after_json) VALUES (?, ?, ?, ?)",
                     (strategy_id, action, json.dumps(before, sort_keys=True) if before is not None else None,
                      json.dumps(after, sort_keys=True) if after is not None else None))
        conn.commit()


def settings_history(conn: sqlite3.Connection, strategy_id: str, limit: int = 50) -> list[dict]:
    """Changements de réglages, du plus récent au plus ancien : `{changed_at, action, changes: {réglage: (avant, après)}}`."""
    try:
        rows = conn.execute("SELECT changed_at, action, before_json, after_json FROM fund_settings_log WHERE strategy_id = ? "
                            "ORDER BY changed_at DESC, log_id DESC LIMIT ?", (strategy_id, limit)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for changed_at, action, before_json, after_json in rows:
        before, after = json.loads(before_json or "{}") or {}, json.loads(after_json or "{}") or {}
        keys = sorted(set(before) | set(after))
        out.append({"changed_at": changed_at, "action": action,
                    "changes": {k: (before.get(k), after.get(k)) for k in keys if before.get(k) != after.get(k)}})
    return out


def overlay(conn: sqlite3.Connection, strategy_id: str, raw: dict | None) -> dict:
    """Les réglages `raw` posés sur ceux déjà enregistrés de la stratégie : ce qu'un formulaire ne montre pas (le périmètre :
    groupes et horizons d'une stratégie par classe d'actifs) est conservé, au lieu de revenir à « tout l'univers »."""
    if raw is not None and not isinstance(raw, dict):
        return raw                                                # `Settings.from_dict` refuse ce qui n'est pas un objet
    stored = (store.get_autopilot(conn, strategy_id) or {}).get("settings") or {}
    return {**stored, **(raw or {})}


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
    """`(instrument, allow_short, code du motif d'exclusion)`. Comptant (action ou ETF, achat seulement) quand c'est possible et
    que la vente à découvert n'est pas demandée, sinon CFD ; en PEA, seulement des actions de l'UE/EEE en euro, au comptant et à l'achat
    (`envelopes.pea_eligibility` rend le motif de chaque exclusion)."""
    sym = symbol.upper()
    cash_ok = instruments.classify_cfd_underlying(sym) == "equity" and not sym.endswith(".NYB")
    kind = "etf" if "ETF" in groups.get(symbol, "") else "equity"
    if wrapper == "PEA":
        why = envelopes.pea_eligibility(symbol, groups)
        if why is not None:
            return None, False, why
        return {"kind": kind, "symbol": sym, "spec": {}}, False, None
    if cash_ok and not settings.allow_short:
        return {"kind": kind, "symbol": sym, "spec": {}}, False, None
    return {"kind": "cfd", "symbol": sym, "spec": {}}, settings.allow_short, None


def _volatility(conn: sqlite3.Connection, symbol: str, today: dt.date, model: str = "trailing") -> float | None:
    """σ des rendements des `VOL_WINDOW` dernières séances connues à `today` (jamais le futur), ou None sans cotation. `model="har"` : la
    volatilité PRÉVUE pour le lendemain par un HAR-RV (`fund/vol_forecast.py`), repli sur la glissante si l'historique ne suffit pas."""
    df = prices.ensure_bars(conn, symbol).df
    if df is None or df.empty:
        return None
    if model == "har":
        from patrick.fund import vol_forecast
        forecast = vol_forecast.har_sigma(df, pd.Timestamp(today))
        if forecast and math.isfinite(forecast["sigma"]) and forecast["sigma"] > 0:
            return forecast["sigma"]
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


def _returns_matrix(conn: sqlite3.Connection, targets: list[str], today: dt.date) -> pd.DataFrame:
    """Rendements quotidiens des cibles jusqu'à `today` (jamais après), `RISK_PARITY_WINDOW` dernières séances."""
    cols = {}
    for target in targets:
        df = prices.ensure_bars(conn, target).df
        if df is None or df.empty:
            continue
        close = df["close"].dropna()
        cols[target] = close[close.index <= pd.Timestamp(today)].pct_change()
    return pd.DataFrame(cols).iloc[-RISK_PARITY_WINDOW:]


def _weights(priced: list[dict], settings: Settings, returns: pd.DataFrame | None = None) -> dict[int, float]:
    """Poids de chaque modèle (clé : `id(modèle)`) : volatilité inverse de sa cible (ou, `weighting="risk_parity"`, contributions au risque
    égales entre cibles, corrélations comprises : `fund/risk_parity.py`), partagée entre les horizons de la cible, puis plafond par
    classe d'actifs : le poids d'une classe au-dessus de `max_class_share` est ramené au plafond, sans être redistribué (l'exposition brute baisse
    d'autant : c'est le sens d'un plafond de risque)."""
    targets = sorted({m["target"] for m in priced})
    inverse = {target: 1.0 / next(m["vol"] for m in priced if m["target"] == target) for target in targets}
    if settings.weighting == "risk_parity" and returns is not None and len(targets) > 1 and set(targets) <= set(returns.columns):
        from patrick.fund import risk_parity
        cov = risk_parity.shrunk_cov(returns[targets])
        if cov is not None:
            inverse = dict(zip(targets, risk_parity.erc_weights(cov), strict=True))
    total, per_target = sum(inverse.values()), {t: sum(1 for m in priced if m["target"] == t) for t in inverse}
    weights = {id(m): inverse[m["target"]] / total / per_target[m["target"]] for m in priced}
    classes = {id(m): classify_asset_class(m["target"]) for m in priced}
    by_class: dict[str, float] = {}
    for m in priced:
        by_class[classes[id(m)]] = by_class.get(classes[id(m)], 0.0) + weights[id(m)]
    scale = {c: min(1.0, settings.max_class_share / w) if w > 0 else 1.0 for c, w in by_class.items()}
    return {id(m): weights[id(m)] * scale[classes[id(m)]] for m in priced}


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
            _reject(excluded, model, why)
            continue
        vol = _volatility(conn, model["target"], today, settings.vol_model)
        unit = _unit_notional(conn, strategy["strategy_id"], instrument["symbol"], today) if instrument["kind"] == "cfd" else None
        if vol is None or (instrument["kind"] == "cfd" and unit is None):
            _reject(excluded, model, "no_quotes")
            continue
        priced.append({**model, "instrument": instrument, "allow_short": allow_short, "vol": vol, "unit_notional": unit})
    returns = (_returns_matrix(conn, sorted({m["target"] for m in priced}), today)
               if settings.weighting == "risk_parity" and len({m["target"] for m in priced}) > 1 else None)
    weights = _weights(priced, settings, returns)
    if settings.min_position is not None and priced:
        # Taille minimale d'une position (frais forfaitaires par ordre : un fonds de quelques milliers d'euros ne peut pas suivre tous les signaux).
        # D'abord le plafond arithmétique (budget / minimum), puis, les poids n'étant pas égaux, on retire le modèle le moins bien classé
        # tant qu'une position reste sous le minimum. L'ordre de `priced` est celui de la sélection : preuves d'abord, p de Diebold-Mariano croissante.
        budget = settings.gross * capital
        keep = max(1, int(budget // settings.min_position))
        for model in priced[keep:]:
            _reject(excluded, model, "min_size", f"{keep} position(s) au plus de {settings.min_position:g} € au moins avec {budget:,.0f} €".replace(",", " "))
        priced = priced[:keep]
        weights = _weights(priced, settings, returns)
        while len(priced) > 1 and any(budget * w < settings.min_position for w in weights.values()):
            _reject(excluded, priced.pop(), "min_size", f"poids trop faible pour atteindre {settings.min_position:g} € (budget {budget:,.0f} €)".replace(",", " "))
            weights = _weights(priced, settings, returns)
    selected = []
    for model in priced:
        weight = weights[id(model)]
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
    combo_summary = None
    if settings.combo and selected:
        # Fonds combiné : chaque règle reçoit les sources disponibles pour sa cible (agent RL crédible, modèle de l'indice de volatilité de sa
        # classe), le coût de son aller-retour et les statistiques de son signal (`fund/combo.py`).
        ctx = combo_mod.plan_context(conn, settings.combo)
        for model in selected:
            model["combo"] = combo_mod.rule_signal(conn, model, strategy, settings.combo, ctx)
        combo_summary = {"rl": sum(1 for m in selected if m["combo"]["rl"]), "regime": sum(1 for m in selected if m["combo"]["regime"]),
                         "n": len(selected)}
    counts: dict[str, int] = {}
    for cell in excluded:
        counts[cell["code"]] = counts.get(cell["code"], 0) + 1
    return {"settings": settings.to_dict(), "n_cells": chosen["n_cells"], "capital": capital, "gross": settings.gross,
            "selected": selected, "excluded": excluded, "combo": combo_summary,
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
            "last_run": stored.get("last_run"), "history": settings_history(conn, strategy_id, limit=12),
            "rules": [r for r in rules if (r["config"].get("managed") or {}).get("by") == MANAGER]}


# --------------------------------------------------------------------------- cycle

def _rule_config(model: dict, settings: Settings, since: str) -> dict:
    signal = model.get("combo") or {"mode": "direction", "min_confidence": settings.min_confidence}
    return {"trial_id": model["trial_id"], "segment": "live", "allow_short": model["allow_short"],
            "signal": signal,
            "hold": {"mode": "horizon", "sessions": model["horizon"]},
            "instrument": model["instrument"], "sizing": model["sizing"], "since": since,
            "managed": {"by": MANAGER, "target": model["target"], "horizon": model["horizon"]}}


def _signature(cfg: dict) -> tuple:
    """Ce qui fait le comportement d'une règle : si cela change, on ne la réécrit pas, on en commence une autre."""
    instrument, signal = cfg["instrument"], cfg["signal"]
    sources = None
    if signal.get("mode") == "combo":                    # un agent RL, un modèle de régime ou un multiple de coût différents changent les décisions
        sources = ((signal.get("rl") or {}).get("job_id"), bool(signal.get("vol")), (signal.get("regime") or {}).get("trial_id"),
                   signal.get("cost_multiple"))
    return (cfg["trial_id"], instrument["kind"], instrument["symbol"].upper(), bool(cfg["allow_short"]),
            signal.get("min_confidence", 0.0), cfg["hold"].get("sessions"), signal.get("mode"), sources)


def managed_rules(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    """Règles du pilote (actives et retirées), les plus anciennes d'abord."""
    return [r for r in systematic.list_rules(conn, strategy_id) if (r["config"].get("managed") or {}).get("by") == MANAGER]


def duplicate_rules(conn: sqlite3.Connection, strategy_id: str) -> list[tuple[dict, dict]]:
    """`[(règle gardée, règle en trop)]` : règles actives du pilote sur une même cellule (cible, horizon). La plus ancienne est gardée.
    Deux cycles simultanés en ont créé 74 la nuit du 16/11/2026, avant le verrou entre processus (24/11) : le cycle range les règles
    actives par cellule et n'en voyait qu'une, mais les appliquait toutes -- chaque exemplaire ouvrait sa propre position."""
    kept: dict[tuple, dict] = {}
    out: list[tuple[dict, dict]] = []
    for rule in managed_rules(conn, strategy_id):                   # les plus anciennes d'abord
        if "retired_on" in rule["config"]:
            continue
        key = (rule["config"]["managed"]["target"], rule["config"]["managed"]["horizon"])
        if key in kept:
            out.append((kept[key], rule))
        else:
            kept[key] = rule
    return out


def drop_duplicate_rules(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    """Supprime chaque règle en trop (`duplicate_rules`) avec ses ordres : ses positions doublaient celles de la règle gardée (même
    modèle, mêmes signaux), leur P&L était compté deux fois. Renvoie une ligne par règle supprimée."""
    out: list[dict] = []
    for keep, extra in duplicate_rules(conn, strategy_id):
        meta = extra["config"]["managed"]
        orders = systematic.purge_rule(conn, extra["rule_id"])
        logger.info("règle du pilote en double supprimée : %s (%s h%s, gardée : %s), %d ordre(s)", extra["rule_id"], meta["target"],
                    meta["horizon"], keep["rule_id"], orders)
        out.append({"rule_id": extra["rule_id"], "kept": keep["rule_id"], "target": meta["target"], "horizon": meta["horizon"],
                    "trial_id": extra["config"]["trial_id"], "orders": orders})
    return out


def repair(conn: sqlite3.Connection, strategy_id: str, today: dt.date | None = None, *, apply: bool = False,
           lock_timeout_s: float | None = None) -> dict:
    """Répare un fonds piloté sans attendre le cycle de la nuit : règles en double (`duplicate_rules`) et positions orphelines des règles
    retirées sans plan (`systematic.orphan_closes`). `apply=False` : aperçu, rien n'est écrit. Rend `{strategy_id, name, duplicates:
    [{rule_id, kept, target, horizon, orders, pnl}], orphans: [{rule_id, target, horizon, position_id, opened, close_on}],
    closed, pending, refused}`. Sous le verrou du cycle (jamais en même temps qu'un cycle)."""
    today = service._today(today)
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        raise store.FundError("stratégie introuvable")
    with _RUN_LOCK, _cycle_lock(conn, CYCLE_LOCK_TIMEOUT_S if lock_timeout_s is None else lock_timeout_s):
        pairs = duplicate_rules(conn, strategy_id)
        pnl_by_rule: dict[str, float] = {}
        if pairs:
            try:                                                   # une seule valorisation du fonds pour toutes les règles en trop
                snapshot = service.strategy_snapshot(conn, strategy, today)
                owner = insight._position_rules(snapshot["orders"])
                for p in snapshot["positions"]:
                    rule_id = owner.get(p["position_id"])
                    if rule_id:
                        pnl_by_rule[rule_id] = pnl_by_rule.get(rule_id, 0.0) + float(p["pnl"] or 0.0)
            except Exception as exc:  # noqa: BLE001 -- cotations indisponibles : l'aperçu dit les ordres sans montant
                logger.info("valorisation impossible pour l'aperçu de la réparation : %s: %s", type(exc).__name__, exc)
        duplicates = []
        for keep, extra in pairs:
            meta = extra["config"]["managed"]
            prefix = f"{systematic.NOTE_PREFIX}:{extra['rule_id']}:"
            n_orders = conn.execute("SELECT COUNT(*) FROM fund_order WHERE strategy_id = ? AND substr(note, 1, ?) = ?",
                                    (strategy_id, len(prefix), prefix)).fetchone()[0]
            duplicates.append({"rule_id": extra["rule_id"], "kept": keep["rule_id"], "target": meta["target"], "horizon": meta["horizon"],
                               "orders": int(n_orders), "pnl": pnl_by_rule.get(extra["rule_id"])})
        if apply:
            for item in duplicates:
                item["orders"] = systematic.purge_rule(conn, item["rule_id"])
        orphans, closed, pending, refused = [], 0, 0, []
        for rule in managed_rules(conn, strategy_id):
            if "retired_on" not in rule["config"]:
                continue
            try:
                systematic.plan(conn, rule)
                continue                                           # le plan se calcule : le cycle ferme ses positions lui-même
            except store.FundError:
                pass
            meta = rule["config"]["managed"]
            for item in systematic.orphan_closes(conn, rule):
                orphans.append({"rule_id": rule["rule_id"], "target": meta["target"], "horizon": meta["horizon"],
                                "position_id": item["request"]["position_id"], "close_on": item["requested"]})
            if apply:
                result = systematic.apply(conn, rule["rule_id"], today)
                closed += len(result["placed"])
                pending += len(result["pending"])
                refused += [{"target": meta["target"], "horizon": meta["horizon"], **r} for r in result["refused"]]
    return {"strategy_id": strategy_id, "name": strategy["name"], "duplicates": duplicates, "orphans": orphans, "applied": apply,
            "closed": closed, "pending": pending, "refused": refused}


def _purge_previous_models(conn: sqlite3.Connection, strategy_id: str, key: tuple, trial_id: int,
                           today: dt.date | None = None) -> list[dict]:
    """Un nouveau modèle prend la cellule `key` (cible, horizon) : les règles du pilote qui y rejouaient un AUTRE modèle (active
    ou déjà retirées) sont supprimées avec leurs ordres. Le P&L du modèle remplacé sort du fonds ; celui des autres cellules, des
    règles saisies à la main et des ordres manuels reste. Renvoie une ligne par règle supprimée."""
    out: list[dict] = []
    for rule in managed_rules(conn, strategy_id):
        cfg = rule["config"]
        if (cfg["managed"]["target"], cfg["managed"]["horizon"]) != key or cfg["trial_id"] == trial_id:
            continue
        orders, pnl = systematic.replace_model(conn, rule, trial_id, today)
        logger.info("pilote %s : %s h%s passe de l'essai %s à l'essai %s, %d ordre(s) de l'ancien modèle supprimé(s)",
                    strategy_id, key[0], key[1], cfg["trial_id"], trial_id, orders)
        out.append({"rule_id": rule["rule_id"], "target": key[0], "horizon": key[1], "trial_id": cfg["trial_id"],
                    "new_trial_id": trial_id, "orders": orders, "pnl_removed": pnl})
    return out


_RUN_LOCK = threading.Lock()        # un seul cycle à la fois dans ce processus : deux cycles simultanés doubleraient les ordres
# Et un seul entre processus : l'application, la nuit (`daily_predict.py`) et la CLI tournent chacune dans le leur. Le verrou est un
# fichier à côté de la base (libéré par le système si le processus meurt). Un cycle attend celui d'un autre processus (idempotent,
# il retrouve alors les règles déjà posées) au plus `CYCLE_LOCK_TIMEOUT_S`, puis renonce avec `CycleBusy`.
CYCLE_LOCK_TIMEOUT_S = 3600.0


class CycleBusy(store.FundError):
    """Un autre processus tient le cycle du pilote au-delà du délai d'attente."""


@contextlib.contextmanager
def _cycle_lock(conn: sqlite3.Connection, timeout_s: float):
    db = interprocess_lock.sqlite_file(conn)
    if db is None:                                   # base en mémoire (tests) : propre à ce processus
        yield
        return
    try:
        with interprocess_lock.file_lock(db + ".autopilot.lock", timeout_s=timeout_s):
            yield
    except interprocess_lock.LockTimeout as exc:
        raise CycleBusy(f"un autre processus fait déjà le cycle des fonds ({exc})") from exc


def run(conn: sqlite3.Connection, strategy_id: str, today: dt.date | None = None, *,
        lock_timeout_s: float = CYCLE_LOCK_TIMEOUT_S) -> dict:
    """Un cycle : sélectionner, ajuster les règles du pilote, appliquer chacune. Idempotent. Rend le compte rendu et
    l'enregistre (`last_run`) avec les réglages. Un seul cycle à la fois, dans ce processus comme entre processus."""
    with _RUN_LOCK, _cycle_lock(conn, lock_timeout_s):
        return _run(conn, strategy_id, today)


def start_cycles(strategy_ids: list[str], db_path: str | None = None) -> threading.Thread:
    """Lance en arrière-plan un cycle pour chacune de ces stratégies, l'une après l'autre (la sélection et les cotations de plusieurs
    centaines de modèles prennent des minutes : la page ne les attend pas). Le compte rendu de chacune est dans son `last_run`."""
    def work() -> None:
        conn = trackdb.connect(db_path)
        try:
            for strategy_id in strategy_ids:
                try:
                    run(conn, strategy_id)
                except Exception:                             # une stratégie en échec n'arrête pas les suivantes
                    logger.exception("autopilot cycle failed for %s", strategy_id)
        finally:
            conn.close()
    thread = threading.Thread(target=work, name="autopilot-cycles", daemon=True)
    thread.start()
    return thread


def _run(conn: sqlite3.Connection, strategy_id: str, today: dt.date | None) -> dict:
    today = service._today(today)
    strategy, stored, settings = _enabled(conn, strategy_id)
    plan = build_plan(conn, strategy, settings, today)
    desired = {(m["target"], m["horizon"]): m for m in plan["selected"]}
    # Arrêt sur perte : au-delà du repli maximal, plus aucun modèle n'est retenu. Les règles sont retirées (leurs positions se ferment à
    # l'échéance), rien n'est effacé ; le pilote reste à l'arrêt tant que le repli dépasse le plafond (le relever ou le vider pour repartir).
    halted = None
    if settings.max_drawdown is not None:
        drawdown = insight.current_drawdown(conn, strategy, today)
        if drawdown is not None and drawdown >= settings.max_drawdown:
            halted = {"drawdown": round(drawdown, 4), "limit": settings.max_drawdown}
            desired = {}
    report: dict = {"day": today.isoformat(), "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                    "selected": len(desired), "created": [], "updated": [], "retired": [], "replaced": [], "failed": [],
                    "refused": [],
                    "placed": 0, "pending": 0}

    report["deduplicated"] = drop_duplicate_rules(conn, strategy_id)
    report["orphans_closed"] = 0
    active: dict[tuple, dict] = {}
    for rule in managed_rules(conn, strategy_id):
        if "retired_on" not in rule["config"]:
            active[(rule["config"]["managed"]["target"], rule["config"]["managed"]["horizon"])] = rule
    yesterday, since = (today - dt.timedelta(days=1)).isoformat(), today.isoformat()
    outgoing: dict[tuple, dict] = {}                 # cellule gardée dont le modèle change : l'ancienne règle attend la neuve
    for key, rule in list(active.items()):
        want = desired.get(key)
        if want is not None and rule["config"]["trial_id"] != want["trial_id"]:
            outgoing[key] = rule
            del active[key]
        elif want is None or _signature(rule["config"]) != _signature(_rule_config(want, settings, since)):
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
            if key in outgoing:                      # le nouveau modèle est refusé : l'ancien s'arrête sans rien effacer
                systematic.retire_rule(conn, outgoing[key]["rule_id"], yesterday)
                report["retired"].append(outgoing[key]["rule_id"])
        else:
            report["created"].append(rule_id)
            active[key] = {"rule_id": rule_id}
            report["replaced"] += _purge_previous_models(conn, strategy_id, key, model["trial_id"], today)
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
        if result.get("orphan"):                                   # retirée sans plan : fermetures de repli (`systematic.orphan_closes`)
            report["orphans_closed"] += len(result["placed"])
        report["refused"] += [{"target": meta["target"], "horizon": meta["horizon"], **r} for r in result["refused"]]
    report["excluded"] = plan["excluded_summary"]
    report["halted"] = halted

    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k != "excluded"}
    store.set_autopilot(conn, strategy_id, {**stored, "last_run": summary})
    return report


def run_all(conn: sqlite3.Connection, today: dt.date | None = None, needs_rl: bool | None = None) -> list[dict]:
    """Un cycle pour chaque stratégie active dont le pilote est activé. Une erreur n'arrête pas les autres. `needs_rl` : True = seulement les fonds
    combinés qui lisent un agent RL (à lancer après `rl.live.refresh`), False = tous les autres, None = tous."""
    out: list[dict] = []
    if needs_rl is not True:                       # A12 : les ordres limite en attente d'abord (une fois par nuit), puis les cycles
        try:
            from patrick.fund import limit_orders
            for moved in limit_orders.resolve(conn, today=today):
                logger.info("ordre limite %s (%s) : %s, %g exécuté(s)", moved["limit_id"], moved["symbol"], moved["status"],
                            moved["filled_quantity"])
        except Exception:                          # un ordre limite en échec n'empêche jamais les cycles des fonds
            logger.exception("résolution des ordres limite en échec")
    for strategy in store.list_strategies(conn):
        stored = store.get_autopilot(conn, strategy["strategy_id"])
        if not stored or not stored.get("enabled"):
            continue
        if needs_rl is not None and combo_mod.needs_rl(stored) != needs_rl:
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
        if stored.get("enabled"):
            _log_settings(conn, strategy_id, "disable", stored.get("settings"), None)
    return {"removed_rules": removed}
