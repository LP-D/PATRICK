"""Lots prêts à lancer des pages Modèles (ML, DL, RL) : ce que la base sait déjà et ce qui manque.

Trois lots, en plus des profils d'entraînement :
- **une carte par classe d'actifs** (depuis 2026-10-23, à la place de « cibles jamais lancées » : toutes les cibles ont été faites) :
  sélectionne d'un clic toutes les cibles de la classe (actions US, Europe, Asie-Pacifique, futures, devises, crypto, volatilité, macro…) ;
  le compte dit combien n'ont encore aucun run de la famille (RL : aucun run RL) ;
- **horizons jamais lancés** : pour les cibles déjà entraînées, les horizons par défaut sans run (couple cible × horizon) ;
- **runs conseillés** (ML) : pour chaque cible, le meilleur réentraînement proposé par le conseiller
  (`tracking/retrain_advisor.py`), appliqué à la configuration de son dernier run terminé.

Deux objectifs (ADR 0029, 0032) : la direction (classes) et la valeur exacte (rendement prévu, étiquette `symbole__val`, champions à
part). Chaque lot se compte pour UN objectif : un run de valeur exacte ne « fait » pas la direction de sa cible, et inversement (avant le
2026-11-27, un job de valeur exacte en file comptait comme la direction de sa cible et un run `X__val` comme une cible inconnue). Les pages
ML et DL montrent les lots de la direction, puis ceux de la valeur exacte (cartes `data-task="value"`, qui basculent le formulaire) :
- par classe d'actifs, avec le nombre de cibles jamais modélisées en valeur exacte dans cette famille ;
- **valeur exacte là où la direction a un signal** : les cibles au signal regroupé le plus fort (`top_signal`) sans modèle de valeur ;
- **déjà essayées dans l'autre famille** : cibles modélisées en valeur exacte en réseaux mais jamais en arbres (ou l'inverse) ;
- horizons jamais lancés en valeur exacte.

Un run « fait » = terminé ou en cours (table `run`), ou déjà en file / en cours (table `job`) : un lot n'en double jamais un autre.
Un run échoué ne compte pas, il peut être relancé. Les cibles à historique trop court (< `min_history_years`) sont écartées, comme
le formulaire les grise. Rien n'est lancé ici : les lots 1 et 2 pré-remplissent le formulaire, le lot 3 demande une confirmation.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from patrick.config import defaults as D
from patrick.config.target_label import run_label, split_task
from patrick.rl.history import DELETED_PHASE, RL_JOB_FILTER

logger = logging.getLogger(__name__)

PENDING_STATUSES = ("queued", "running")
EXECUTED_RUN_STATUSES = ("done", "running")


def config_family(config: dict) -> str:
    """« dl » si tous les algorithmes du run sont des réseaux de neurones, sinon « ml » (même règle que `RunConfig.family`)."""
    algos = (config.get("models") or {}).get("algos") or []
    return "dl" if algos and all(a in D.ALL_DL_ALGOS for a in algos) else "ml"


TASKS = ("direction", "value")


def config_task(config: dict) -> str:
    """Objectif d'une configuration (`objective.task`) : « value » pour la valeur exacte, « direction » sinon (défaut historique)."""
    return "value" if (config.get("objective") or {}).get("task") == "value" else "direction"


