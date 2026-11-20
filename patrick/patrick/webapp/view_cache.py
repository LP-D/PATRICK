"""Cache persistant « lu d'abord, recalculé ensuite » des vues lourdes de l'application, avec l'avancement de leur recalcul.

Plusieurs pages demandent des dizaines de secondes de calcul sur la vraie base (76 Go) : l'accueil 25 s, les fonds 15 à 38 s, l'analyse 6 s, les
pages de classes d'actifs 8 s, le portefeuille 3 s. L'ancienne mémoïsation (`tracking/memo.py`) les gardait 5 minutes en mémoire de processus :
chaque ouverture après ce délai, chaque redémarrage, chaque run terminé les recalculait pendant que la page attendait.

Une `CachedView` écrit son résultat dans un fichier à côté de la base (remplacé atomiquement) et la page le relit TOUJOURS, même vieux :

- recalcul en tâche de fond quand il a plus de `max_age`, ou quand la base a bougé (`marker`, au plus une fois par `min_interval`) ;
- un seul calcul à la fois par vue et par clé : une demande reçue pendant un calcul en demande un second juste après si les données ont bougé,
  jamais deux en parallèle ;
- `hard_marker` (facultatif) : l'état que l'UTILISATEUR modifie lui-même (un fonds, un ordre). S'il a changé depuis le calcul, l'instantané ne
  vaut plus : on le recalcule tout de suite, la page attend, pour qu'on voie sa propre modification ;
- aucun instantané (premier calcul) : la page attend quelques secondes (instantané sur une petite base), sinon elle affiche « se prépare » ;
- l'avancement du calcul (étape, pourcentage) est lu par `/api/refresh-status` et dessiné par la barre de chargement de la page. Le pourcentage
  pondère chaque étape par sa durée au dernier calcul (mémorisée dans l'instantané), pas par leur nombre.

Un calcul peut aussi tourner dans un autre processus (tâche de nuit, `refresh_sync`) : il écrit le même fichier."""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import pickle
import tempfile
import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from patrick.clock import utc_now
from patrick.tracking import db as trackdb

logger = logging.getLogger("patrick.view_cache")

FIRST_BUILD_WAIT_S = 20.0                    # attente de la page quand il n'existe encore aucun instantané
HARD_WAIT_S = 180.0                          # attente de la page quand l'état modifié par l'utilisateur a changé


@dataclass
class Snapshot:
    value: Any
    computed_at: datetime
    marker: tuple = ()
    hard_marker: tuple = ()
    timings: dict[str, float] = field(default_factory=dict)
    duration: float = 0.0                    # secondes du calcul : sert à estimer l'avancement du suivant


class Progress:
    """Passé à `compute` : `plan` déclare les étapes (durée attendue en secondes, remplacée par la durée du dernier calcul), `step` annonce la
    suivante. Sans plan, l'avancement est estimé par le temps écoulé sur la durée du dernier calcul (indéterminé au tout premier)."""

    def __init__(self, state: dict, last_timings: dict[str, float]):
        self._state, self._last = state, last_timings
        self._current: str | None = None
        self._started = time.monotonic()
        self.timings: dict[str, float] = {}

    def plan(self, steps: dict[str, float]) -> None:
        plan = {label: (max(float(self._last[label]), 0.01) if label in self._last else (float(default) or 1.0)) for label, default in steps.items()}
        with _lock:
            self._state.update(plan=plan, done=0.0, current=None)

    def step(self, label: str) -> None:
        now = time.monotonic()
        if self._current is not None:
            self.timings[self._current] = now - self._started
        self._current, self._started = label, now
        with _lock:
            plan = self._state["plan"]
            self._state.update(current=label, step_started=now, done=sum(w for k, w in plan.items() if k in self.timings))

    def finish(self) -> None:
        if self._current is not None:
            self.timings[self._current] = time.monotonic() - self._started
            self._current = None


