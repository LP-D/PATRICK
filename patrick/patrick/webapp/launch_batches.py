"""Lots prêts à lancer des pages Modèles (ML, DL, RL) : ce que la base sait déjà et ce qui manque.

Trois lots, en plus des profils d'entraînement :
- **une carte par classe d'actifs** (depuis 2026-10-23, à la place de « cibles jamais lancées » : toutes les cibles ont été faites) :
  sélectionne d'un clic toutes les cibles de la classe (actions US, Europe, Asie-Pacifique, futures, devises, crypto, volatilité, macro…) ;
  le compte dit combien n'ont encore aucun run de la famille (RL : aucun run RL) ;
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
import time
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


# Ordre d'affichage des classes d'actifs (les clés sont celles de `data/session_calendar.classify_asset_class`).
CLASS_ORDER = ("equities_us", "equities_europe", "equities_asia_pacific", "equities_americas_other", "futures", "fx", "crypto",
               "volatility_index", "macro", "other")


def by_asset_class(candidates: Iterable[str], never: Iterable[str], sources: dict[str, str],
                   evidence: dict[str, dict] | None = None) -> list[dict]:
    """`[{"key": classe, "symbols": [cibles], "never": n}]` : les cibles proposables regroupées par classe d'actifs (ordre `CLASS_ORDER`,
    classes vides omises) ; `never` = combien n'ont encore aucun run. `sources` : `{cible: "yfinance" | "fred"}` (une cible absente est
    classée comme une valeur yfinance). `evidence` : `{classe: {"auc": AUC regroupée moyenne, "n_significant": paires significatives}}`
    (`tracking/pooled_signal.py`) : les classes mesurées passent devant, la plus forte AUC d'abord, et la carte affiche la mesure ;
    sans mesure, l'ordre est celui de `CLASS_ORDER`."""
    from patrick.data.session_calendar import classify_asset_class

    never_set = set(never)
    groups: dict[str, list[str]] = {}
    for symbol in candidates:
        groups.setdefault(classify_asset_class(symbol, sources.get(symbol, "yfinance")), []).append(symbol)
    keys = [k for k in CLASS_ORDER if k in groups] + sorted(k for k in groups if k not in CLASS_ORDER)
    evidence = {k: v for k, v in (evidence or {}).items() if v.get("auc") is not None}
    keys = sorted((k for k in keys if k in evidence), key=lambda k: -evidence[k]["auc"]) + [k for k in keys if k not in evidence]
    return [{"key": k, "symbols": groups[k], "never": sum(1 for s in groups[k] if s in never_set),
             "auc": evidence.get(k, {}).get("auc"), "n_significant": evidence.get(k, {}).get("n_significant")} for k in keys]


def overview(conn: sqlite3.Connection, family: str, symbols: Iterable[str], first_dates: dict[str, str], today: date,
             min_years: float = D.DEFAULT_MIN_HISTORY_YEARS, horizons: Iterable[int] = D.DEFAULT_HORIZONS,
             sources: dict[str, str] | None = None, evidence: dict[str, dict] | None = None) -> dict:
    """`{"never": [cibles], "missing": {cible: [horizons]}}` pour `family` (`ml`, `dl` ou `rl`) ; `symbols` = cibles proposables.
    Pas d'horizon pour le RL : `missing` y est toujours vide. Avec `sources`, ajoute `"by_class"` (`by_asset_class`)."""
    candidates = [s for s in dict.fromkeys(symbols) if _long_enough(s, first_dates, today, min_years)]
    if family == "rl":
        done = rl_executed_targets(conn)
        out = {"never": [s for s in candidates if s not in done], "missing": {}}
    else:
        done_pairs = executed_pairs(conn, family)
        wanted = list(horizons)
        missing = {s: gaps for s in candidates if s in done_pairs and (gaps := [h for h in wanted if h not in done_pairs[s]])}
        out = {"never": [s for s in candidates if s not in done_pairs], "missing": missing}
    if sources is not None:
        out["by_class"] = by_asset_class(candidates, out["never"], sources, evidence)
    return out


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


def note_relaunch(job_id: str, parent_run_id: str, key: str, source: str) -> None:
    """Garde quel run et quelle suggestion ont produit ce job (`relaunch_stats`), pour mesurer plus tard lesquelles valent leur temps de calcul.
    Mesure seulement : une base inaccessible ne doit jamais empêcher un lancement."""
    from patrick.tracking import db as trackdb
    from patrick.tracking import relaunch_stats

    try:
        conn = trackdb.connect()
    except Exception:  # noqa: BLE001
        return
    try:
        relaunch_stats.record_relaunch(conn, job_id, parent_run_id, key, source)
    finally:
        conn.close()


_ADVICE_TTL_S = 600.0
_advice_cache: dict[tuple[str, str], tuple[float, dict | None]] = {}


def _advice(conn: sqlite3.Connection, run_id: str, history: dict) -> dict | None:
    """`advise_run` d'un run, gardé 10 minutes : la page calcule le lot (analyse de chaque cible), puis la confirmation le refait pour construire chaque
    configuration. Sans cette mémoire le second passage coûtait autant que le premier (~3 min pour 519 cibles le 07/11/2026). Clé : base + run."""
    from patrick.tracking import retrain_advisor

    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    key = (db_file, run_id)
    now = time.monotonic()
    hit = _advice_cache.get(key)
    if hit is not None and now - hit[0] < _ADVICE_TTL_S:
        return hit[1]
    if len(_advice_cache) > 4000:
        _advice_cache.clear()
    result = retrain_advisor.advise_run(conn, run_id, history=history, limit=20)
    _advice_cache[key] = (now, result)
    return result


