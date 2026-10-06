"""Fonds, chantier 3 : mode systématique « modèle ML avec seuils saisis ».

Une règle (`fund_rule`) lie une stratégie à un essai de modèle et à un
instrument. Les signaux du modèle (`prediction`) deviennent des ordres du
fonds par une machine à états à seuils d'entrée/sortie (hystérésis); les
ordres passent par `service.place_order`, donc par les mêmes règles
d'enveloppe, frais et valorisation que les ordres manuels. Spécification :
`docs/superpowers/specs/2026-10-06-fonds-mode-ml-seuils-design.md`.

Garanties :
- retard : un signal du jour *t* est exécuté à la première séance du titre
  négocié à partir de *t + 1 jour* (jamais le jour du signal);
- idempotence : chaque ordre généré porte la note `auto:<règle>:<date>:<action>`
  et un identifiant de position déterministe; `apply` ignore ce qui existe déjà;
- honnêteté statistique : créer une règle compte les seuils comme une
  configuration essayée (`simulate.engine.save_simulation`, F03).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3

import pandas as pd

from patrick.config import defaults as D
from patrick.fund import service, store
from patrick.simulate import engine as sim_engine

EQUITY_KINDS = ("equity", "etf")
NOTE_PREFIX = "auto"


# --------------------------------------------------------------------------- configuration

def _float(value, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise store.FundError(f"{name} invalide : nombre attendu ({value!r})") from exc
    if not math.isfinite(out):
        raise store.FundError(f"{name} invalide : nombre fini attendu")
    return out


def validate_config(config: dict) -> dict:
    """Configuration normalisée d'une règle, ou `FundError` motivée."""
    if not isinstance(config, dict):
        raise store.FundError("configuration invalide : objet attendu")
    trial_id = config.get("trial_id")
    if isinstance(trial_id, bool) or not isinstance(trial_id, int) or trial_id < 1:
        raise store.FundError("trial_id invalide : entier >= 1 attendu")
    segment = config.get("segment") or "holdout"
    if segment not in sim_engine.SEGMENTS:
        raise store.FundError(f"segment inconnu : {segment!r} ({', '.join(sim_engine.SEGMENTS)})")
    enter = _float(config.get("enter"), "enter")
    if not 0.5 < enter < 1.0:
        raise store.FundError("enter doit être strictement entre 0,5 et 1")
    exit_ = _float(config.get("exit", 0.5), "exit")
    if not 0.5 <= exit_ <= enter:
        raise store.FundError("exit doit être entre 0,5 et enter")
    allow_short = bool(config.get("allow_short", False))

    instrument = config.get("instrument")
    if not isinstance(instrument, dict) or instrument.get("kind") not in store.INSTRUMENT_KINDS:
        raise store.FundError(f"instrument : type inconnu (attendu : {', '.join(store.INSTRUMENT_KINDS)})")
    kind = instrument["kind"]
    spec = instrument.get("spec") or {}
    if not isinstance(spec, dict):
        raise store.FundError("instrument : spec invalide (objet attendu)")
    symbol = str(instrument.get("symbol") or "").strip().upper()
    if kind == "future":
        if not spec.get("root"):
            raise store.FundError("future : racine requise dans spec (voir le catalogue)")
        year, month = spec.get("year"), spec.get("month")
        if (isinstance(year, bool) or not isinstance(year, int) or isinstance(month, bool)
                or not isinstance(month, int) or not 1 <= month <= 12):
            raise store.FundError("future : année et mois (1 à 12) du contrat requis dans spec")
    elif not symbol:
        raise store.FundError("symbole manquant")
    if allow_short and kind in EQUITY_KINDS:
        raise store.FundError("vente à découvert impossible sur action/ETF (compte comptant) : "
                              "utiliser un CFD ou un future")

    sizing = config.get("sizing") or {}
    if kind in EQUITY_KINDS:
        amount = sizing.get("amount")
        if amount is None or _float(amount, "montant") <= 0:
            raise store.FundError("montant requis (action/ETF) : sizing.amount > 0")
        norm_sizing = {"amount": _float(amount, "montant")}
    else:
        quantity = sizing.get("quantity")
        if quantity is None or _float(quantity, "quantité") < 1 or _float(quantity, "quantité") != int(quantity):
            raise store.FundError("quantité entière >= 1 requise (CFD/future) : sizing.quantity")
        norm_sizing = {"quantity": int(quantity)}

    return {"trial_id": trial_id, "segment": segment, "enter": enter, "exit": exit_, "allow_short": allow_short,
            "instrument": {"kind": kind, "symbol": symbol, "spec": spec}, "sizing": norm_sizing}


# --------------------------------------------------------------------------- signaux