class _NullProgress:
    """Quand rien n'attend l'avancement (la fonction est appelée hors d'une vue) : tout est accepté, rien n'est gardé."""

    def plan(self, steps: dict[str, float]) -> None: ...
    def step(self, label: str) -> None: ...
    def finish(self) -> None: ...


_active = threading.local()


def current_progress() -> Progress | _NullProgress:
    """L'avancement du calcul de vue qui tourne dans CE fil, ou un objet qui ne fait rien : une fonction de calcul partagée entre une vue et une
    page (`_predictions_overview`) annonce ses étapes sans savoir qui l'appelle."""
    return getattr(_active, "progress", None) or _NullProgress()


def _fraction(state: dict, now: float) -> float | None:
    """Avancement 0..1 d'un calcul en cours, lissé : étapes pondérées par leur durée au dernier calcul, et l'étape courante avance avec le
    temps (sans dépasser 95 % de son poids). None = indéterminé (premier calcul d'une vue sans plan)."""
    plan = state["plan"]
    if plan:
        total = sum(plan.values()) or 1.0
        weight = plan.get(state["current"], 0.0)
        inside = min(0.95, (now - state["step_started"]) / weight) * weight if weight and state["current"] else 0.0
        return min(0.99, (state["done"] + inside) / total)
    if state["expected_s"]:
        return min(0.95, (now - state["started_mono"]) / state["expected_s"])
    return None


_lock = threading.Lock()
_loaded: dict[str, tuple[int, Snapshot]] = {}      # chemin -> (mtime_ns, instantané déjà lu)
_states: dict[str, dict] = {}                      # chemin -> état du recalcul


def _new_state(name: str = "", key: Hashable = None, base: str = "") -> dict:
    return {"name": name, "key": None if key is None else str(key), "base": base, "running": False, "plan": {}, "done": 0.0, "current": None,
            "step_started": 0.0, "started_mono": 0.0, "expected_s": None, "started_at": None, "finished_at": None,
            "error": None, "again": False}


def _public(state: dict, now: float) -> dict:
    """Ce que `/api/refresh-status` dit d'un calcul : nom, clé, en cours ou non, étape courante, avancement (None = indéterminé)."""
    return {"name": state["name"], "key": state["key"], "running": state["running"], "label": state["current"],
            "fraction": _fraction(state, now) if state["running"] else None, "started_at": state["started_at"],
            "finished_at": state["finished_at"], "error": state["error"]}


def all_status(db_path: str | None = None) -> list[dict]:
    """L'état de tous les calculs de CETTE base connus de ce processus (en cours, ou terminés depuis le démarrage)."""
    base = str(Path(db_path or trackdb.default_db_path()).parent)
    now = time.monotonic()
    with _lock:
        return [_public(state, now) for state in _states.values() if state["base"] == base]


