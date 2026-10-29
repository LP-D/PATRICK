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
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial

from patrick.clock import utc_today
from patrick.tracking import db as trackdb

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
    """Agrégat succès/échecs d'une exécution complète (tous les candidats)."""
    outcomes: list[PredictOutcome] = field(default_factory=list)

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
    rows = conn.execute(
        "SELECT r.run_id, r.target, r.horizon, t.trial_id, t.artifact_path "
        "FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
        "WHERE r.status = 'done' AND t.artifact_path IS NOT NULL AND t.artifact_path != '' "
        "ORDER BY r.target, r.horizon, r.finished_at DESC"
    ).fetchall()

    latest_per_pair: dict[tuple[str, int], PredictCandidate] = {}
    for run_id, target, horizon, trial_id, artifact_path in rows:
        key = (target, horizon)
        if key in latest_per_pair:
            continue  # déjà gardé le plus récent (lignes triées DESC par finished_at)
        resolved = artifact_path if os.path.isabs(artifact_path) else os.path.join(base_dir, artifact_path)
        if not os.path.exists(resolved):
            logger.debug("Ignoré (fichier introuvable) : target=%s horizon=%s run_id=%s artifact_path=%s "
                         "(résolu: %s)", target, horizon, run_id, artifact_path, resolved)
            continue
        latest_per_pair[key] = PredictCandidate(target=target, horizon=horizon, run_id=run_id,
                                                  trial_id=trial_id, artifact_path=artifact_path)
    return list(latest_per_pair.values())


def run_daily_predictions(candidates: list[PredictCandidate], predict_live_fn=None,
                           db_path: str | None = None, on_item=None) -> RunSummary:
    """Appelle `predict_live_fn(candidate.run_id, db_path=db_path)` pour
    chaque candidat, un par un. Une exception sur UN item ne doit JAMAIS
    interrompre le traitement des suivants -- try/except par item, erreur
    loggée, boucle continue.

    `predict_live_fn` est injectable (mocké dans les tests) ; par défaut,
    `patrick.predict.predict_live` avec un cache de téléchargement partagé
    entre les runs de même objectif/univers. `on_item(outcome)` : rappel de
    progression (affichage de l'avancement dans l'app)."""
    if predict_live_fn is None:
        from patrick import (
            predict as predict_module,  # chargé ici : tire sklearn / xgboost / le pipeline (~1 s)
        )

        predict_live_fn = partial(predict_module.predict_live, raw_cache={})

    summary = RunSummary()
    for candidate in candidates:
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
        except Exception as exc:
            finished_at = datetime.now(UTC).isoformat()
            logger.exception("FAIL  target=%s horizon=%s run_id=%s", candidate.target,
                             candidate.horizon, candidate.run_id)
            outcome = PredictOutcome(candidate=candidate, ok=False, error=str(exc),
                                     started_at=started_at, finished_at=finished_at)
        summary.add(outcome)
        if on_item is not None:
            on_item(outcome)
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
                    logger.info("règle %s remplacée par %s (nouveau champion, essai %s)", rolled["retired"], rolled["created"],
                                rolled["trial_id"])
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