def decide(scores: pd.Series, enter: float, exit_: float, allow_short: bool) -> list[dict]:
    """Machine à états à plat / long / short sur une série de scores haussiers
    indexée par date. Un score manquant ne change rien."""
    state: str | None = None
    out: list[dict] = []
    for ts, score in scores.sort_index().items():
        if score is None or math.isnan(score):
            continue
        if state == "long" and score < exit_:
            out.append({"ts": ts, "action": "close", "side": "long", "score": float(score)})
            state = None
        elif state == "short" and score > 1 - exit_:
            out.append({"ts": ts, "action": "close", "side": "short", "score": float(score)})
            state = None
        if state is None:
            if score >= enter:
                state = "long"
            elif allow_short and score <= 1 - enter:
                state = "short"
            if state:
                out.append({"ts": ts, "action": "open", "side": state, "score": float(score)})
    return out


def load_scores(conn: sqlite3.Connection, config: dict) -> pd.Series:
    df = sim_engine._load_predictions(conn, config["trial_id"], config["segment"])
    if df.empty:
        raise store.FundError(f"aucun signal du segment {config['segment']!r} pour l'essai {config['trial_id']}")
    if df["ts"].duplicated().any():
        raise store.FundError("signaux dupliqués (essai CPCV) : choisir un essai walk-forward")
    score = sim_engine._directional_score(df["y_pred"].to_numpy(), df["y_proba"].to_numpy())
    return pd.Series(score, index=pd.DatetimeIndex(df["ts"])).sort_index()


# --------------------------------------------------------------------------- règles

def _row(raw: tuple) -> dict:
    return {"rule_id": raw[0], "strategy_id": raw[1], "name": raw[2], "config": json.loads(raw[3]),
            "created_at": raw[4]}


def get_rule(conn: sqlite3.Connection, rule_id: str) -> dict | None:
    raw = conn.execute("SELECT rule_id, strategy_id, name, config_json, created_at FROM fund_rule "
                       "WHERE rule_id = ?", (rule_id,)).fetchone()
    return _row(raw) if raw else None


