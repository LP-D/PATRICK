"""Instantané du tableau de `/predictions` : calculé en dehors de l'ouverture de la page, relu en quelques dizaines de ms.

Sur la vraie base (76 Go, ~25 millions de prédictions, 500+ actifs) le tableau demande ~2 à 3 minutes de lecture. C'est une vue du cache
persistant commun (`webapp/view_cache.py`, qui décrit la politique : lu d'abord, recalculé ensuite, un seul calcul à la fois, avancement
lisible par la barre de chargement). Ici seulement ce qui est propre au tableau :

- le résultat (tableau directionnel, tableau alpha, avantage live de la vue « Par horizon ») ;
- le signal qui dit qu'il faut recalculer : de nouveaux signaux live (`live_marker`) ;
- recalcul à la fin de chaque actualisation live, à la fin de la tâche de nuit (`scripts/daily_predict.py`) et au démarrage de l'app s'il
  manque ou date de plus de 24 h ;
- ce qui dépend de l'heure (marché ouvert / fermé) n'est pas figé ici : `app.py` le recalcule à chaque affichage.

Les fonctions de ce module gardent leur forme d'origine (`get`, `load`, `refresh_sync`, `request_refresh`…) : elles renvoient un dict
`{version, computed_at, live_marker, directional, alpha, edge}`."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from patrick.webapp import view_cache
from patrick.webapp.view_cache import Snapshot

VERSION = 2                                  # à incrémenter quand la forme du tableau change : l'ancien instantané est alors ignoré
MAX_AGE = timedelta(hours=24)                # au-delà, recalcul même sans nouveau signal
MIN_INTERVAL = timedelta(minutes=30)         # entre deux recalculs déclenchés par de nouveaux signaux
FIRST_BUILD_WAIT_S = view_cache.FIRST_BUILD_WAIT_S

_META = ("version", "computed_at", "live_marker")
# Durée attendue de chaque étape, en secondes, avant d'avoir mesuré un premier calcul (profil de la vraie base).
PLAN = {"Derniers signaux": 25.0, "Mesures de direction": 55.0, "Fiabilité live": 3.0, "Suivi par mouvement": 3.0,
        "Dérive et métriques": 2.0, "Assemblage du tableau": 3.0, "Modèles alpha": 1.0, "Avantage par horizon": 6.0}


def live_marker(conn) -> tuple:
    """Ce qui dit que de nouveaux signaux live existent : leur nombre et la date du dernier (lecture O(1) sur la vraie base)."""
    return tuple(conn.execute("SELECT COUNT(*), MAX(ts) FROM prediction WHERE split = 'live'").fetchone())


def _compute_for_view(db_path, key, progress) -> dict:
    return compute(db_path)


VIEW = view_cache.CachedView("predictions", _compute_for_view, version=VERSION, max_age=MAX_AGE, min_interval=MIN_INTERVAL,
                             marker=live_marker, legacy_filename="predictions_snapshot.pkl")


def _merged(snap: Snapshot | None) -> dict | None:
    if snap is None:
        return None
    return {**snap.value, "version": VIEW.version, "computed_at": snap.computed_at.isoformat(), "live_marker": snap.marker}


def snapshot_path(db_path: str | None = None) -> Path:
    """L'instantané vit à côté de la base qu'il résume : une base de test a le sien, jamais mélangé avec celui de la vraie base."""
    return VIEW.path(None, db_path)


def status(db_path: str | None = None) -> dict:
    return VIEW.status(None, db_path)


def load(db_path: str | None = None) -> dict | None:
    """L'instantané du disque (relu seulement si le fichier a changé), ou None s'il n'existe pas / est d'une autre version."""
    return _merged(VIEW.load(None, db_path))


def save(payload: dict, db_path: str | None = None) -> None:
    VIEW.save(Snapshot({k: v for k, v in payload.items() if k not in _META}, datetime.fromisoformat(payload["computed_at"]),
                       tuple(payload.get("live_marker") or ())), None, db_path)


def compute(db_path: str | None = None) -> dict:
    """Calcule tout ce que lisent les vues de `/predictions` (lent : minutes sur la vraie base). Jamais appelé à l'ouverture d'une page."""
    from patrick.tracking import db as trackdb
    from patrick.webapp import app as webapp  # importé ici : app.py importe ce module
    from patrick.webapp import live_edge_view

    progress = view_cache.current_progress()
    progress.plan(PLAN)
    directional = webapp._predictions_overview("directional", db_path=db_path, report=True)
    progress.step("Modèles alpha")
    alpha = webapp._predictions_overview("alpha", db_path=db_path)
    progress.step("Avantage par horizon")
    conn = trackdb.connect(db_path)
    try:
        edge = live_edge_view.compute_edge(conn, directional)
    finally:
        conn.close()
    return {"directional": directional, "alpha": alpha, "edge": edge}


def refresh_sync(db_path: str | None = None) -> dict:
    """Calcule et écrit l'instantané dans le processus appelant (tâche de nuit, tests)."""
    return _merged(VIEW.refresh_sync(None, db_path))


def request_refresh(db_path: str | None = None, rerun_if_running: bool = True) -> bool:
    """Demande un recalcul en tâche de fond. Un calcul déjà en cours en fera un second juste après (les données ont bougé), sauf
    `rerun_if_running=False` (ouverture d'une page : le calcul en cours suffit)."""
    return VIEW.request_refresh(None, db_path, rerun_if_running)


def needs_refresh(payload: dict | None, marker_now: tuple, now: datetime, live_running: bool = False) -> bool:
    """Faut-il recalculer ? Oui sans instantané ou s'il a plus de 24 h ; oui aussi si de nouveaux signaux live sont apparus depuis, au plus
    une fois toutes les 30 min et jamais pendant une actualisation live (elle déclenche elle-même un recalcul à sa fin)."""
    snap = None if payload is None else Snapshot(None, datetime.fromisoformat(payload["computed_at"]), tuple(payload.get("live_marker") or ()))
    return VIEW.needs_refresh(snap, marker_now, now, live_running)


def refresh_if_stale_sync(db_path: str | None = None) -> bool:
    """Tâche de nuit : recalcule dans CE processus si l'instantané manque, est trop vieux ou si des signaux live sont apparus depuis."""
    return VIEW.refresh_if_stale_sync(None, db_path)


def get(db_path: str | None = None, live_running: bool = False, wait_first: float = 0.0) -> dict | None:
    """L'instantané à afficher, sans jamais bloquer la page sur un recalcul : le dernier connu, même vieux, et un recalcul en tâche de fond
    s'il en faut un. Sans aucun instantané, attend jusqu'à `wait_first` secondes le premier calcul puis renvoie ce qu'il a (None si pas
    fini : la page affiche « le tableau se prépare » et la barre de chargement dit où en est le calcul)."""
    return _merged(VIEW.get(None, db_path, live_running=live_running, wait_first=wait_first))
