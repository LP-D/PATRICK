"""Mémoïsation des vues lourdes de la base de suivi (synthèse, tableau des prédictions).

Sur la vraie base (27 Go, ~24 millions de prédictions), la synthèse demande ~6 s et le tableau des prédictions ~3 s, à chaque
chargement de page. Leur résultat ne change que quand un run se termine, qu'un champion est promu ou qu'une prédiction live est
écrite : `fingerprint` capte exactement ces événements en quelques lectures O(1), et le résultat calculé est réutilisé tant
que l'empreinte est la même (et pendant `ttl` secondes au plus).

- une seule exécution à la fois par clé : deux onglets ou deux fragments qui demandent la même vue attendent le premier calcul
  au lieu de le refaire en parallèle ;
- la clé contient le chemin de la base : jamais de résultat d'une base servi pour une autre (tests, bases temporaires) ;
- un échec de calcul n'est jamais mis en cache.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Hashable
from typing import Any

DEFAULT_TTL_S = 300.0

_lock = threading.Lock()
_key_locks: dict[Hashable, threading.Lock] = {}
_cache: dict[Hashable, tuple[float, tuple, Any]] = {}


def fingerprint(conn: sqlite3.Connection) -> tuple:
    """Empreinte de l'état de la base qui détermine les vues : prédictions live (nombre, dernière date), runs (nombre,
    dernière fin), champions (nombre, dernière promotion), derniers tests de Diebold-Mariano, jobs en cours.

    Les prédictions des plis et du holdout ne comptent pas : pendant un run le scan en écrit en continu, ce qui rendait
    la mémoïsation inopérante dès qu'un worker tournait ; une fois le run fini, `run.finished_at` bouge et suffit."""
    one = conn.execute
    return (
        tuple(one("SELECT COUNT(*), MAX(ts) FROM prediction WHERE split = 'live'").fetchone()),
        tuple(one("SELECT COUNT(*), MAX(finished_at) FROM run").fetchone()),
        tuple(one("SELECT COUNT(*), MAX(promoted_at) FROM champion").fetchone()),
        one("SELECT MAX(computed_at) FROM dm_result").fetchone()[0],
        one("SELECT COUNT(*) FROM job WHERE status = 'running'").fetchone()[0],
    )


def _db_path(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2] if row else ""


def memoize(conn: sqlite3.Connection, key: Hashable, compute: Callable[[], Any], ttl: float = DEFAULT_TTL_S) -> Any:
    """`compute()` si l'empreinte de la base a changé ou si le résultat a plus de `ttl` secondes, sinon la valeur déjà calculée."""
    full_key = (_db_path(conn), key)
    fp = fingerprint(conn)
    with _lock:
        guard = _key_locks.setdefault(full_key, threading.Lock())
    with guard:
        hit = _cache.get(full_key)
        if hit is not None and hit[1] == fp and time.monotonic() - hit[0] < ttl:
            return hit[2]
        value = compute()
        _cache[full_key] = (time.monotonic(), fp, value)
        return value


def clear() -> None:
    """Vide le cache (tests)."""
    with _lock:
        _cache.clear()
