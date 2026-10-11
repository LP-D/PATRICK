"""Lots prêts à lancer des pages Modèles (ML, DL, RL) : ce que la base sait déjà et ce qui manque.

Trois lots, en plus des profils d'entraînement :
- **cibles jamais lancées** : les cibles de l'univers sans aucun run de la famille (RL : sans run RL) ;
- **horizons jamais lancés** : pour les cibles déjà entraînées, les horizons par défaut sans run (couple cible × horizon) ;
- **runs conseillés** (ML) : pour chaque cible, le meilleur réentraînement proposé par le conseiller
  (`tracking/retrain_advisor.py`), appliqué à la configuration de son dernier run terminé.

Un run « fait » = terminé ou en cours (table `run`), ou déjà en file / en cours (table `job`) : un lot n'en double jamais un autre.
Un run échoué ne compte pas, il peut être relancé. Les cibles à historique trop court (< `min_history_years`) sont écartées, comme
le formulaire les grise. Rien n'est lancé ici : les lots 1 et 2 pré-remplissent le formulaire, le lot 3 demande une confirmation.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import date, timedelta

from patrick.config import defaults as D
from patrick.rl.history import DELETED_PHASE, RL_JOB_FILTER

PENDING_STATUSES = ("queued", "running")
EXECUTED_RUN_STATUSES = ("done", "running")


def config_family(config: dict) -> str:
    """« dl » si tous les algorithmes du run sont des réseaux de neurones, sinon « ml » (même règle que `RunConfig.family`)."""
    algos = (config.get("models") or {}).get("algos") or []
    return "dl" if algos and all(a in D.ALL_DL_ALGOS for a in algos) else "ml"


def _loads(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def executed_pairs(conn: sqlite3.Connection, family: str) -> dict[str, set[int]]:
    """`{cible: {horizons}}` des runs de classification déjà faits, en cours ou en attente, pour la famille `ml` ou `dl`."""
    out: dict[str, set[int]] = {}
    marks = ",".join("?" for _ in EXECUTED_RUN_STATUSES)
    for target, horizon, raw in conn.execute(
            f"SELECT target, horizon, config_json FROM run WHERE status IN ({marks})", EXECUTED_RUN_STATUSES):
        if "__alpha_" not in target and config_family(_loads(raw)) == family:
            out.setdefault(target, set()).add(int(horizon))
    marks = ",".join("?" for _ in PENDING_STATUSES)
    for (raw,) in conn.execute(f"SELECT config_json FROM job WHERE status IN ({marks})", PENDING_STATUSES):
        cfg = _loads(raw)
        if cfg.get("kind") == "rl" or config_family(cfg) != family:
            continue
        objective = cfg.get("objective") or {}
        symbol = objective.get("target_symbol")
        if symbol:
            out.setdefault(symbol, set()).update(int(h) for h in objective.get("horizons") or [])
    return out


def rl_executed_targets(conn: sqlite3.Connection) -> set[str]:
    """Cibles ayant au moins un run RL (terminé, en cours ou en attente), hors échecs et hors runs supprimés."""
    out: set[str] = set()
    for (raw,) in conn.execute("SELECT config_json FROM job WHERE config_json LIKE ? AND phase != ? AND status != 'error'",
                               (RL_JOB_FILTER, DELETED_PHASE)):
        symbol = (_loads(raw).get("objective") or {}).get("target_symbol")
        if symbol:
            out.add(symbol)
    return out


def _long_enough(symbol: str, first_dates: dict[str, str], today: date, min_years: float) -> bool:
    """Faux seulement si on SAIT que l'historique est trop court (première date connue plus récente que le seuil)."""
    first = first_dates.get(symbol)
    if not first:
        return True
    try:
        return date.fromisoformat(first) <= today - timedelta(days=int(min_years * 365.25))
    except ValueError:
        return True


def overview(conn: sqlite3.Connection, family: str, symbols: Iterable[str], first_dates: dict[str, str], today: date,
             min_years: float = D.DEFAULT_MIN_HISTORY_YEARS, horizons: Iterable[int] = D.DEFAULT_HORIZONS) -> dict:
    """`{"never": [cibles], "missing": {cible: [horizons]}}` pour `family` (`ml`, `dl` ou `rl`) ; `symbols` = cibles proposables.
    Pas d'horizon pour le RL : `missing` y est toujours vide."""
    candidates = [s for s in dict.fromkeys(symbols) if _long_enough(s, first_dates, today, min_years)]
    if family == "rl":
        done = rl_executed_targets(conn)
        return {"never": [s for s in candidates if s not in done], "missing": {}}
    done_pairs = executed_pairs(conn, family)
    wanted = list(horizons)
    missing = {s: gaps for s in candidates if s in done_pairs and (gaps := [h for h in wanted if h not in done_pairs[s]])}
    return {"never": [s for s in candidates if s not in done_pairs], "missing": missing}


