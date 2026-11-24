"""Horloge « machine éveillée » : le temps écoulé hors veille et hors hibernation.

`time.time()` (et `time.monotonic()` sous Windows, qui lit `GetTickCount64`) continue d'avancer pendant que le PC dort : un run commencé le
soir et repris au réveil affichait des heures « écoulées » pendant lesquelles rien n'avait tourné. Sous Windows, `QueryUnbiasedInterruptTime`
compte le temps d'interruption SANS les périodes de veille ou d'hibernation (unités de 100 ns) ; ailleurs, `time.monotonic()` (CLOCK_MONOTONIC
sous Linux, `mach_absolute_time` sous macOS) s'arrête déjà pendant la suspension.

La différence entre l'écart d'horloge murale et l'écart de cette horloge, entre deux battements du worker, est le temps passé en veille
(`suspended_between`) : le fil de battement (`system/worker.py`) l'inscrit dans `machine_idle` (migration 0054), et toutes les durées
affichées (chronomètre d'un run, estimation de la file, durées moyennes par étape) le retranchent.
"""
from __future__ import annotations

import ctypes
import sys
import time

# Écart minimal (s) pour conclure à une veille : en dessous, c'est la gigue de l'ordonnanceur ou un réglage NTP de l'horloge murale.
SUSPEND_MIN_S = 20.0


def _windows_unbiased() -> float | None:
    try:
        value = ctypes.c_ulonglong(0)
        if ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(value)):   # type: ignore[attr-defined]
            return value.value / 1e7
    except (AttributeError, OSError):
        return None
    return None


def awake_seconds() -> float:
    """Secondes d'une horloge monotone qui S'ARRÊTE pendant la veille (origine arbitraire : n'en comparer que des écarts)."""
    if sys.platform == "win32":
        value = _windows_unbiased()
        if value is not None:
            return value
    return time.monotonic()


def suspended_between(wall_before: float, awake_before: float, wall_after: float, awake_after: float,
                      threshold: float = SUSPEND_MIN_S) -> float:
    """Temps passé en veille entre deux lectures `(time.time(), awake_seconds())` ; 0 sous le seuil (gigue, réglage d'horloge)."""
    gap = (wall_after - wall_before) - (awake_after - awake_before)
    return gap if gap >= threshold else 0.0