def list_rules(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    rows = conn.execute("SELECT rule_id, strategy_id, name, config_json, created_at FROM fund_rule "
                        "WHERE strategy_id = ? ORDER BY created_at, rule_id", (strategy_id,)).fetchall()
    return [_row(r) for r in rows]


def create_rule(conn: sqlite3.Connection, strategy_id: str, name: str, config: dict) -> str:
    if store.get_strategy(conn, strategy_id) is None:
        raise store.FundError("stratégie introuvable")
    name = (name or "").strip()
    if not name:
        raise store.FundError("nom de règle manquant")
    cfg = validate_config(config)
    if conn.execute("SELECT 1 FROM trial WHERE trial_id = ?", (cfg["trial_id"],)).fetchone() is None:
        raise store.FundError(f"essai {cfg['trial_id']} introuvable")
    if sim_engine.available_segments(conn, cfg["trial_id"]).get(cfg["segment"], 0) < 1:
        raise store.FundError(f"aucun signal du segment {cfg['segment']!r} pour l'essai {cfg['trial_id']}")
    rule_id = store.new_id("rule")
    with conn:
        conn.execute("INSERT INTO fund_rule (rule_id, strategy_id, name, config_json) VALUES (?, ?, ?, ?)",
                     (rule_id, strategy_id, name[:120], json.dumps(cfg)))
    # Les seuils saisis sont une configuration de plus essayée sur cette cible (F03).
    sim_engine.save_simulation(
        conn, cfg["trial_id"],
        sim_engine.SimParams(position_mode="threshold", threshold=cfg["enter"], short_allowed=cfg["allow_short"]),
        {"ok": True, "kind": "fund_rule", "rule_id": rule_id, "enter": cfg["enter"], "exit": cfg["exit"]})
    return rule_id


def delete_rule(conn: sqlite3.Connection, rule_id: str) -> bool:
    """Supprime la règle (jamais les ordres déjà passés, qui restent des ordres du fonds). False si inconnue."""
    with conn:
        cur = conn.execute("DELETE FROM fund_rule WHERE rule_id = ?", (rule_id,))
    return cur.rowcount > 0


def rule_summaries(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    """Règles d'une stratégie avec le modèle visé et le nombre d'ordres déjà générés."""
    notes = [o["note"] for o in store.list_orders(conn, strategy_id) if o.get("note")]
    out = []
    for rule in list_rules(conn, strategy_id):
        prefix = f"{NOTE_PREFIX}:{rule['rule_id']}:"
        model = conn.execute(
            "SELECT run.target, run.horizon, trial.algo FROM trial JOIN run ON run.run_id = trial.run_id "
            "WHERE trial.trial_id = ?", (rule["config"]["trial_id"],)).fetchone()
        out.append({**rule, "n_orders": sum(1 for n in notes if n.startswith(prefix)),
                    "model": dict(zip(("target", "horizon", "algo"), model)) if model else None})
    return out


def available_models(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Essais gagnants dont on peut rejouer les signaux : un run terminé, jamais un horizon descriptif (pas un
    signal de portefeuille), au moins un signal dans un segment. Les modèles en titre d'abord, puis les plus récents."""
    descriptive = sorted(D.DESCRIPTIVE_HORIZONS)
    rows = conn.execute(
        "SELECT trial.trial_id, trial.run_id, trial.algo, run.target, run.horizon, run.started_at, "
        "       (champion.trial_id IS NOT NULL) "
        "FROM trial JOIN run ON run.run_id = trial.run_id "
        "LEFT JOIN champion ON champion.trial_id = trial.trial_id "
        f"WHERE trial.is_best = 1 AND run.status = 'done' AND run.horizon NOT IN ({','.join('?' for _ in descriptive)}) "
        "ORDER BY 7 DESC, run.started_at DESC, trial.trial_id DESC LIMIT ?", (*descriptive, limit)).fetchall()
    out = []
    for trial_id, run_id, algo, target, horizon, started_at, is_champion in rows:
        segments = sim_engine.available_segments(conn, trial_id)
        if segments:
            out.append({"trial_id": trial_id, "run_id": run_id, "algo": algo, "target": target, "horizon": horizon,
                        "started_at": started_at, "champion": bool(is_champion), "segments": segments})
    return out


# --------------------------------------------------------------------------- plan et exécution

def _position_id(rule_id: str, signal_day: str, side: str) -> str:
    digest = hashlib.sha1(f"{rule_id}:{signal_day}:{side}".encode()).hexdigest()
    return f"pos_{digest[:10]}"


def plan(conn: sqlite3.Connection, rule: dict) -> list[dict]:
    """Tous les ordres que la règle implique sur l'historique de signaux, dans l'ordre chronologique."""
    cfg, rule_id = rule["config"], rule["rule_id"]
    inst, sizing = cfg["instrument"], cfg["sizing"]
    open_pid: str | None = None
    out: list[dict] = []
    for sig in decide(load_scores(conn, cfg), cfg["enter"], cfg["exit"], cfg["allow_short"]):
        signal_day = sig["ts"].date().isoformat()
        requested = (sig["ts"] + pd.Timedelta(days=1)).date().isoformat()
        note = f"{NOTE_PREFIX}:{rule_id}:{signal_day}:{sig['action']}"
        if sig["action"] == "open":
            open_pid = _position_id(rule_id, signal_day, sig["side"])
            request = {"strategy_id": rule["strategy_id"], "action": "open", "instrument_kind": inst["kind"],
                       "side": sig["side"], "date": requested, "position_id": open_pid, "note": note}
            if inst["kind"] != "future":
                request["symbol"] = inst["symbol"]
            if inst["spec"]:
                request["spec"] = dict(inst["spec"])
            request.update(sizing)
        else:
            request = {"strategy_id": rule["strategy_id"], "action": "close", "position_id": open_pid,
                       "date": requested, "note": note}
        out.append({"signal": signal_day, "action": sig["action"], "side": sig["side"], "score": sig["score"],
                    "requested": requested, "note": note, "request": request})
    return out


def apply(conn: sqlite3.Connection, rule_id: str, today: dt.date | None = None) -> dict:
    """Place les ordres de la règle qui n'existent pas encore.

    `placed` : ordres passés; `refused` : refusés par les règles (avec motifs);
    `skipped` : fermetures d'une position jamais ouverte; `pending` : exécution
    dans le futur; `already` : déjà présents; `drift` : ordres automatiques
    existants qui ne sont plus dans le plan (jamais supprimés)."""
    rule = get_rule(conn, rule_id)
    if rule is None:
        raise store.FundError("règle introuvable")
    today = service._today(today)
    planned = plan(conn, rule)
    prefix = f"{NOTE_PREFIX}:{rule_id}:"
    existing = {o["note"] for o in store.list_orders(conn, rule["strategy_id"])
                if o.get("note") and o["note"].startswith(prefix)}
    result: dict = {"placed": [], "refused": [], "skipped": [], "pending": [], "already": 0,
                    "drift": sorted(existing - {p["note"] for p in planned}),
                    "segment_warning": sim_engine.SEGMENT_WARNINGS.get(rule["config"]["segment"])}
    unopened: set[str] = set()
    for item in planned:
        brief = {k: item[k] for k in ("signal", "action", "side", "requested")}
        if item["note"] in existing:
            result["already"] += 1
            continue
        if item["requested"] > today.isoformat():
            result["pending"].append(brief)
            continue
        req = item["request"]
        if item["action"] == "close" and req["position_id"] in unopened:
            result["skipped"].append({**brief, "reason": "ouverture refusée : rien à fermer"})
            continue
        try:
            placed = service.place_order(conn, req, today)
        except service.FundRuleError as exc:
            result["refused"].append({**brief, "reasons": list(exc.blocking)})
        except store.FundError as exc:
            result["refused"].append({**brief, "reasons": [str(exc)]})
        else:
            result["placed"].append({**brief, "order_id": placed["order_id"]})
            continue
        if item["action"] == "open":
            unopened.add(req["position_id"])
    return result
