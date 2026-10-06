"""Actualisation des prédictions live (une par couple actif x horizon).

Partagé par `scripts/daily_predict.py` (planificateur de tâches) et par le
démarrage de l'app web : à chaque lancement, chaque modèle déjà entraîné
rejoue `predict_live` sur les données du jour -- le tableau /predictions
montre donc le signal du jour, pas celui de l'entraînement.

Jour de marché fermé : `predict_live` lit la dernière barre de la série de
l'actif lui-même. Pas de nouvelle barre = pas de nouvelle ligne (rien n'est
réécrit), et le signal affiché garde la date de sa dernière séance.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial

from patrick import predict as predict_module
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
        predict_live_fn = partial(predict_module.predict_live, raw_cache={})

    summary = RunSummary()
    for candidate in candidates:
        started_at = datetime.now(timezone.utc).isoformat()
        logger.info("START target=%s horizon=%s run_id=%s", candidate.target, candidate.horizon,
                    candidate.run_id)
        try:
            detail = predict_live_fn(candidate.run_id, db_path=db_path)
            finished_at = datetime.now(timezone.utc).isoformat()
            logger.info("OK    target=%s horizon=%s run_id=%s y_pred=%s y_proba=%s "
                        "n_outcomes_updated=%s", candidate.target, candidate.horizon, candidate.run_id,
                        detail.get("y_pred"), detail.get("y_proba"), detail.get("n_outcomes_updated"))
            outcome = PredictOutcome(candidate=candidate, ok=True, detail=detail,
                                     started_at=started_at, finished_at=finished_at)
        except Exception as exc:
            finished_at = datetime.now(timezone.utc).isoformat()
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
_state: dict = {"running": False, "done": 0, "total": 0, "failed": 0,
                "started_at": None, "finished_at": None}
_started = False


def refresh_status() -> dict:
    """Copie de l'état d'avancement (affiché en tête de /predictions)."""
    with _state_lock:
        return dict(_state)


def _refresh_once(db_path: str | None = None) -> None:
    conn = trackdb.connect(db_path)
    try:
        candidates = find_predictable_candidates(conn)
    finally:
        conn.close()
    with _state_lock:
        _state.update(running=True, done=0, failed=0, total=len(candidates),
                      started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)

    def _progress(outcome: PredictOutcome) -> None:
        with _state_lock:
            _state["done"] += 1
            _state["failed"] += 0 if outcome.ok else 1

    try:
        run_daily_predictions(candidates, db_path=db_path, on_item=_progress)
    finally:
        with _state_lock:
            _state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat())


def start_background_refresh(db_path: str | None = None) -> None:
    """Lance UNE actualisation en tâche de fond au démarrage de l'app (jamais
    deux ; désactivable par `PATRICK_LIVE_REFRESH=0`). Ne bloque ni le
    démarrage ni les pages : une erreur est loggée, jamais propagée."""
    global _started
    if os.environ.get("PATRICK_LIVE_REFRESH", "1") == "0":
        return
    with _state_lock:
        if _started:
            return
        _started = True

    def _run() -> None:
        try:
            _refresh_once(db_path)
        except Exception:
            logger.exception("live refresh failed")
            with _state_lock:
                _state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat())

    threading.Thread(target=_run, name="live-refresh", daemon=True).start()
