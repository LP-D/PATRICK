"""Vue « Par horizon » de `/predictions` : assemble le tableau des signaux du jour (`app._predictions_overview`) et l'avantage
mesuré sur les signaux jugés (`tracking/live_edge.py`) en une structure prête pour `_predictions_horizon.html`.

Aucun calcul statistique ici (il vit dans `tracking/live_edge.py`, testé à part) : seulement du regroupement et du tri."""
from __future__ import annotations

import sqlite3
from typing import Any

from patrick.config import asset_classes
from patrick.tracking import live_edge

OTHER_CLASS = "other"


def class_order() -> list[str]:
    """Ordre d'affichage des classes : celui de la barre latérale, puis les actifs sans classe."""
    return [c.key for c in sorted(asset_classes.ASSET_CLASSES, key=lambda c: c.nav_order)] + [OTHER_CLASS]


def class_of_assets(overview: dict[str, Any]) -> dict[str, str]:
    """`{cible: clé de classe}` d'après le groupe du tableau des prédictions (`asset_classes.class_of_group`)."""
    return {a["symbol"]: asset_classes.class_of_group(g["group"]) or OTHER_CLASS
            for g in overview["groups"] for a in g["assets"]}


def horizons_shown(overview: dict[str, Any]) -> list[int]:
    """Les horizons qui ont au moins un signal live aujourd'hui (pas de colonne vide)."""
    return [h for h in overview["horizons"]
            if any(a["cells"][h]["direction"] for g in overview["groups"] for a in g["assets"])]


def compute_edge(conn: sqlite3.Connection, overview: dict[str, Any]) -> dict[str, Any]:
    """Lit les signaux jugés en base puis calcule l'avantage par classe et par actif (mémorisé par l'appelant)."""
    symbols = [a["symbol"] for g in overview["groups"] for a in g["assets"]]
    judged, excluded = live_edge.fetch_judged(conn, symbols, overview["horizons"])
    out = live_edge.build(judged, class_of_assets(overview), overview["horizons"])
    out["excluded_backfill"] = excluded
    return out


def build(overview: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    """`{horizons, matrix_rows, blocks, ...}` :

    - `matrix_rows` : une ligne par classe présente (+ « toutes classes »), `cells[horizon]` = statistiques et verdict ;
    - `blocks` : un bloc par horizon, avec ses classes et, pour chacune, les actifs qui ont un signal aujourd'hui ou un historique
      jugé (`cell` = la cellule de `/predictions`, `edge` = la précision jugée de cet actif sur cet horizon)."""
    horizons = horizons_shown(overview)
    cls_of = class_of_assets(overview)
    present = {c for c in cls_of.values()}
    order = [c for c in class_order() if c in present]
    matrix_rows = [{"key": live_edge.ALL_KEY, "cells": edge["matrix"].get(live_edge.ALL_KEY, {})}]
    matrix_rows += [{"key": c, "cells": edge["matrix"].get(c, {})} for c in order if c in edge["matrix"]]

    blocks = []
    for h in horizons:
        by_class: dict[str, list[dict]] = {c: [] for c in order}
        n_signals = 0
        for g in overview["groups"]:
            cls = asset_classes.class_of_group(g["group"]) or OTHER_CLASS
            for a in g["assets"]:
                cell = a["cells"][h]
                stats = edge["assets"].get((a["symbol"], h))
                has_stats = bool(stats and stats["n"])
                if not cell["direction"] and not has_stats:
                    continue
                n_signals += int(bool(cell["direction"]))
                by_class[cls].append({"symbol": a["symbol"], "label": a["label"], "cell": cell, "edge": stats if has_stats else None})
        blocks.append({
            "horizon": h, "n_signals": n_signals,
            "classes": [{"key": c, "stats": edge["matrix"].get(c, {}).get(h), "assets": rows}
                        for c, rows in by_class.items() if rows],
        })
    return {"horizons": horizons, "matrix_rows": matrix_rows, "blocks": blocks, "n_judged": edge["n_judged"],
            "first_day": edge["first_day"], "last_day": edge["last_day"], "excluded_backfill": edge["excluded_backfill"],
            "min_effective": live_edge.MIN_EFFECTIVE}
