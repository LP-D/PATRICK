"""Priorités système : naviguer dans l'app d'abord, entraîner les modèles ensuite.

Un entraînement occupe tous les cœurs (processus de calcul en parallèle) et le disque pendant des heures ; l'app web, elle, a besoin d'un
peu de processeur à chaque page. Sans consigne les deux sont à égalité, et les pages ralentissent dès qu'un worker tourne.

- Le worker d'entraînement (`patrick worker`) passe en priorité BASSE à son démarrage (Windows : « sous la normale » ; Unix : nice 10), ses
  accès disque aussi. Les processus de calcul qu'il lance (joblib / loky) héritent de cette priorité.
- L'app web et ses tâches de fond liées aux pages (instantané de /predictions, signaux du jour, préchauffage des lots) restent à la priorité
  normale : dès que le processeur est disputé, la navigation passe devant l'entraînement. Aucune élévation au-dessus de la normale : l'app
  porte aussi la passe live, qui ne doit pas prendre le pas sur le reste du PC.
- Une passe live lancée DANS l'app (des heures de calcul) laisse la main à la navigation : avant chaque modèle elle attend qu'aucune page
  n'ait été demandée depuis quelques secondes (`wait_for_idle`), au plus `max_wait_s` par modèle pour avancer malgré tout.

Tout est facultatif et jamais bloquant : un refus du système (droits, plateforme) est ignoré, le travail continue à la priorité d'avant."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections.abc import Callable

import psutil

logger = logging.getLogger(__name__)

ENV_DISABLE = "PATRICK_NO_PRIORITY"               # =1 : ne touche à aucune priorité (diagnostic)
NAVIGATION_IDLE_S = 3.0                           # silence de navigation avant qu'une tâche de fond reprenne
NAVIGATION_MAX_WAIT_S = 30.0                      # attente maximale par tâche : elle avance même si on navigue sans arrêt

_nav_lock = threading.Lock()
_last_navigation = 0.0                            # horloge monotone de la dernière page demandée (0 = jamais)


def lower_for_training() -> dict:
    """Met CE processus (le worker d'entraînement) en priorité basse, processeur et disque. Renvoie ce qui a été fait, par exemple
    `{"cpu": "below_normal", "io": "low"}` ; une clé manque quand le système a refusé."""
    done: dict = {}
    if os.environ.get(ENV_DISABLE) == "1":
        return done
    try:
        proc = psutil.Process()
        if sys.platform == "win32":
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            done["cpu"] = "below_normal"
        elif proc.nice() < 10:
            proc.nice(10)
            done["cpu"] = "nice_10"
    except (psutil.Error, OSError, ValueError, AttributeError):
        logger.info("priorité processeur du worker inchangée", exc_info=True)
    try:
        proc = psutil.Process()
        if sys.platform == "win32":
            proc.ionice(psutil.IOPRIO_LOW)
            done["io"] = "low"
        elif hasattr(psutil, "IOPRIO_CLASS_BE"):
            proc.ionice(psutil.IOPRIO_CLASS_BE, 7)
            done["io"] = "best_effort_7"
    except (psutil.Error, OSError, ValueError, AttributeError):
        logger.info("priorité disque du worker inchangée", exc_info=True)
    return done


def note_navigation() -> None:
    """Une page vient d'être demandée : les tâches de fond de l'app lui laissent la main (`wait_for_idle`)."""
    global _last_navigation
    with _nav_lock:
        _last_navigation = time.monotonic()


def _is_navigation(scope: dict) -> bool:
    """Une page ou un fragment demandé par l'utilisateur ; pas les fichiers statiques ni les interrogations JSON (`/api/…`), qui reviennent
    toutes les quelques secondes sur une page ouverte et la feraient passer pour une navigation permanente."""
    if scope.get("type") != "http" or scope.get("method") != "GET":
        return False
    path = scope.get("path", "")
    return not path.startswith(("/static", "/api/"))


class NavigationActivity:
    """Middleware ASGI : note chaque navigation, sans rien changer à la requête ni à la réponse."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if _is_navigation(scope):
            note_navigation()
        await self.app(scope, receive, send)


def wait_for_idle(idle_s: float = NAVIGATION_IDLE_S, max_wait_s: float = NAVIGATION_MAX_WAIT_S,
                  sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> float:
    """Attend qu'aucune navigation n'ait eu lieu depuis `idle_s` secondes, au plus `max_wait_s` ; renvoie le temps attendu."""
    started = clock()
    while True:
        with _nav_lock:
            quiet_for = clock() - _last_navigation if _last_navigation else idle_s
        if quiet_for >= idle_s:
            return clock() - started
        waited = clock() - started
        if waited >= max_wait_s:
            return waited
        sleep(min(0.5, idle_s - quiet_for, max_wait_s - waited))