class CachedView:
    def __init__(self, name: str, compute: Callable[[str | None, Hashable, Progress], Any], *, version: int = 1,
                 max_age: timedelta = timedelta(hours=6), min_interval: timedelta = timedelta(minutes=30),
                 marker: Callable[[Any], tuple] | None = None, hard_marker: Callable[[Any], tuple] | None = None,
                 legacy_filename: str | None = None):
        self.name, self.compute, self.version = name, compute, version
        self.max_age, self.min_interval = max_age, min_interval
        self.marker_fn, self.hard_marker_fn = marker, hard_marker
        self.legacy_filename = legacy_filename

    # ------------------------------------------------------------------ fichier

    def path(self, key: Hashable = None, db_path: str | None = None) -> Path:
        base = Path(db_path or trackdb.default_db_path()).parent
        if key is None and self.legacy_filename:
            return base / self.legacy_filename
        digest = hashlib.blake2s(repr(key).encode("utf-8"), digest_size=4).hexdigest()
        return base / "views" / f"{self.name}--{digest}.pkl"

    def load(self, key: Hashable = None, db_path: str | None = None) -> Snapshot | None:
        path = self.path(key, db_path)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None
        cache_key = f"{path}|v{self.version}"       # la version fait partie de la clé : une vue dont la forme change ne relit pas l'ancien
        with _lock:
            hit = _loaded.get(cache_key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        try:
            with open(path, "rb") as fh:
                raw = pickle.load(fh)
        except Exception:
            logger.exception("instantané illisible : %s", path)
            return None
        if not isinstance(raw, dict) or raw.get("version") != self.version or "value" not in raw:
            return None
        snap = Snapshot(raw["value"], datetime.fromisoformat(raw["computed_at"]), tuple(raw.get("marker") or ()),
                        tuple(raw.get("hard_marker") or ()), dict(raw.get("timings") or {}),
                        float(raw.get("duration") or 0.0))
        with _lock:
            _loaded[cache_key] = (mtime, snap)
        return snap

    def save(self, snap: Snapshot, key: Hashable = None, db_path: str | None = None) -> None:
        path = self.path(key, db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = {"version": self.version, "computed_at": snap.computed_at.isoformat(), "marker": snap.marker,
               "hard_marker": snap.hard_marker, "timings": snap.timings, "duration": snap.duration, "value": snap.value}
        fd, tmp = tempfile.mkstemp(prefix=f"{self.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                pickle.dump(raw, fh, protocol=pickle.HIGHEST_PROTOCOL)
            for attempt in range(5):          # Windows : le remplacement échoue si un lecteur tient le fichier à cet instant
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

    # ------------------------------------------------------------------ état et avancement

    def _state(self, key: Hashable, db_path: str | None) -> dict:
        """État du recalcul de CETTE base et de cette clé ; à lire et modifier sous `_lock`."""
        base = str(Path(db_path or trackdb.default_db_path()).parent)
        return _states.setdefault(str(self.path(key, db_path)), _new_state(self.name, key, base))

    def status(self, key: Hashable = None, db_path: str | None = None) -> dict:
        with _lock:
            out = _public(self._state(key, db_path), time.monotonic())
        snap = self.load(key, db_path)
        out["computed_at"] = None if snap is None else snap.computed_at.isoformat()
        return out

    # ------------------------------------------------------------------ calcul

    def markers(self, db_path: str | None = None) -> tuple[tuple, tuple]:
        if self.marker_fn is None and self.hard_marker_fn is None:
            return (), ()
        conn = trackdb.connect(db_path)
        try:
            soft = tuple(self.marker_fn(conn)) if self.marker_fn else ()
            hard = tuple(self.hard_marker_fn(conn)) if self.hard_marker_fn else ()
        finally:
            conn.close()
        return soft, hard

    def _compute_and_save(self, key: Hashable, db_path: str | None) -> Snapshot:
        started = time.monotonic()
        previous = self.load(key, db_path)
        with _lock:
            state = self._state(key, db_path)
            state.update(running=True, plan={}, done=0.0, current=None, started_mono=started, started_at=utc_now().isoformat(),
                         expected_s=(previous.duration if previous and previous.duration else None), error=None)
        progress = Progress(state, previous.timings if previous else {})
        _active.progress = progress
        try:
            soft, hard = self.markers(db_path)          # lus AVANT le calcul : un changement pendant le calcul déclenchera un autre tour
            value = self.compute(db_path, key, progress)
            progress.finish()
            duration = time.monotonic() - started
            snap = Snapshot(value, utc_now(), soft, hard, dict(progress.timings), duration)
            self.save(snap, key, db_path)
            logger.info("vue %s recalculée en %.0f s", self.name, duration)
            return snap
        finally:
            _active.progress = None
            with _lock:
                state.update(current=None, finished_at=utc_now().isoformat())

    def refresh_sync(self, key: Hashable = None, db_path: str | None = None) -> Snapshot:
        """Calcule et écrit l'instantané dans le processus appelant (tâche de nuit, tests)."""
        try:
            return self._compute_and_save(key, db_path)
        finally:
            with _lock:
                self._state(key, db_path)["running"] = False

    def _run(self, key: Hashable, db_path: str | None) -> None:
        """Fil de fond : un calcul, puis un autre si une demande est arrivée pendant le premier ; `running` reste vrai entre les deux."""
        try:
            while True:
                with _lock:
                    self._state(key, db_path)["again"] = False
                try:
                    self._compute_and_save(key, db_path)
                except Exception as exc:
                    logger.exception("recalcul de la vue %s échoué", self.name)
                    with _lock:
                        self._state(key, db_path)["error"] = str(exc)
                with _lock:
                    state = self._state(key, db_path)
                    if not state["again"]:
                        state["running"] = False
                        return
        except BaseException:
            with _lock:
                self._state(key, db_path)["running"] = False
            raise

    def request_refresh(self, key: Hashable = None, db_path: str | None = None, rerun_if_running: bool = True) -> bool:
        """Demande un recalcul en tâche de fond. Un calcul déjà en cours en fera un second juste après, sauf `rerun_if_running=False`
        (ouverture d'une page : le calcul en cours suffit)."""
        with _lock:
            state = self._state(key, db_path)
            if state["running"]:
                if rerun_if_running:
                    state["again"] = True
                return rerun_if_running
            state["running"] = True
        threading.Thread(target=self._run, args=(key, db_path), name=f"view-{self.name}", daemon=True).start()
        return True

    # ------------------------------------------------------------------ lecture

    def needs_refresh(self, snap: Snapshot | None, marker_now: tuple, now: datetime, live_running: bool = False) -> bool:
        """Oui sans instantané, ou s'il a plus de `max_age`, ou si la base a bougé depuis (au plus une fois par `min_interval`, jamais pendant
        une actualisation live : elle déclenche elle-même un recalcul à sa fin)."""
        if snap is None:
            return True
        age = now - snap.computed_at
        if age > self.max_age:
            return True
        return snap.marker != tuple(marker_now) and age > self.min_interval and not live_running

    def refresh_if_stale_sync(self, key: Hashable = None, db_path: str | None = None) -> bool:
        """Tâche de nuit : recalcule dans CE processus si l'instantané manque, est trop vieux ou si la base a bougé. True s'il a été recalculé."""
        soft, hard = self.markers(db_path)
        snap = self.load(key, db_path)
        if snap is not None and snap.marker == soft and snap.hard_marker == hard and utc_now() - snap.computed_at <= self.max_age:
            return False
        self.refresh_sync(key, db_path)
        return True

    def get(self, key: Hashable = None, db_path: str | None = None, live_running: bool = False,
            wait_first: float = 0.0, hard_wait: float = 0.0) -> Snapshot | None:
        """L'instantané à afficher, sans jamais bloquer la page sur un recalcul de confort : le dernier connu, même vieux, et un recalcul en
        tâche de fond s'il en faut un. Deux exceptions où la page attend : aucun instantané (`wait_first` secondes), et un état modifié par
        l'utilisateur (`hard_marker` changé : `hard_wait` secondes) -- elle rend alors ce qu'il a, ou None si le calcul n'est pas fini."""
        snap = self.load(key, db_path)
        soft, hard = self.markers(db_path)
        invalid = snap is not None and self.hard_marker_fn is not None and snap.hard_marker != hard
        if invalid or self.needs_refresh(snap, soft, utc_now(), live_running):
            self.request_refresh(key, db_path, rerun_if_running=invalid)
        wait = hard_wait if invalid else (wait_first if snap is None else 0.0)
        if wait > 0:
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                fresh = self.load(key, db_path)
                if fresh is not None and (not invalid or fresh.hard_marker == hard):
                    return fresh
                time.sleep(0.1)
            return None if snap is None else (None if invalid else snap)
        return None if invalid else snap
