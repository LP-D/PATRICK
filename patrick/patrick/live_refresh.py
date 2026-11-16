"""Actualisation des prédictions live (une par couple actif x horizon).

Partagé par `scripts/daily_predict.py` (planificateur de tâches) et par
l'app web : au lancement, puis chaque jour tant que l'app reste ouverte,
chaque modèle déjà entraîné rejoue `predict_live` sur les données du jour --
il fait sa nouvelle prédiction ET juge celles dont l'horizon est écoulé. Le
tableau /predictions montre donc le signal du jour, pas celui de
l'entraînement. Un jour où l'app était fermée est reconstitué au lancement
suivant (`predict.py`, `live_backfill=1`).

Jour de marché fermé : `predict_live` lit la dernière barre de la série de
l'actif lui-même. Pas de nouvelle barre = pas de nouvelle ligne (rien n'est
réécrit), et le signal affiché garde la date de sa dernière séance.
"""
from __future__ import annotations

import dataclasses
import errno
import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial

from patrick import cache_eviction, paths, settings
from patrick.clock import utc_today
from patrick.config.targets import is_macro_target
from patrick.tracking import db as trackdb
from patrick.tracking import relaunch_stats

logger = logging.getLogger("patrick.live_refresh")


@dataclass
class PredictCandidate:
    """Un (ticker, horizon) avec un run `done` exploitable identifié en base."""
    target: str
    horizon: int
    run_id: str
    trial_id: int
    artifact_path: str


@dataclass
class PredictOutcome:
    """Résultat de l'appel `predict_live` pour un candidat -- succès ou échec."""
    candidate: PredictCandidate
    ok: bool
    detail: dict | None = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""


@dataclass
class RunSummary:
    """Agrégat succès/échecs d'une exécution complète (tous les candidats). `aborted` : raison (déjà journalisée) d'un arrêt avant la fin,
    disque plein ; les candidats restants n'ont alors pas été tentés."""
    outcomes: list[PredictOutcome] = field(default_factory=list)
    aborted: str | None = None

    @property
    def successes(self) -> list[PredictOutcome]:
        return [o for o in self.outcomes if o.ok]

    @property
    def failures(self) -> list[PredictOutcome]:
        return [o for o in self.outcomes if not o.ok]

    def add(self, outcome: PredictOutcome) -> None:
        self.outcomes.append(outcome)


def find_predictable_candidates(conn, base_dir: str | None = None) -> list[PredictCandidate]:
    """Un candidat par (target, horizon) : le run `status='done'` le plus
    récent dont le trial `is_best=1` a un `artifact_path` non vide ET dont le
    fichier existe réellement -- vérifié sur disque, pas seulement en base
    (l'audit de la DB de production a trouvé des lignes `trial.artifact_path`
    non NULL pointant vers des fichiers déjà supprimés/déplacés).

    Chemins relatifs résolus contre `base_dir` (défaut `os.getcwd()`) :
    `predict_live()` fait `joblib.load(artifact_path)` tel quel, donc c'est le
    cwd du PROCESS au moment de l'appel qui doit correspondre."""
    base_dir = base_dir or os.getcwd()
    # Le champion en titre d'abord : un run plus récent qui n'a pas pu être comparé (CPCV de confirmation, run sans holdout) n'est pas
    # le modèle de la cellule. Sans cela le champion ne recevait plus de signal du jour, alors que les fonds, la sélection du pilote
    # et la page des prédictions lisent le sien (31 cellules dans ce cas le 2026-11-13).
    rows = conn.execute(
        "SELECT r.run_id, r.target, r.horizon, t.trial_id, t.artifact_path "
        "FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
        "LEFT JOIN champion c ON c.target = r.target AND c.horizon = r.horizon AND c.trial_id = t.trial_id "
        "WHERE r.status = 'done' AND t.artifact_path IS NOT NULL AND t.artifact_path != '' "
        "ORDER BY r.target, r.horizon, (c.trial_id IS NOT NULL) DESC, r.finished_at DESC"
    ).fetchall()

    latest_per_pair: dict[tuple[str, int], PredictCandidate] = {}
    for run_id, target, horizon, trial_id, artifact_path in rows:
        key = (target, horizon)
        if key in latest_per_pair:
            continue  # déjà gardé le plus récent (lignes triées DESC par finished_at)
        if is_macro_target(target):
            continue                  # série macro : plus une cible (2026-10-31), son signal du jour serait de la fausse information
        resolved = artifact_path if os.path.isabs(artifact_path) else os.path.join(base_dir, artifact_path)
        if not os.path.exists(resolved):
            logger.debug("Ignoré (fichier introuvable) : target=%s horizon=%s run_id=%s artifact_path=%s "
                         "(résolu: %s)", target, horizon, run_id, artifact_path, resolved)
            continue
        latest_per_pair[key] = PredictCandidate(target=target, horizon=horizon, run_id=run_id,
                                                  trial_id=trial_id, artifact_path=artifact_path)
    return list(latest_per_pair.values())


