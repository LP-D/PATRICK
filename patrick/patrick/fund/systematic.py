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
from patrick.config.schema import RunConfig
from patrick.config.target_label import split_run_label
from patrick.features import alpha_target
from patrick.fund import prices, service, store
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
        _check_future_spec(spec)
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

    out = {"trial_id": trial_id, "segment": segment, "enter": enter, "exit": exit_, "allow_short": allow_short,
           "instrument": {"kind": kind, "symbol": symbol, "spec": spec}, "sizing": norm_sizing}
    if config.get("hedge") is not None:
        out["hedge"] = _validate_hedge(config["hedge"])
    return out


def _check_future_spec(spec: dict) -> None:
    if not spec.get("root"):
        raise store.FundError("future : racine requise dans spec (voir le catalogue)")
    year, month = spec.get("year"), spec.get("month")
    if (isinstance(year, bool) or not isinstance(year, int) or isinstance(month, bool)
            or not isinstance(month, int) or not 1 <= month <= 12):
        raise store.FundError("future : année et mois (1 à 12) du contrat requis dans spec")


def _validate_hedge(hedge) -> dict:
    """Jambe de couverture d'une règle d'alpha : CFD (indice, ETF...) ou future, jamais une action (pas de vente à
    découvert au comptant). Le symbole d'un CFD vaut par défaut le benchmark du modèle (complété à la création)."""
    if not isinstance(hedge, dict) or hedge.get("kind") not in ("cfd", "future"):
        raise store.FundError("couverture : type invalide (cfd ou future : la jambe benchmark se vend à découvert)")
    spec = hedge.get("spec") or {}
    if not isinstance(spec, dict):
        raise store.FundError("couverture : spec invalide (objet attendu)")
    if hedge["kind"] == "future":
        _check_future_spec(spec)
    elif spec.get("leverage") is not None and _float(spec["leverage"], "levier") < 1:
        raise store.FundError("levier invalide : minimum 1")
    return {"kind": hedge["kind"], "symbol": str(hedge.get("symbol") or "").strip().upper(), "spec": spec}


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


def _model_of(conn: sqlite3.Connection, trial_id) -> dict | None:
    """Le modèle d'un essai : étiquette de cible, nature (`raw` | `alpha`), actif et benchmark."""
    row = conn.execute("SELECT run.target, run.config_json FROM trial JOIN run ON run.run_id = trial.run_id "
                       "WHERE trial.trial_id = ?", (trial_id,)).fetchone() if isinstance(trial_id, int) else None
    if row is None:
        return None
    asset, kind, benchmark = split_run_label(row[0])
    return {"label": row[0], "kind": kind, "asset": asset, "benchmark": benchmark, "config_json": row[1]}


def create_rule(conn: sqlite3.Connection, strategy_id: str, name: str, config: dict) -> str:
    if store.get_strategy(conn, strategy_id) is None:
        raise store.FundError("stratégie introuvable")
    name = (name or "").strip()
    if not name:
        raise store.FundError("nom de règle manquant")
    config = json.loads(json.dumps(config)) if isinstance(config, dict) else config
    model = _model_of(conn, config.get("trial_id")) if isinstance(config, dict) else None
    if model is not None and model["kind"] == "alpha" and isinstance(config.get("instrument"), dict):
        inst = config["instrument"]
        if inst.get("kind") in ("equity", "etf", "cfd") and not str(inst.get("symbol") or "").strip():
            inst["symbol"] = model["asset"]                  # l'instrument négocié est la cible du modèle
    cfg = validate_config(config)
    if model is None:
        raise store.FundError(f"essai {cfg['trial_id']} introuvable")
    if model["kind"] == "alpha":
        _check_alpha_rule(cfg, model)
    elif "hedge" in cfg:
        raise store.FundError("couverture : seulement pour un modèle d'alpha (un modèle de direction n'en a pas besoin)")
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


def _check_alpha_rule(cfg: dict, model: dict) -> None:
    """Un modèle d'alpha prédit la surperformance de l'actif sur son benchmark : on ne le trade que par une paire
    (actif d'un côté, benchmark de l'autre pour β × le montant), et sur l'actif du modèle lui-même."""
    inst = cfg["instrument"]
    if inst["kind"] != "future" and inst["symbol"] != model["asset"].upper():
        raise store.FundError(f"modèle d'alpha : l'instrument négocié doit être la cible du modèle ({model['asset']})")
    hedge = cfg.get("hedge")
    if hedge is None:
        raise store.FundError("modèle d'alpha : une couverture est requise (jambe benchmark, CFD ou future)")
    if hedge["kind"] == "cfd" and not hedge["symbol"]:
        hedge["symbol"] = model["benchmark"].upper()          # par défaut : le benchmark du modèle


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
        described = dict(zip(("target", "horizon", "algo"), model)) if model else None
        if described:
            _, described["kind"], described["benchmark"] = split_run_label(described["target"])
        out.append({**rule, "n_orders": sum(1 for n in notes if n.startswith(prefix)), "model": described})
    return out