def _loads(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def executed_pairs(conn: sqlite3.Connection, family: str, task: str = "direction") -> dict[str, set[int]]:
    """`{cible: {horizons}}` des runs déjà faits, en cours ou en attente, pour la famille `ml` ou `dl` et l'objectif `task`
    (`direction` : classes ; `value` : valeur exacte, run `symbole__val`). La clé est toujours le symbole."""
    out: dict[str, set[int]] = {}
    marks = ",".join("?" for _ in EXECUTED_RUN_STATUSES)
    for target, horizon, raw in conn.execute(
            f"SELECT target, horizon, config_json FROM run WHERE status IN ({marks})", EXECUTED_RUN_STATUSES):
        base, run_task = split_task(target)
        if "__alpha_" not in base and run_task == task and config_family(_loads(raw)) == family:
            out.setdefault(base, set()).add(int(horizon))
    marks = ",".join("?" for _ in PENDING_STATUSES)
    for (raw,) in conn.execute(f"SELECT config_json FROM job WHERE status IN ({marks})", PENDING_STATUSES):
        cfg = _loads(raw)
        if cfg.get("kind") == "rl" or config_family(cfg) != family or config_task(cfg) != task:
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
             sources: dict[str, str] | None = None, evidence: dict[str, dict] | None = None, task: str = "direction") -> dict:
    """`{"never": [cibles], "missing": {cible: [horizons]}}` pour `family` (`ml`, `dl` ou `rl`) et l'objectif `task` ; `symbols` =
    cibles proposables. Pas d'horizon pour le RL : `missing` y est toujours vide. Avec `sources`, ajoute `"by_class"` (`by_asset_class`).
    Valeur exacte (`task="value"`) : ajoute `"cross"`, les cibles déjà modélisées en valeur exacte dans l'AUTRE famille (réseaux / arbres)
    mais jamais dans celle-ci."""
    candidates = [s for s in dict.fromkeys(symbols) if _long_enough(s, first_dates, today, min_years)]
    if family == "rl":
        done = rl_executed_targets(conn)
        out = {"never": [s for s in candidates if s not in done], "missing": {}}
    else:
        done_pairs = executed_pairs(conn, family, task)
        wanted = list(horizons)
        missing = {s: gaps for s in candidates if s in done_pairs and (gaps := [h for h in wanted if h not in done_pairs[s]])}
        out = {"never": [s for s in candidates if s not in done_pairs], "missing": missing}
        if task == "value":
            other = executed_pairs(conn, "dl" if family == "ml" else "ml", task)
            out["cross"] = [s for s in out["never"] if s in other]
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


def pending_targets(conn: sqlite3.Connection, family: str, task: str = "direction") -> set[str]:
    """Cibles déjà en file ou en cours pour la famille `ml`/`dl` et l'objectif `task` (un lot ne les double pas)."""
    marks = ",".join("?" for _ in PENDING_STATUSES)
    out: set[str] = set()
    for (raw,) in conn.execute(f"SELECT config_json FROM job WHERE status IN ({marks})", PENDING_STATUSES):
        cfg = _loads(raw)
        if cfg.get("kind") != "rl" and config_family(cfg) == family and config_task(cfg) == task:
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
    except Exception as exc:  # noqa: BLE001 -- mesure seulement : une base inaccessible n'empêche jamais un lancement
        logger.warning("origine du lancement non enregistrée (base inaccessible) : %s: %s", type(exc).__name__, exc)
        return
    try:
        relaunch_stats.record_relaunch(conn, job_id, parent_run_id, key, source)
    finally:
        conn.close()


_ADVICE_TTL_S = 1800.0
_advice_cache: dict[tuple[str, str], tuple[float, dict | None]] = {}
ADVICE_WORKERS = 4                  # analyses menées en parallèle par le lot conseillé (SQLite lit en parallèle, chaque fil a sa connexion)
_analysis_lock = threading.Lock()   # une seule analyse du lot à la fois : un second clic attend la première (puis lit son cache) au lieu d'en lancer une autre
_progress: dict = {"running": False, "done": 0, "total": 0}


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


_prewarm_lock = threading.Lock()
_prewarm_at: float | None = None


def prewarm(db_path: str | None = None) -> bool:
    """Lance en arrière-plan l'analyse du lot conseillé (une fois par durée de validité du cache, jamais deux en même temps) : la page Modèles la
    déclenche en chargeant ses lots, et le clic sur « Runs conseillés » tombe alors sur des analyses déjà faites (ou en cours : il attend la fin
    au lieu de tout refaire). 70 s sur une machine au repos, davantage quand l'application démarre. `PATRICK_ADVICE_PREWARM=0` l'inhibe.
    Renvoie `True` si une analyse a été lancée."""
    global _prewarm_at
    if os.environ.get("PATRICK_ADVICE_PREWARM", "1") == "0":
        return False
    now = time.monotonic()
    with _prewarm_lock:
        if _progress["running"] or (_prewarm_at is not None and now - _prewarm_at < _ADVICE_TTL_S - 120):
            return False
        _prewarm_at = now
    threading.Thread(target=_prewarm_run, args=(db_path,), name="advice-prewarm", daemon=True).start()
    return True


