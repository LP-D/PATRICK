"""Entonnoir de sélection des variables d'un run (VI8 du 26/11) : de l'univers de séries aux quelques variables du modèle retenu.

Lu dans les métadonnées du modèle exporté (`*_meta.json`, `tracking/export.py`) :

1. séries candidates de l'univers ;
2. séries gardées par la réduction de l'univers (une série trop corrélée à une autre est écartée, `selection/universe_reduction.py`) ;
3. variables construites à partir d'elles (le « pool » : techniques, volatilité, macro, interactions…) ;
4. variables retenues par le modèle final (les N meilleures de la sélection).

Avec, pour la dernière marche, la répartition par famille (préfixe du nom de la variable avant le premier « _ »).
"""
from __future__ import annotations

import math


def _family(name: str) -> str:
    head = str(name).split("_", 1)[0]
    return head if head and len(head) <= 12 else "autre"


def funnel(meta: dict | None) -> dict | None:
    """`{steps: [{key, n}], families: [{family, n}]}` ; None sans métadonnées exploitables."""
    if not meta:
        return None
    selected = list(meta.get("feature_names") or [])
    pool = list(meta.get("feature_pool") or [])
    if not selected:
        return None
    steps = []
    red = meta.get("universe_reduction") or {}
    if red and not red.get("skipped_reason"):
        kept = len(red.get("kept") or []) + len(red.get("not_eligible") or [])
        steps.append({"key": "series", "n": kept + len(red.get("dropped") or {})})
        steps.append({"key": "series_kept", "n": kept})
    if pool:
        steps.append({"key": "pool", "n": len(pool)})
    steps.append({"key": "selected", "n": len(selected)})
    fam: dict[str, int] = {}
    for name in selected:
        fam[_family(name)] = fam.get(_family(name), 0) + 1
    families = sorted(({"family": f, "n": n} for f, n in fam.items()), key=lambda r: (-r["n"], r["family"]))

    top = max(s["n"] for s in steps) or 1
    for s in steps:                              # échelle logarithmique : 2 000 variables et 8 retenues restent lisibles sur la même barre
        s["width"] = round(max(4.0, 100 * math.log1p(s["n"]) / math.log1p(top)), 1)
    return {"steps": steps, "families": families, "dropped": dict(list((red.get("dropped") or {}).items())[:12])}