def available_models(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Essais gagnants dont on peut rejouer les signaux : un run terminé, jamais un horizon descriptif (pas un
    signal de portefeuille), au moins un signal dans un segment. Les modèles en titre d'abord, puis les plus récents.
    Un modèle d'alpha (`kind == "alpha"`) se trade en paire couverte contre son benchmark."""
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
            asset, kind, benchmark = split_run_label(target)
            out.append({"trial_id": trial_id, "run_id": run_id, "algo": algo, "target": target, "horizon": horizon,
                        "started_at": started_at, "champion": bool(is_champion), "segments": segments,
                        "kind": kind, "asset": asset, "benchmark": benchmark})
    return out


# --------------------------------------------------------------------------- plan et exécution

def _position_id(rule_id: str, signal_day: str, side: str) -> str:
    digest = hashlib.sha1(f"{rule_id}:{signal_day}:{side}".encode()).hexdigest()
    return f"pos_{digest[:10]}"


def plan(conn: sqlite3.Connection, rule: dict) -> list[dict]:
    """Tous les ordres que la règle implique sur l'historique de signaux, dans l'ordre chronologique.
    Règle d'alpha : chaque élément est une PAIRE (jambe actif dans `request`, jambe benchmark décrite par
    `hedge_position_id`, `hedge_note` et, à la fermeture, `hedge_request`)."""
    cfg, rule_id = rule["config"], rule["rule_id"]
    inst, sizing, hedged = cfg["instrument"], cfg["sizing"], "hedge" in cfg
    open_pid = open_hedge_pid = None
    out: list[dict] = []
    for sig in decide(load_scores(conn, cfg), cfg["enter"], cfg["exit"], cfg["allow_short"]):
        signal_day = sig["ts"].date().isoformat()
        requested = (sig["ts"] + pd.Timedelta(days=1)).date().isoformat()
        note = f"{NOTE_PREFIX}:{rule_id}:{signal_day}:{sig['action']}"
        extra: dict = {}
        if sig["action"] == "open":
            open_pid = _position_id(rule_id, signal_day, sig["side"])
            request = {"strategy_id": rule["strategy_id"], "action": "open", "instrument_kind": inst["kind"],
                       "side": sig["side"], "date": requested, "position_id": open_pid, "note": note}
            if inst["kind"] != "future":
                request["symbol"] = inst["symbol"]
            if inst["spec"]:
                request["spec"] = dict(inst["spec"])
            request.update(sizing)
            if hedged:
                open_hedge_pid = _position_id(rule_id, signal_day, sig["side"] + "_hedge")
                extra = {"hedge_position_id": open_hedge_pid, "hedge_note": note + "_hedge"}
        else:
            request = {"strategy_id": rule["strategy_id"], "action": "close", "position_id": open_pid,
                       "date": requested, "note": note}
            if hedged:
                extra = {"hedge_position_id": open_hedge_pid, "hedge_note": note + "_hedge",
                         "hedge_request": {"strategy_id": rule["strategy_id"], "action": "close",
                                           "position_id": open_hedge_pid, "date": requested,
                                           "note": note + "_hedge"}}
        out.append({"signal": signal_day, "action": sig["action"], "side": sig["side"], "score": sig["score"],
                    "requested": requested, "note": note, "request": request, **extra})
    return out


# --------------------------------------------------------------------------- paire couverte (modèle d'alpha)

def _beta_at(conn: sqlite3.Connection, rule: dict, signal_day: str) -> float:
    """β actif / benchmark connu à la date du signal, estimé sur les cotations du fonds (mêmes règles que la cible
    alpha : fenêtre glissante, jamais le futur, décalé du retard de séance du benchmark)."""
    model = _model_of(conn, rule["config"]["trial_id"])
    config = RunConfig.model_validate_json(model["config_json"])
    asset = prices.ensure_bars(conn, model["asset"]).df
    bench = prices.ensure_bars(conn, model["benchmark"]).df
    if asset is None or bench is None or asset.empty or bench.empty:
        raise store.FundError(f"β inconnu : cotations indisponibles pour {model['asset']} ou {model['benchmark']}")
    lag = alpha_target.bench_lag(config.objective)
    beta = alpha_target.point_in_time_beta(asset["close"], bench["close"]).shift(lag)
    known = beta.loc[:pd.Timestamp(signal_day)].dropna()
    if known.empty:
        raise store.FundError(f"β inconnu à la date du signal ({signal_day}) : moins de "
                              f"{alpha_target.DEFAULT_MIN_OBS} rendements communs avec le benchmark")
    return float(known.iloc[-1])


def _hedge_request(rule: dict, item: dict, side: str, quantity: float) -> dict:
    hedge = rule["config"]["hedge"]
    req = {"strategy_id": rule["strategy_id"], "action": "open", "instrument_kind": hedge["kind"], "side": side,
           "date": item["requested"], "position_id": item["hedge_position_id"], "note": item["hedge_note"],
           "quantity": quantity}
    if hedge["kind"] == "cfd":
        req["symbol"] = hedge["symbol"]
    if hedge["spec"]:
        req["spec"] = dict(hedge["spec"])
    return req


def _open_pair(conn: sqlite3.Connection, rule: dict, item: dict, today: dt.date) -> list[int]:
    """Cote la jambe actif, calcule la jambe de couverture (β × montant de l'actif), cote la couverture, puis place
    les deux. Rien n'est placé si l'une des deux est refusée ; si la seconde échoue après la première (course),
    la première est retirée : jamais de jambe actif non couverte."""
    asset_req = item["request"]
    quote = service.quote(conn, asset_req, today)
    if not quote["ok"]:
        raise service.FundRuleError(quote["blocking"])
    beta = _beta_at(conn, rule, item["signal"])
    long_asset = item["side"] == "long"
    hedge_side = ("short" if long_asset else "long") if beta > 0 else ("long" if long_asset else "short")
    hedge_notional = abs(beta) * quote["preview"]["notional_base"]

    unit = service.quote(conn, _hedge_request(rule, item, hedge_side, 1), today)
    if unit["preview"] is None or unit["preview"]["notional_base"] in (None, 0):
        raise service.FundRuleError(unit["blocking"] or ["couverture : cotation indisponible"])
    if unit["blocking"]:
        raise service.FundRuleError(unit["blocking"])
    quantity = hedge_notional / unit["preview"]["notional_base"]
    quantity = float(max(1, round(quantity))) if rule["config"]["hedge"]["kind"] == "future" else round(quantity, 4)
    if quantity <= 0:
        raise store.FundError("couverture : quantité nulle (montant de l'actif trop petit pour ce β)")
    hedge_req = _hedge_request(rule, item, hedge_side, quantity)
    checked = service.quote(conn, hedge_req, today)
    if not checked["ok"]:
        raise service.FundRuleError(checked["blocking"])

    first = service.place_order(conn, asset_req, today)
    try:
        second = service.place_order(conn, hedge_req, today)
    except Exception:
        store.delete_position(conn, asset_req["position_id"])
        raise
    return [first["order_id"], second["order_id"]]


def _close_pair(conn: sqlite3.Connection, item: dict, today: dt.date) -> list[int]:
    first = service.place_order(conn, item["request"], today)
    second = service.place_order(conn, item["hedge_request"], today)
    return [first["order_id"], second["order_id"]]


def apply(conn: sqlite3.Connection, rule_id: str, today: dt.date | None = None) -> dict:
    """Place les ordres de la règle qui n'existent pas encore.

    `placed` : ordres passés; `refused` : refusés par les règles (avec motifs);
    `skipped` : fermetures d'une position jamais ouverte; `pending` : exécution
    dans le futur; `already` : déjà présents; `drift` : ordres automatiques
    existants qui ne sont plus dans le plan (jamais supprimés). Règle d'alpha :
    un élément = une paire (actif + couverture), placée ou refusée ensemble."""
    rule = get_rule(conn, rule_id)
    if rule is None:
        raise store.FundError("règle introuvable")
    today = service._today(today)
    planned = plan(conn, rule)
    hedged = "hedge" in rule["config"]
    prefix = f"{NOTE_PREFIX}:{rule_id}:"
    existing = {o["note"] for o in store.list_orders(conn, rule["strategy_id"])
                if o.get("note") and o["note"].startswith(prefix)}
    planned_notes = {p["note"] for p in planned} | {p["hedge_note"] for p in planned if "hedge_note" in p}
    result: dict = {"placed": [], "refused": [], "skipped": [], "pending": [], "already": 0,
                    "drift": sorted(existing - planned_notes),
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
            if not hedged:
                order_ids = [service.place_order(conn, req, today)["order_id"]]
            elif item["action"] == "open":
                order_ids = _open_pair(conn, rule, item, today)
            else:
                order_ids = _close_pair(conn, item, today)
        except service.FundRuleError as exc:
            result["refused"].append({**brief, "reasons": list(exc.blocking)})
        except store.FundError as exc:
            result["refused"].append({**brief, "reasons": [str(exc)]})
        else:
            result["placed"].append({**brief, "order_id": order_ids[0], "order_ids": order_ids})
            continue
        if item["action"] == "open":
            unopened.add(req["position_id"])
    return result
