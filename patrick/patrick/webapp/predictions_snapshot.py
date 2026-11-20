"""Instantané du tableau de `/predictions` : calculé en dehors de l'ouverture de la page, relu en quelques dizaines de ms.

Sur la vraie base (76 Go, ~25 millions de prédictions, 500+ actifs) le tableau demande ~3 minutes de lecture. L'ancienne
mémoïsation (`tracking/memo.py`) le gardait 5 minutes en mémoire de processus : chaque ouverture de page après ce délai, chaque
redémarrage, chaque run terminé le recalculait pendant que la page attendait.

Maintenant :

- le résultat (tableau directionnel, tableau alpha, avantage live de la vue « Par horizon ») est écrit dans un fichier à côté de la
  base (`predictions_snapshot.pkl`, remplacé atomiquement) ; la page le lit toujours, même vieux, et ne calcule JAMAIS à
  l'ouverture ;
- il est recalculé en tâche de fond : à la fin de chaque actualisation live, à la fin de la tâche de nuit
  (`scripts/daily_predict.py`), au démarrage de l'app s'il est absent ou vieux de plus de 24 h, et quand de nouveaux signaux
  live sont apparus depuis (au plus une fois toutes les 30 min, jamais pendant une actualisation) ;
- un seul calcul à la fois : une demande reçue pendant un calcul en demande un second juste après (les données ont bougé), pas deux
  en parallèle ;
- premier calcul (aucun instantané) : la page attend quelques secondes (instantané sur une petite base), sinon elle affiche « le
  tableau se prépare » et se rafraîchit toute seule.

Ce qui dépend de l'heure (marché ouvert / fermé, « marché fermé » d'une case) n'est pas figé dans l'instantané : `app.py` le recalcule à
chaque affichage (`_refresh_time_dependent`)."""
from __future__ import annotations

import contextlib
import logging
import os
import pickle
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from patrick.clock import utc_now
from patrick.tracking import db as trackdb

logger = logging.getLogger("patrick.predictions_snapshot")

VERSION = 1                                  # à incrémenter quand la forme du tableau change : l'ancien instantané est alors ignoré
MAX_AGE = timedelta(hours=24)                # au-delà, recalcul même sans nouveau signal
MIN_INTERVAL = timedelta(minutes=30)         # entre deux recalculs déclenchés par de nouveaux signaux
FIRST_BUILD_WAIT_S = 20.0                    # attente de la page quand il n'existe encore aucun instantané

_lock = threading.Lock()
_states: dict[str, dict] = {}                # chemin de l'instantané -> état du recalcul (une base de test n'influe pas sur une autre)
_loaded: dict[str, tuple[int, dict]] = {}    # chemin -> (mtime_ns, instantané déjà lu)


def _state_of(db_path: str | None) -> dict:
    """État du recalcul de CETTE base ; à lire et modifier sous `_lock`."""
    return _states.setdefault(str(snapshot_path(db_path)),
                              {"running": False, "started_at": None, "finished_at": None, "error": None, "again": False})


def snapshot_path(db_path: str | None = None) -> Path:
    """L'instantané vit à côté de la base qu'il résume : une base de test a le sien, jamais mélangé avec celui de la vraie base."""
    return Path(db_path or trackdb.default_db_path()).with_name("predictions_snapshot.pkl")


def status(db_path: str | None = None) -> dict:
    with _lock:
        return dict(_state_of(db_path))


def live_marker(conn) -> tuple:
    """Ce qui dit que de nouveaux signaux live existent : leur nombre et la date du dernier (lecture O(1) sur la vraie base)."""
    return tuple(conn.execute("SELECT COUNT(*), MAX(ts) FROM prediction WHERE split = 'live'").fetchone())