class FormOverride:
    """Le formulaire reçu, dont certains champs sont remplacés (ex. `horizons` limités aux horizons jamais lancés d'une cible)."""

    def __init__(self, form, **lists: list):
        self._form, self._lists = form, {k: [str(v) for v in values] for k, values in lists.items()}

    def get(self, name: str, default=None):
        if name in self._lists:
            return self._lists[name][0] if self._lists[name] else default
        return self._form.get(name, default)

    def getlist(self, name: str) -> list:
        return list(self._lists[name]) if name in self._lists else self._form.getlist(name)


def pending_targets(conn: sqlite3.Connection, family: str) -> set[str]:
    """Cibles déjà en file ou en cours pour la famille `ml`/`dl` (un lot ne les double pas)."""
    marks = ",".join("?" for _ in PENDING_STATUSES)
    out: set[str] = set()
    for (raw,) in conn.execute(f"SELECT config_json FROM job WHERE status IN ({marks})", PENDING_STATUSES):
        cfg = _loads(raw)
        if cfg.get("kind") != "rl" and config_family(cfg) == family:
            symbol = (cfg.get("objective") or {}).get("target_symbol")
            if symbol:
                out.add(symbol)
    return out


def best_suggestion(advice: dict | None, key: str | None = None):
    """La proposition du conseiller qu'un lot peut lancer seule : disponible et applicable par le formulaire (ni action manuelle, ni
    levier absent) ; son patch peut être vide : « garde anti-fuite » relance avec les réglages d'aujourd'hui. `key` : celle-là
    précisément ; sinon la mieux classée."""
    for s in (advice or {}).get("suggestions", []):
        if s.available and not s.manual and (key is None or s.key == key):
            return s
    return None


def recommended(conn: sqlite3.Connection, history: dict) -> list[dict]:
    """Lot « runs conseillés » (ML) : par cible, le meilleur réentraînement proposé pour son dernier run terminé. Une ligne par
    cible : `run_id`, `target`, `horizons` (ceux du lancement d'origine), `key`, `score`, `cost`, `est_minutes`. Les cibles déjà en
    file sont écartées ; le calcul (~0,07 s par run) se fait à la demande, pas au chargement de la page."""
    from patrick.tracking import retrain_advisor

    latest: dict[str, tuple[str, int]] = {}
    for run_id, target, horizon, raw in conn.execute(
            "SELECT run_id, target, horizon, config_json FROM run WHERE status = 'done' ORDER BY started_at DESC, rowid DESC"):
        if "__alpha_" not in target and target not in latest and config_family(_loads(raw)) == "ml":
            latest[target] = (run_id, int(horizon))
    busy = pending_targets(conn, "ml")
    out = []
    for target, (run_id, horizon) in latest.items():
        if target in busy:
            continue
        suggestion = best_suggestion(retrain_advisor.advise_run(conn, run_id, history=history, limit=20))
        if suggestion is None:
            continue
        out.append({"run_id": run_id, "target": target, "horizon": horizon, "key": suggestion.key, "score": round(suggestion.score),
                    "cost": suggestion.cost, "est_minutes": suggestion.est_minutes})
    return sorted(out, key=lambda r: (-r["score"], r["target"]))


def summarize(items: list[dict]) -> dict:
    """Répartition d'un lot par proposition et par coût, pour la confirmation."""
    by_key: dict[str, int] = {}
    by_cost: dict[str, int] = {}
    for item in items:
        by_key[item["key"]] = by_key.get(item["key"], 0) + 1
        by_cost[item["cost"]] = by_cost.get(item["cost"], 0) + 1
    return {"n": len(items), "by_key": by_key, "by_cost": by_cost}


def build_recommended_config(conn: sqlite3.Connection, run_id: str, key: str, history: dict):
    """`(RunConfig, [])` ou `(None, [erreurs])` : la configuration du run `run_id` avec la suggestion `key` du conseiller, telle
    qu'on la lancerait en ouvrant `/ml?run_id=…&suggest=…` puis « Lancer » (même vue du formulaire, mêmes validations)."""
    from pydantic import ValidationError

    from patrick.config.schema import RunConfig
    from patrick.tracking import db as trackdb
    from patrick.tracking import retrain_advisor
    from patrick.webapp import forms, run_manager

    config = run_manager.get_run_config(run_id)
    if config is None:
        row = trackdb.get_run(conn, run_id)
        if row is None or not row.get("config_json"):
            return None, [f"{run_id} : run introuvable (configuration indisponible)."]
        config = RunConfig.model_validate_json(row["config_json"])
    if config.family != "ml":
        return None, [f"{run_id} : le conseiller ne s'applique qu'aux runs de machine learning."]
    suggestion = best_suggestion(retrain_advisor.advise_run(conn, run_id, history=history, limit=20), key)
    if suggestion is None:
        return None, [f"{run_id} : la suggestion « {key} » n'est plus proposée pour ce run."]
    cfg = config.model_dump()
    cfg["output"]["dir"] = ""
    view = forms.to_view(cfg)
    view = {**view, **{k: v for k, v in suggestion.patch.items() if k in view}}
    symbol = view["target_symbol"]
    config_dict, errors = forms.build_config_dict(forms.FormFromView(view), target_symbol=symbol, name=run_manager.next_run_name(symbol))
    if not errors:
        try:
            return RunConfig.model_validate(config_dict), []
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()]
    return None, [f"{symbol} : {e}" for e in errors]