def recommended(conn: sqlite3.Connection, history: dict) -> list[dict]:
    """Lot « runs conseillés » (ML) : par cible, le meilleur réentraînement proposé pour son dernier run terminé. Une ligne par
    cible : `run_id`, `target`, `horizons` (ceux du lancement d'origine), `key`, `score`, `cost`, `est_minutes`. Les cibles déjà en
    file sont écartées, comme celles dont la configuration refaite serait refusée par le formulaire (cible retirée de l'univers,
    ex. `^EVZ` ; historique devenu trop court…) : un seul refus annulant tout le lot à la mise en file, aucun run conseillé ne
    partirait. Le calcul (~0,07 s par run) se fait à la demande, pas au chargement de la page."""
    from patrick.webapp import forms

    latest: dict[str, tuple[str, int]] = {}
    for run_id, target, horizon, raw in conn.execute(
            "SELECT run_id, target, horizon, config_json FROM run WHERE status = 'done' ORDER BY started_at DESC, rowid DESC"):
        if ("__alpha_" not in target and target not in latest and target in forms.TARGET_SOURCE_BY_SYMBOL
                and forms.TARGET_SOURCE_BY_SYMBOL[target] not in D.NON_TARGET_SOURCES
                and config_family(_loads(raw)) == "ml"):
            latest[target] = (run_id, int(horizon))
    busy = pending_targets(conn, "ml")
    out = []
    for target, (run_id, horizon) in latest.items():
        if target in busy:
            continue
        suggestion = best_suggestion(_advice(conn, run_id, history))
        if suggestion is None:
            continue
        config, _ = _ml_run_config(conn, run_id)
        if config is None or _refit(config, suggestion)[0] is None:
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
    config, errors = _ml_run_config(conn, run_id)
    if config is None:
        return None, errors
    suggestion = best_suggestion(_advice(conn, run_id, history), key)
    if suggestion is None:
        return None, [f"{run_id} : la suggestion « {key} » n'est plus proposée pour ce run."]
    return _refit(config, suggestion)


def source_config(conn: sqlite3.Connection, source_id: str):
    """`(RunConfig, [])` de la configuration d'un job ou d'un run (ML ou DL), ou `(None, [erreurs])` s'il est introuvable, s'il n'a pas de
    configuration (run de renforcement : pas de `RunConfig`) ou si la sienne n'est plus lisible par le schéma d'aujourd'hui."""
    from pydantic import ValidationError

    from patrick.config.schema import RunConfig
    from patrick.tracking import db as trackdb
    from patrick.webapp import run_manager

    config = run_manager.get_run_config(source_id)
    if config is None:
        row = trackdb.get_run(conn, source_id)
        if row is None or not row.get("config_json"):
            return None, [f"{source_id} : run introuvable (configuration indisponible)."]
        try:
            config = RunConfig.model_validate_json(row["config_json"])
        except ValidationError:
            return None, [f"{source_id} : configuration d'un ancien run, devenue illisible."]
    return config, []


def _ml_run_config(conn: sqlite3.Connection, run_id: str):
    """`(RunConfig, [])` du run `run_id`, ou `(None, [erreurs])` s'il est introuvable ou n'est pas un run de machine learning."""
    config, errors = source_config(conn, run_id)
    if config is not None and config.family != "ml":
        return None, [f"{run_id} : le conseiller ne s'applique qu'aux runs de machine learning."]
    return config, errors


def refit(config, patch: dict):
    """`(RunConfig, [])` ou `(None, [erreurs])` : `config` refaite avec `patch` (champs du formulaire de lancement ; `{}` = les mêmes
    réglages), par le chemin du formulaire. Un nouveau nom de run est pris à chaque appel."""
    from pydantic import ValidationError

    from patrick.config.schema import RunConfig
    from patrick.webapp import forms, run_manager

    cfg = config.model_dump()
    cfg["output"]["dir"] = ""
    view = forms.to_view(cfg)
    view = {**view, **{k: v for k, v in patch.items() if k in view}}
    symbol = view["target_symbol"]
    config_dict, errors = forms.build_config_dict(forms.FormFromView(view), target_symbol=symbol, name=run_manager.next_run_name(symbol))
    if not errors:
        try:
            return RunConfig.model_validate(config_dict), []
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()]
    return None, [f"{symbol} : {e}" for e in errors]


def _refit(config, suggestion):
    """`refit` avec la modification d'une proposition du conseiller."""
    return refit(config, suggestion.patch)


def pending_pairs(conn: sqlite3.Connection) -> dict[str, set[int]]:
    """`{cible: {horizons}}` des jobs de classification déjà en file ou en cours (ML et DL) : ce qu'un lot ne doit pas doubler."""
    out: dict[str, set[int]] = {}
    marks = ",".join("?" for _ in PENDING_STATUSES)
    for (raw,) in conn.execute(f"SELECT config_json FROM job WHERE status IN ({marks})", PENDING_STATUSES):
        cfg = _loads(raw)
        objective = cfg.get("objective") or {}
        if cfg.get("kind") != "rl" and objective.get("target_symbol"):
            out.setdefault(objective["target_symbol"], set()).update(int(h) for h in objective.get("horizons") or [])
    return out
