"""Verdict du placebo de décalage (ADR 0008) : module léger, partagé par le moteur et la page d'un run."""
from __future__ import annotations

import math

PLACEBO_MIN_AUC = 0.58
PLACEBO_MIN_DROP = 0.08


def placebo_verdict(real: dict | None, lagged: dict | None) -> str | None:
    """`"same_day"` si un signal net du holdout (AUC >= `PLACEBO_MIN_AUC`) perd au moins `PLACEBO_MIN_DROP` d'AUC quand les variables sont
    retardées d'un jour : il repose sur l'information du jour même (souvent une fuite de date). `"stable"` sinon, `None` sans données."""
    a = (real or {}).get("AUC_ovr_4cls")
    b = (lagged or {}).get("AUC_ovr_4cls")
    if a is None or b is None or math.isnan(a) or math.isnan(b):
        return None
    return "same_day" if a >= PLACEBO_MIN_AUC and a - b >= PLACEBO_MIN_DROP else "stable"