# --- Disque plein : le 15/11/2026, D: pleine, 2 984 prédictions tentées pour 2 985 échecs « [Errno 28] » sans alerte ------------------

KEY_MIN_FREE_GB = "predict_min_free_gb"
DEFAULT_MIN_FREE_GB = 5.0           # comme `FOLDER_MIN_FREE_BYTES` de sync.py
DISK_CHECK_EVERY = 25               # une prédiction dure une vingtaine de secondes : environ toutes les dix minutes
_WINERROR_DISK_FULL = 112           # ERROR_DISK_FULL ; Python le traduit déjà en errno 28, gardé par prudence


def min_free_bytes() -> int:
    """Seuil d'espace libre (réglage `predict_min_free_gb`, 5 Go) sous lequel les prédictions s'arrêtent ; 0 désactive le garde-fou.
    Un réglage illisible ou négatif ne le désactive pas : retour au défaut."""
    value = settings.load().get(KEY_MIN_FREE_GB, DEFAULT_MIN_FREE_GB)
    try:
        gb = float(value)
    except (TypeError, ValueError):
        return int(DEFAULT_MIN_FREE_GB * 1e9)
    return int(gb * 1e9) if gb >= 0 else int(DEFAULT_MIN_FREE_GB * 1e9)


def data_root_free_bytes() -> int:
    """Octets libres sur le disque de la racine de données (store, cache de variables, caches : tout ce que les prédictions écrivent)."""
    return shutil.disk_usage(paths.data_root()).free


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",") + " Go"


def _root_hint() -> str:
    try:
        return str(paths.data_root())
    except paths.DataRootUnavailable:
        return "dossier de données absent"