def load(db_path: str | None = None) -> dict | None:
    """L'instantané du disque (relu seulement si le fichier a changé), ou None s'il n'existe pas / est d'une autre version."""
    path = snapshot_path(db_path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = str(path)
    with _lock:
        hit = _loaded.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            payload = pickle.load(fh)
    except Exception:
        logger.exception("instantané illisible : %s", path)
        return None
    if not isinstance(payload, dict) or payload.get("version") != VERSION:
        return None
    with _lock:
        _loaded[key] = (mtime, payload)
    return payload


def save(payload: dict, db_path: str | None = None) -> None:
    """Écriture atomique : un lecteur voit l'ancien instantané ou le nouveau, jamais un fichier à moitié écrit."""
    path = snapshot_path(db_path)
    fd, tmp = tempfile.mkstemp(prefix="predictions_snapshot.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        for attempt in range(5):             # Windows : le remplacement échoue si un lecteur tient le fichier à cet instant
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def compute(db_path: str | None = None) -> dict:
    """Calcule tout ce que lisent les vues de `/predictions` (lent : minutes sur la vraie base). Jamais appelé à l'ouverture d'une page."""
    from patrick.webapp import app as webapp  # importé ici : app.py importe ce module
    from patrick.webapp import live_edge_view

    conn = trackdb.connect(db_path)
    try:
        marker = live_marker(conn)           # lu AVANT le calcul : un signal arrivé pendant le calcul déclenchera un nouveau tour
    finally:
        conn.close()
    directional = webapp._predictions_overview("directional", db_path=db_path)
    alpha = webapp._predictions_overview("alpha", db_path=db_path)
    conn = trackdb.connect(db_path)
    try:
        edge = live_edge_view.compute_edge(conn, directional)
    finally:
        conn.close()
    return {"version": VERSION, "computed_at": utc_now().isoformat(), "live_marker": marker,
            "directional": directional, "alpha": alpha, "edge": edge}


def refresh_sync(db_path: str | None = None) -> dict:
    """Calcule et écrit l'instantané dans le processus appelant (tâche de nuit, tests)."""
    started = time.monotonic()
    payload = compute(db_path)
    save(payload, db_path)
    logger.info("instantané de /predictions recalculé en %.0f s", time.monotonic() - started)
    return payload


def _run(db_path: str | None) -> None:
    try:
        while True:
            with _lock:
                _state_of(db_path).update(running=True, started_at=utc_now().isoformat(), error=None, again=False)
            try:
                refresh_sync(db_path)
            except Exception as exc:
                logger.exception("recalcul de l'instantané de /predictions échoué")
                with _lock:
                    _state_of(db_path)["error"] = str(exc)
            with _lock:
                state = _state_of(db_path)
                state["finished_at"] = utc_now().isoformat()
                if not state["again"]:
                    state["running"] = False
                    return
    except BaseException:
        with _lock:
            _state_of(db_path)["running"] = False
        raise


def request_refresh(db_path: str | None = None, rerun_if_running: bool = True) -> bool:
    """Demande un recalcul en tâche de fond. Un calcul déjà en cours en fera un second juste après (les données ont bougé), sauf
    `rerun_if_running=False` (ouverture d'une page : le calcul en cours suffit). Renvoie True si un calcul a démarré ou est en
    attente de rejouer."""
    with _lock:
        state = _state_of(db_path)
        if state["running"]:
            if rerun_if_running:
                state["again"] = True
            return rerun_if_running
        state["running"] = True
    threading.Thread(target=_run, args=(db_path,), name="predictions-snapshot", daemon=True).start()
    return True


def needs_refresh(payload: dict | None, marker_now: tuple, now: datetime, live_running: bool = False) -> bool:
    """Faut-il recalculer ? Oui sans instantané ou s'il a plus de 24 h ; oui aussi si de nouveaux signaux live sont apparus depuis,
    au plus une fois toutes les 30 min et jamais pendant une actualisation live (elle déclenche elle-même un recalcul à sa fin)."""
    if payload is None:
        return True
    age = now - datetime.fromisoformat(payload["computed_at"])
    if age > MAX_AGE:
        return True
    return tuple(payload.get("live_marker") or ()) != tuple(marker_now) and age > MIN_INTERVAL and not live_running


def refresh_if_stale_sync(db_path: str | None = None) -> bool:
    """Tâche de nuit : recalcule l'instantané dans CE processus s'il manque, s'il a plus de 24 h ou si des signaux live sont apparus depuis
    (le tableau est alors prêt le matin). Renvoie True s'il a été recalculé."""
    conn = trackdb.connect(db_path)
    try:
        marker = live_marker(conn)
    finally:
        conn.close()
    payload = load(db_path)
    if payload is not None and tuple(payload.get("live_marker") or ()) == tuple(marker)             and utc_now() - datetime.fromisoformat(payload["computed_at"]) <= MAX_AGE:
        return False
    refresh_sync(db_path)
    return True


def get(db_path: str | None = None, live_running: bool = False, wait_first: float = 0.0) -> dict | None:
    """L'instantané à afficher, sans jamais bloquer la page sur un recalcul : le dernier connu, même vieux, et un recalcul en
    tâche de fond s'il en faut un. Sans aucun instantané, attend jusqu'à `wait_first` secondes le premier calcul puis renvoie ce
    qu'il a (None si pas fini : la page affiche « le tableau se prépare »)."""
    payload = load(db_path)
    conn = trackdb.connect(db_path)
    try:
        marker = live_marker(conn)
    finally:
        conn.close()
    if needs_refresh(payload, marker, utc_now(), live_running):
        request_refresh(db_path, rerun_if_running=False)
    if payload is None and wait_first > 0:
        deadline = time.monotonic() + wait_first
        while time.monotonic() < deadline:
            payload = load(db_path)
            if payload is not None:
                break
            time.sleep(0.1)
    return payload