def _prewarm_run(db_path: str | None) -> None:
    from patrick.tracking import data_health
    from patrick.tracking import db as trackdb

    try:
        conn = trackdb.connect(db_path)
        try:
            recommended(conn, data_health.history_depths(), workers=2)         # 2 fils : l'application reste réactive pendant ce temps
        finally:
            conn.close()
    except Exception:  # un préchauffage raté ne doit jamais gêner la page ; le clic refera l'analyse
        logger.exception("préchauffage de l'analyse des runs conseillés")


def analysis_progress() -> dict:
    """`{"running", "done", "total"}` de l'analyse du lot conseillé en cours (la page l'affiche pendant l'attente)."""
    return dict(_progress)


def _warm_advice(conn: sqlite3.Connection, run_ids: list[str], history: dict, workers: int) -> None:
    """Remplit `_advice_cache` pour `run_ids` (le conseiller analyse chaque run, 0,3 à 1,5 s sur la vraie base : 505 cibles font plusieurs minutes
    d'un seul fil), en `workers` fils quand `workers > 1`, et tient `_progress` à jour. Chaque fil lit avec sa propre connexion."""
    _progress.update(done=0, total=len(run_ids))
    if workers <= 1 or len(run_ids) < 2:
        for run_id in run_ids:
            _advice(conn, run_id, history)
            _progress["done"] += 1
        return
    from patrick.tracking import db as trackdb

    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    guard = threading.Lock()

    def work(run_id: str) -> None:
        own = trackdb.connect(db_file)          # une connexion SQLite ne sert que dans le fil qui l'a ouverte ; en ouvrir une coûte quelques millisecondes
        try:
            _advice(own, run_id, history)
        finally:
            own.close()
        with guard:
            _progress["done"] += 1

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="advice") as pool:
        list(pool.map(work, run_ids))


def recommended(conn: sqlite3.Connection, history: dict, workers: int = 1) -> list[dict]:
    """Lot « runs conseillés » (ML) : par cible, le meilleur réentraînement proposé pour son dernier run terminé. Une ligne par
    cible : `run_id`, `target`, `horizons` (ceux du lancement d'origine), `key`, `score`, `cost`, `est_minutes`, `signal`, `value` ;
    classées par valeur attendue pour le temps de calcul (`expected_value`), plus par score seul. Les cibles déjà en
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
    signals = target_signals(conn)
    out = []
    with _analysis_lock:
        _progress["running"] = True
        try:
            _warm_advice(conn, [run_id for target, (run_id, _) in latest.items() if target not in busy], history, workers)
        finally:
            _progress["running"] = False
    for target, (run_id, horizon) in latest.items():
        if target in busy:
            continue
        suggestion = best_suggestion(_advice(conn, run_id, history))
        if suggestion is None:
            continue
        config, _ = _ml_run_config(conn, run_id)
        if config is None or _refit(config, suggestion, name="validation")[0] is None:
            continue
        signal = signals.get(target)
        out.append({"run_id": run_id, "target": target, "horizon": horizon, "key": suggestion.key, "score": round(suggestion.score),
                    "cost": suggestion.cost, "est_minutes": suggestion.est_minutes, "signal": signal,
                    "value": round(expected_value(suggestion.score, suggestion.est_minutes, signal), 1)})
    return sorted(out, key=lambda r: (-r["value"], -r["score"], r["target"]))


SIGNAL_BOOST = {True: 1.25, False: 0.8, None: 1.0}      # cible à signal regroupé significatif / mesurée sans signal / jamais mesurée


def expected_value(score: float, est_minutes: float | None, signal: bool | None) -> float:
    """Ce qu'une relance vaut pour son temps de calcul : le score du conseiller (déjà pondéré par le taux de victoire au duel de sa
    suggestion), relevé pour une cible dont le signal regroupé est significatif (`tracking/pooled_signal.py`), abaissé pour une cible
    mesurée sans signal, puis divisé par la durée (une heure de calcul divise la valeur par deux). Un lot conseillé dépasse 300 h : il
    n'est jamais mené au bout, l'ordre décide donc de ce qui tourne."""
    return float(score) * SIGNAL_BOOST[signal] / (1.0 + max(0.0, float(est_minutes or 0.0)) / 60.0)


TOP_SIGNAL_N = 50


def value_where_signal(conn: sqlite3.Connection, candidates: Iterable[str], never_value: Iterable[str], n: int = TOP_SIGNAL_N) -> list[str]:
    """Lot « valeur exacte là où la direction a un signal » : les cibles les plus prévisibles en direction (`top_signal`, signal regroupé)
    qui n'ont encore aucun modèle de valeur exacte dans la famille. Prédire l'amplitude n'a de chance que là où la direction se prévoit déjà."""
    never = set(never_value)
    return top_signal(conn, [s for s in candidates if s in never], n=n)