def _is_disk_full(exc: BaseException) -> bool:
    """`[Errno 28] No space left on device`, levée telle quelle, cause d'une autre exception, ou seulement dans le texte d'une
    erreur re-levée par une bibliothèque."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and (current.errno == errno.ENOSPC or getattr(current, "winerror", None) == _WINERROR_DISK_FULL):
            return True
        current = current.__cause__ or current.__context__
    return "No space left on device" in str(exc) or "[Errno 28]" in str(exc)


def trim_feature_cache() -> dict | None:
    """Ramène le cache de variables sous son plafond (réglage `feature_cache_max_gb`, 150 Go) : les fichiers les moins récemment lus
    d'abord, jamais ceux d'une heure ou moins. Seul ce cache : jamais la base (`evict_vol_cache`, `prune_db_caches` : elle ne se modifie
    pas pendant qu'un worker vit). Ne lève jamais ; renvoie le compte rendu de `evict_feature_cache`, ou `None` si l'éviction a échoué."""
    try:
        result = cache_eviction.evict_feature_cache()
    except Exception as exc:  # noqa: BLE001 -- entretien : jamais bloquant (racine de données absente, lecteur qui redémarre...)
        logger.warning("éviction du cache de variables non faite : %s: %s", type(exc).__name__, exc)
        return None
    logger.info("cache de variables : %d fichier(s) retiré(s) (%s), plafond %s", result.get("removed_files", 0),
                _gb(result.get("removed_bytes", 0)), _gb(result.get("cap", 0)))
    return result


def _eviction_sentence(result: dict | None) -> str:
    if result is None:
        return "L'éviction du cache de variables n'a pas pu être faite."
    n = result.get("removed_files", 0)
    sentence = f"L'éviction du cache de variables a retiré {n} fichier{'s' if n > 1 else ''} ({_gb(result.get('removed_bytes', 0))})"
    if "bytes" in result and "cap" in result:
        sentence += f", il reste {_gb(result['bytes'] - result.get('removed_bytes', 0))} pour un plafond de {_gb(result['cap'])}"
    return sentence + "."


def _stop_for_low_space(free_bytes_fn, floor: int, remaining: int) -> str | None:
    """Mesure l'espace libre ; sous `floor`, évince le cache de variables et mesure de nouveau. `None` : assez de place (ou mesure
    impossible : elle ne doit jamais empêcher une prédiction, qui dira elle-même son erreur). Sinon le message d'arrêt, journalisé UNE fois."""
    try:
        free = free_bytes_fn()
    except Exception as exc:  # noqa: BLE001 -- racine absente, lecteur qui redémarre : la mesure n'est pas un motif d'arrêt
        logger.warning("espace libre non mesuré : %s: %s", type(exc).__name__, exc)
        return None
    if free >= floor:
        return None
    logger.warning("Disque presque plein : %s libres sur %s (seuil %s) : éviction du cache de variables.", _gb(free), _root_hint(), _gb(floor))
    evicted = trim_feature_cache()
    try:
        free_after = free_bytes_fn()
    except Exception:  # noqa: BLE001 -- idem
        free_after = free
    if free_after >= floor:
        logger.info("Disque : %s libres après l'éviction, les prédictions continuent.", _gb(free_after))
        return None
    message = (f"Disque presque plein : {_gb(free_after)} libres sur {_root_hint()} (seuil {_gb(floor)}). {_eviction_sentence(evicted)} "
               f"Prédictions arrêtées, {remaining} non tentée{'s' if remaining > 1 else ''} : libère de la place (`patrick storage evict --feature-cache-gb 100`, "
               "anciennes sauvegardes) puis relance.")
    logger.error(message)
    return message


def _open_failure_tracker(db_path: str | None):
    """Connexion qui sert à noter les échecs ; `None` si la base est inaccessible (la mesure ne doit jamais empêcher une prédiction)."""
    try:
        return trackdb.connect(db_path)
    except Exception:  # noqa: BLE001 -- mesure : jamais bloquante
        return None


