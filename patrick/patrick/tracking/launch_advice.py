"""Assistant de lancement par objectif de temps (FO27 du 25/11) : « je veux un modèle en moins de 30 minutes » -> quel profil choisir.

Les profils d'entraînement (`config/training_profiles.py` : rapide, récent, standard, robuste, approfondi…) ne disent pas combien de temps
ils prennent sur CE PC. On le mesure sur les runs terminés : profil déduit des réglages (`training_profiles.identify`), durée réelle
(début -> fin), médiane par profil (sur la cible si elle a assez de runs, sinon sur toutes). L'assistant propose le profil le plus
approfondi dont la médiane tient dans le temps donné. Une médiane n'est pas une promesse : la durée dépend aussi de la charge du PC.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import statistics

# du plus léger au plus approfondi : à temps égal, on préfère le plus approfondi
# (profils de direction seulement : un profil de valeur exacte prépare un autre objectif, il n'est jamais proposé à sa place)
DEPTH = ("quick", "short_history", "recent", "standard", "regimes", "robust", "ensemble", "deep", "max")
MIN_RUNS = 3


def _minutes(started: str | None, finished: str | None) -> float | None:
    try:
        a, b = dt.datetime.fromisoformat(str(started).replace(" ", "T")), dt.datetime.fromisoformat(str(finished).replace(" ", "T"))
    except (TypeError, ValueError):
        return None
    m = (b - a).total_seconds() / 60.0
    return m if m > 0 else None


def durations(conn: sqlite3.Connection, target: str | None = None) -> dict[str, list[float]]:
    from patrick.config import training_profiles
    from patrick.webapp import forms

    default_view = forms.to_view(forms.default_config_dict("ml"))
    out: dict[str, list[float]] = {}
    sql = "SELECT config_json, started_at, finished_at FROM run WHERE status = 'done' AND finished_at IS NOT NULL"
    rows = conn.execute(sql + (" AND target = ?" if target else "") + " ORDER BY started_at DESC LIMIT 2000", (target,) if target else ()).fetchall()
    for cfg_json, started, finished in rows:
        minutes = _minutes(started, finished)
        if minutes is None:
            continue
        try:
            profile = training_profiles.identify(forms.to_view(json.loads(cfg_json or "{}")), default_view)
        except (KeyError, TypeError, ValueError, AttributeError):
            profile = None
        if profile:
            out.setdefault(profile, []).append(minutes)
    return out


def advise(conn: sqlite3.Connection, minutes: float, target: str | None = None) -> dict:
    """`{profiles: [{key, median_min, n}], recommended, scope}` ; `scope` = la cible si elle a assez de runs, sinon « tous »."""
    by = durations(conn, target) if target else {}
    scope = target
    if sum(len(v) for v in by.values()) < MIN_RUNS:
        by, scope = durations(conn), None
    profiles = [{"key": k, "median_min": round(statistics.median(v), 1), "n": len(v)} for k, v in by.items() if len(v) >= MIN_RUNS]
    profiles.sort(key=lambda p: DEPTH.index(p["key"]) if p["key"] in DEPTH else len(DEPTH))
    fitting = [p for p in profiles if p["key"] in DEPTH and p["median_min"] <= minutes]   # jamais un profil hors échelle (valeur exacte, thématique)
    return {"profiles": profiles, "recommended": fitting[-1]["key"] if fitting else None, "scope": scope, "minutes": minutes}