def top_signal(conn: sqlite3.Connection, candidates: Iterable[str], n: int = TOP_SIGNAL_N) -> list[str]:
    """Les `n` cibles proposables les plus prévisibles d'après l'AUC regroupée (`tracking/pooled_signal.py`) : celles dont une paire est
    significative d'abord, puis par meilleure AUC. C'est le lot d'une campagne ciblée (deep learning, réglage long) : dépenser le calcul
    là où un signal a déjà été mesuré plutôt que sur tout l'univers. Vide tant que la table n'a pas été calculée."""
    from patrick.tracking import pooled_signal

    allowed = set(candidates)
    best: dict[str, tuple[bool, float]] = {}
    try:
        rows = pooled_signal.load(conn)
    except sqlite3.Error:
        return []
    for row in rows:
        if row["target"] in allowed and row["auc"] is not None:
            sig, auc = best.get(row["target"], (False, 0.0))
            best[row["target"]] = (sig or bool(row["significant"]), max(auc, float(row["auc"])))
    ranked = sorted(best, key=lambda t: (not best[t][0], -best[t][1], t))
    return ranked[:n]


def target_signals(conn: sqlite3.Connection) -> dict[str, bool]:
    """`{cible: une de ses paires cible-horizon a un signal regroupé significatif}` ; une cible absente n'a jamais été mesurée."""
    from patrick.tracking import pooled_signal

    out: dict[str, bool] = {}
    try:
        for row in pooled_signal.load(conn):
            out[row["target"]] = out.get(row["target"], False) or bool(row["significant"])
    except sqlite3.Error:
        return {}
    return out


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


def refit(config, patch: dict, name: str | None = None):
    """`(RunConfig, [])` ou `(None, [erreurs])` : `config` refaite avec `patch` (champs du formulaire de lancement ; `{}` = les mêmes
    réglages), par le chemin du formulaire. Un nouveau nom de run est pris à chaque appel, sauf si `name` est donné (la validation d'un lot
    n'en a pas besoin : chercher le prochain numéro de chaque cible coûtait 0,07 s, un tiers du temps de la reconstruction)."""
    from pydantic import ValidationError

    from patrick.config.schema import RunConfig
    from patrick.webapp import forms, run_manager

    cfg = config.model_dump()
    cfg["output"]["dir"] = ""
    view = forms.to_view(cfg)
    view = {**view, **{k: v for k, v in patch.items() if k in view}}
    symbol = view["target_symbol"]
    config_dict, errors = forms.build_config_dict(forms.FormFromView(view), target_symbol=symbol, name=name or run_manager.next_run_name(symbol))
    if not errors:
        try:
            return RunConfig.model_validate(config_dict), []
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()]
    return None, [f"{symbol} : {e}" for e in errors]


def _refit(config, suggestion, name: str | None = None):
    """`refit` avec la modification d'une proposition du conseiller."""
    return refit(config, suggestion.patch, name)


def pending_pairs(conn: sqlite3.Connection) -> dict[str, set[int]]:
    """`{cible: {horizons}}` des jobs ML et DL déjà en file ou en cours : ce qu'un lot ne doit pas doubler. La clé dit l'objectif : le
    symbole pour la direction, `symbole__val` pour la valeur exacte (`config.target_label.run_label`) -- un job de valeur exacte en file ne
    bloque pas la relance de la direction de sa cible."""
    out: dict[str, set[int]] = {}
    marks = ",".join("?" for _ in PENDING_STATUSES)
    for (raw,) in conn.execute(f"SELECT config_json FROM job WHERE status IN ({marks})", PENDING_STATUSES):
        cfg = _loads(raw)
        objective = cfg.get("objective") or {}
        if cfg.get("kind") != "rl" and objective.get("target_symbol"):
            key = run_label(objective["target_symbol"], task=config_task(cfg))
            out.setdefault(key, set()).update(int(h) for h in objective.get("horizons") or [])
    return out