def run_daily_predictions(candidates: list[PredictCandidate], predict_live_fn=None,
                           db_path: str | None = None, on_item=None, track_failures: bool | None = None,
                           free_bytes_fn=None, check_every: int = DISK_CHECK_EVERY) -> RunSummary:
    """Appelle `predict_live_fn(candidate.run_id, db_path=db_path)` pour
    chaque candidat, un par un. Une exception sur UN item ne doit JAMAIS
    interrompre le traitement des suivants -- try/except par item, erreur
    loggée, boucle continue. Seule exception : un disque plein (voir ci-dessous).

    `predict_live_fn` est injectable (mocké dans les tests) ; par défaut,
    `patrick.predict.predict_live` avec un cache de téléchargement partagé
    entre les runs de même objectif/univers. `on_item(outcome)` : rappel de
    progression (affichage de l'avancement dans l'app).

    `track_failures` : noter dans la base (`live_failure`) les modèles qui échouent et effacer la note de ceux qui réussissent ; le conseiller de relance s'en sert
    (suggestion `inputs_lost`). Par défaut seulement avec la vraie prédiction : un `predict_live_fn` injecté (tests) n'écrit jamais dans la base.

    Disque plein (15/11/2026 : D: pleine, 2 984 prédictions tentées, 2 985 échecs « [Errno 28] »). `free_bytes_fn()` mesure l'espace libre, avant la
    première prédiction puis toutes les `check_every` : sous le seuil (réglage `predict_min_free_gb`, 5 Go) le cache de variables est évincé d'abord
    (jamais la base), puis, si la place manque encore, la boucle s'arrête avec UN message d'erreur (`RunSummary.aborted`). Une erreur « disque plein »
    sur une prédiction arrête aussi la boucle : les suivantes échoueraient de même, et elle n'est pas notée comme un échec du modèle. Mesure par défaut
    (disque de la racine de données) seulement avec la vraie prédiction, ou si `free_bytes_fn` est donnée, comme `track_failures`."""
    if track_failures is None:
        track_failures = predict_live_fn is None
    guard = free_bytes_fn is not None or predict_live_fn is None
    if free_bytes_fn is None:
        free_bytes_fn = data_root_free_bytes
    floor, check_every = min_free_bytes(), max(1, int(check_every))
    if predict_live_fn is None:
        from patrick import (
            predict as predict_module,  # chargé ici : tire sklearn / xgboost / le pipeline (~1 s)
        )

        predict_live_fn = partial(predict_module.predict_live, raw_cache={})

    summary = RunSummary()
    tracker = _open_failure_tracker(db_path) if track_failures else None
    for index, candidate in enumerate(candidates):
        if guard and index % check_every == 0:
            stop = _stop_for_low_space(free_bytes_fn, floor, len(candidates) - index)
            if stop:
                summary.aborted = stop
                break
        started_at = datetime.now(UTC).isoformat()
        logger.info("START target=%s horizon=%s run_id=%s", candidate.target, candidate.horizon,
                    candidate.run_id)
        try:
            detail = predict_live_fn(candidate.run_id, db_path=db_path)
            finished_at = datetime.now(UTC).isoformat()
            logger.info("OK    target=%s horizon=%s run_id=%s y_pred=%s y_proba=%s "
                        "n_outcomes_updated=%s", candidate.target, candidate.horizon, candidate.run_id,
                        detail.get("y_pred"), detail.get("y_proba"), detail.get("n_outcomes_updated"))
            outcome = PredictOutcome(candidate=candidate, ok=True, detail=detail,
                                     started_at=started_at, finished_at=finished_at)
            if tracker is not None:
                relaunch_stats.clear_live_failure(tracker, candidate.run_id)
        except Exception as exc:
            finished_at = datetime.now(UTC).isoformat()
            disk_full = _is_disk_full(exc)
            remaining = len(candidates) - index - 1
            if disk_full:
                summary.aborted = (f"Disque plein pendant la prédiction de {candidate.target} (horizon {candidate.horizon}) : {exc}. Les {remaining} "
                                   f"prédiction(s) suivante(s) échoueraient de même : arrêt. Libère de la place sur {_root_hint()} "
                                   "(`patrick storage evict --feature-cache-gb 100`, anciennes sauvegardes) puis relance.")
                logger.error(summary.aborted)                       # un seul message, pas une traceback par cible
            else:
                logger.exception("FAIL  target=%s horizon=%s run_id=%s", candidate.target,
                                 candidate.horizon, candidate.run_id)
            outcome = PredictOutcome(candidate=candidate, ok=False, error=str(exc),
                                     started_at=started_at, finished_at=finished_at)
            if tracker is not None and not disk_full:               # le disque n'est pas la faute du modèle : pas de note `live_failure`
                relaunch_stats.record_live_failure(tracker, candidate.run_id, str(exc))
        summary.add(outcome)
        if on_item is not None:
            on_item(outcome)
        if summary.aborted:
            break
    if tracker is not None:
        tracker.close()
    return summary


# --- Actualisation au lancement de l'app --------------------------------

_state_lock = threading.Lock()
_state: dict = {"running": False, "done": 0, "total": 0, "failed": 0, "judged": 0, "judged_right": 0,
                "started_at": None, "finished_at": None}
_started = False
_stop = threading.Event()

# Une app laissée ouverte plusieurs jours doit continuer à prédire et à juger : on regarde toutes les 30 min si le jour a changé.
REFRESH_CHECK_SECONDS = 30 * 60


def _fund_cells(db_path: str | None = None) -> set[tuple[str, int]]:
    """Les (cible, horizon) dont un fonds a besoin du signal du jour : les modèles que le pilote automatique de chaque stratégie
    retiendrait (sélection sans la limite de fraîcheur : c'est justement le signal à renouveler) et ceux des règles saisies à la main."""
    from patrick.fund import autopilot, selection, store

    conn = trackdb.connect(db_path)
    try:
        cells: set[tuple[str, int]] = set()
        for strategy in store.list_strategies(conn):
            stored = store.get_autopilot(conn, strategy["strategy_id"])
            if stored and stored.get("enabled"):
                policy = dataclasses.replace(autopilot.Settings.from_dict(stored.get("settings")).selection, fresh_days=365)
                cells |= {(m["target"], m["horizon"]) for m in selection.select_models(conn, policy)["selected"]}
        for (config_json,) in conn.execute("SELECT config_json FROM fund_rule").fetchall():
            trial_id = json.loads(config_json).get("trial_id")
            row = conn.execute("SELECT run.target, run.horizon FROM trial JOIN run ON run.run_id = trial.run_id "
                               "WHERE trial.trial_id = ?", (trial_id,)).fetchone() if trial_id else None
            if row:
                cells.add((row[0], row[1]))
        return cells
    finally:
        conn.close()


def split_for_funds(candidates: list[PredictCandidate], db_path: str | None = None) -> tuple[list[PredictCandidate], list[PredictCandidate]]:
    """`(prioritaires, autres)` : les candidats dont un fonds a besoin passent en premier, pour que son cycle ne dépende pas des quelque
    2 000 autres prédictions (environ 13 h : la tâche de nuit était interrompue avant le cycle). L'ordre d'origine est gardé dans chaque
    lot. Aucun fonds concerné, ou une panne du calcul : `([], candidates)`, l'appelant garde alors l'ordre d'avant (tout, puis le cycle)."""
    try:
        needed = _fund_cells(db_path)
    except Exception:
        logger.exception("modèles utiles aux fonds : ordre d'origine conservé")
        return [], list(candidates)
    first = [c for c in candidates if (c.target, c.horizon) in needed]
    return first, [c for c in candidates if (c.target, c.horizon) not in needed]


def run_autopilots(db_path: str | None = None) -> list[dict]:
    """Un cycle du pilote automatique des fonds pour chaque stratégie activée : sélection des modèles, règles, ordres
    échus. Avant lui, les règles saisies à la main qui suivent le champion passent au nouveau champion (un meilleur modèle
    entraîné entre-temps). À lancer APRÈS les prédictions du jour (il lit leurs signaux). Une erreur sur une stratégie est
    dans son compte rendu, jamais levée ; l'appelant protège le reste."""
    from patrick.fund import autopilot, systematic

    conn = trackdb.connect(db_path)
    try:
        try:
            for rolled in systematic.roll_to_champions(conn):
                if "error" in rolled:
                    logger.warning("règle %s : le champion n'a pas pu la remplacer (%s)", rolled["rule_id"], rolled["error"])
                else:
                    logger.info("règle %s remplacée par %s (nouveau champion, essai %s) : %s ordre(s) de l'ancien modèle supprimé(s)",
                                rolled["retired"], rolled["created"], rolled["trial_id"], rolled.get("purged_orders", 0))
        except Exception:
            logger.exception("suivi du champion en échec")        # n'empêche pas le cycle du pilote
        reports = autopilot.run_all(conn)
    finally:
        conn.close()
    for report in reports:
        if "error" in report:
            logger.error("autopilot %s : %s", report["strategy_id"], report["error"])
        else:
            logger.info("autopilot %s : %d modèle(s), %d ordre(s) placé(s), %d en attente", report["strategy_id"],
                        report["selected"], report["placed"], report["pending"])
    return reports


def refresh_metric_panel(db_path: str | None = None) -> dict | None:
    """Rattrape le panneau de métriques (ADR 0023 : AUC_dir, Brier_up, MCC_4cls, Acc_dir_p) des modèles évalués avant qu'il existe, à partir de
    leurs prédictions en base (`tracking/metric_backfill.py`, ajout seulement). Ne fait rien une fois tout rattrapé ; une panne est journalisée,
    jamais levée."""
    from patrick.tracking import metric_backfill

    try:
        conn = trackdb.connect(db_path)
        try:
            report = metric_backfill.backfill(conn)
        finally:
            conn.close()
    except Exception:
        logger.exception("panneau de métriques : rattrapage en échec")
        return None
    if report["n_rows"]:
        logger.info("panneau de métriques rattrapé : %d essai(s), %d mesure(s) ajoutée(s) en %.0f s", report["n_touched"], report["n_rows"],
                    report["seconds"])
    return report


def refresh_pooled_signal(db_path: str | None = None) -> dict | None:
    """Tient à jour l'AUC regroupée par paire cible-horizon (`tracking/pooled_signal.py`), lue par la Synthèse et les cartes de lots.
    À lancer après les prédictions du jour ; une panne est journalisée, jamais levée."""
    from patrick.tracking import pooled_signal

    try:
        conn = trackdb.connect(db_path)
        try:
            report = pooled_signal.refresh_if_stale(conn)
        finally:
            conn.close()
    except Exception:
        logger.exception("AUC regroupée : recalcul en échec")
        return None
    if report["refreshed"]:
        logger.info("AUC regroupée recalculée : %d paire(s), %d significative(s)", report["n_pairs"], report["n_significant"])
    return report


def write_weekly_report(db_path: str | None = None) -> str | None:
    """Écrit le rapport de la semaine écoulée s'il n'existe pas encore (`tracking/weekly_report.py`) ; renvoie son chemin. À lancer après
    les prédictions du jour ; une panne est journalisée, jamais levée."""
    from patrick.tracking import weekly_report

    try:
        conn = trackdb.connect(db_path)
        try:
            written = weekly_report.write_if_due(conn, folder=weekly_report.default_folder(db_path))
        finally:
            conn.close()
    except Exception:
        logger.exception("rapport hebdomadaire : écriture en échec")
        return None
    if written is not None:
        logger.info("rapport hebdomadaire écrit : %s", written)
    return str(written) if written is not None else None


def refresh_status() -> dict:
    """Copie de l'état d'avancement (affiché en tête de /predictions)."""
    with _state_lock:
        return dict(_state)


def refresh_due(last_day: date | None, today: date) -> bool:
    """Une actualisation par jour (UTC) : la première au lancement, puis dès que le jour a changé."""
    return last_day is None or today > last_day


def _refresh_once(db_path: str | None = None) -> None:
    conn = trackdb.connect(db_path)
    try:
        candidates = find_predictable_candidates(conn)
    finally:
        conn.close()
    with _state_lock:
        _state.update(running=True, done=0, failed=0, judged=0, judged_right=0, total=len(candidates),
                      started_at=datetime.now(UTC).isoformat(), finished_at=None)

    def _progress(outcome: PredictOutcome) -> None:
        detail = outcome.detail or {}
        with _state_lock:
            _state["done"] += 1
            _state["failed"] += 0 if outcome.ok else 1
            _state["judged"] += int(detail.get("n_outcomes_updated") or 0)
            _state["judged_right"] += int(detail.get("n_outcomes_right") or 0)

    first, rest = split_for_funds(candidates, db_path)
    if not first:
        first, rest = candidates, []             # aucun fonds concerné : tout, puis le cycle (l'ordre d'avant)
    try:
        run_daily_predictions(first, db_path=db_path, on_item=_progress)
        try:
            run_autopilots(db_path)              # les signaux utiles aux fonds sont écrits : le pilote automatique les traite sans attendre le reste
        except Exception:
            logger.exception("autopilot cycle failed")
        if rest:
            run_daily_predictions(rest, db_path=db_path, on_item=_progress)
        refresh_pooled_signal(db_path)
        refresh_metric_panel(db_path)
        write_weekly_report(db_path)
    finally:
        with _state_lock:
            _state.update(running=False, finished_at=datetime.now(UTC).isoformat())


def _refresh_loop(db_path: str | None = None) -> None:
    """Prédit et juge au lancement, puis une fois par jour tant que l'app reste ouverte. Une erreur est loggée, jamais
    propagée : la boucle continue et retente au prochain tour."""
    last_day: date | None = None
    while True:
        today = utc_today()
        if refresh_due(last_day, today):
            last_day = today
            try:
                _refresh_once(db_path)
            except Exception:
                logger.exception("live refresh failed")
                with _state_lock:
                    _state.update(running=False, finished_at=datetime.now(UTC).isoformat())
        if _stop.wait(REFRESH_CHECK_SECONDS):
            return


def start_background_refresh(db_path: str | None = None) -> None:
    """Lance en tâche de fond la boucle d'actualisation quotidienne (jamais deux ; désactivable par
    `PATRICK_LIVE_REFRESH=0`). Ne bloque ni le démarrage ni les pages."""
    global _started
    if os.environ.get("PATRICK_LIVE_REFRESH", "1") == "0":
        return
    with _state_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_refresh_loop, args=(db_path,), name="live-refresh", daemon=True).start()
