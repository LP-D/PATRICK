"""Vue « classe d'actifs » : pour chaque cible d'une classe, ce que l'application sait déjà d'elle -- profondeur d'historique,
modèles directionnels et alpha entraînés (panneau du meilleur modèle -- AUC de direction, puis Brier, ADR 0023 -- jamais un score
suspect), champions, dernier run.

Une seule lecture de `run` pour toute la page (`tracking/db.py::list_all_runs`, requêtes groupées) : le coût ne dépend pas du
nombre de cibles affichées, une classe de 320 actions se rend aussi vite qu'une classe de 6 cryptos.
"""
from __future__ import annotations

import html
import sqlite3
from datetime import date

from patrick.config import asset_classes
from patrick.config.target_label import split_run_label
from patrick.data.store import DataStore
from patrick.tracking import data_health
from patrick.tracking import db as trackdb
from patrick.validation import metric_panel


def model_stats_by_asset(conn: sqlite3.Connection, runs: list[dict] | None = None) -> dict[str, dict]:
    """`{actif: {directional: {...}, alpha: {...}, champions: [horizons], suspects: n}}` sur tous les runs non archivés.
    `runs` : `list_all_runs` déjà lu par l'appelant (chaque lecture parse le `config_json` de tous les runs)."""
    champions: dict[str, set[int]] = {}
    for target, horizon in conn.execute("SELECT target, horizon FROM champion"):
        champions.setdefault(split_run_label(target)[0], set()).add(int(horizon))
    stats: dict[str, dict] = {}
    for run in (trackdb.list_all_runs(conn, with_balance=False) if runs is None else runs):
        asset, kind, _bench = split_run_label(html.unescape(run["target"] or ""))
        entry = stats.setdefault(asset, {
            "directional": {"n": 0, "n_done": 0, "best": None, "best_run": None, "last": None},
            "alpha": {"n": 0, "n_done": 0, "best": None, "best_run": None, "last": None},
            "value": {"n": 0, "n_done": 0, "best": None, "best_run": None, "last": None},
            "champions": sorted(champions.get(asset, ())), "suspects": 0})
        # valeur exacte (`__val`) : sa propre colonne, classée sur son panneau (IC puis R²) ; elle ne se mêle plus à la direction
        is_value = run.get("kind") == "value" or html.unescape(run["target"] or "").endswith("__val")
        side = entry["value" if is_value else "alpha" if kind == "alpha" else "directional"]
        side["n"] += 1
        if run["started_at"] and (side["last"] is None or run["started_at"] > side["last"]):
            side["last"] = run["started_at"]
        if run["status"] != "done":
            continue
        side["n_done"] += 1
        if run.get("suspect"):
            entry["suspects"] += 1
            continue                      # un score impossible n'est jamais « le meilleur »
        panel = run.get("value_panel") if is_value else run.get("panel")
        rank = metric_panel.value_rank_key if is_value else metric_panel.rank_key
        if metric_panel.has_any(panel) and (side["best"] is None or rank(panel) < rank(side["best"])):
            side["best"], side["best_run"] = panel, run["run_id"]
    return stats


def class_page(conn: sqlite3.Connection, class_key: str, all_groups: dict[str, list[tuple[str, str]]],
               min_years: int, store: DataStore | None = None, today: date | None = None,
               stats: dict[str, dict] | None = None) -> dict:
    """Données de la page d'une classe : un bloc par groupe, une ligne par cible, et les compteurs d'en-tête.
    `stats` : `model_stats_by_asset` déjà calculé (la synthèse l'agrège une seule fois pour toutes les classes)."""
    cls = asset_classes.BY_KEY[class_key]
    wanted = {g: all_groups[g] for g in cls.groups if g in all_groups}
    history = {r["symbol"]: r for r in data_health.history_table(wanted, min_years, store, today)}
    stats = model_stats_by_asset(conn) if stats is None else stats
    groups = []
    kpi = {"n_targets": 0, "n_trained": 0, "n_alpha": 0, "n_champions": 0, "n_short": 0, "n_suspect": 0}
    for group, items in wanted.items():
        rows = []
        for symbol, label in items:
            h = history[symbol]
            s = stats.get(symbol)
            directional = (s or {}).get("directional", {})
            alpha = (s or {}).get("alpha", {})
            row = {"symbol": symbol, "label": label, "group": group, "first": h["first"], "years": h["years"],
                   "history": h["status"], "history_source": h["source"],
                   "n_dir": directional.get("n_done", 0), "n_dir_running": directional.get("n", 0) - directional.get("n_done", 0),
                   "panel": directional.get("best"), "best_run": directional.get("best_run"),
                   "n_alpha": alpha.get("n_done", 0), "alpha_panel": alpha.get("best"),
                   "champions": (s or {}).get("champions", []), "suspects": (s or {}).get("suspects", 0),
                   "last": max(filter(None, [directional.get("last"), alpha.get("last")]), default=None)}
            rows.append(row)
            kpi["n_targets"] += 1
            kpi["n_trained"] += int(row["n_dir"] > 0)
            kpi["n_alpha"] += int(row["n_alpha"] > 0)
            kpi["n_champions"] += int(bool(row["champions"]))
            kpi["n_short"] += int(row["history"] == "short")
            kpi["n_suspect"] += int(row["suspects"] > 0)
        groups.append({"group": group, "rows": rows})
    return {"class": cls, "groups": groups, "kpi": kpi}


def all_classes_summary(conn: sqlite3.Connection, all_groups: dict[str, list[tuple[str, str]]], min_years: int,
                        store: DataStore | None = None, runs: list[dict] | None = None) -> list[dict]:
    """Une ligne par classe d'actifs (compteurs de `class_page`) : le tableau « par classe » de la synthèse."""
    stats = model_stats_by_asset(conn, runs)
    out = []
    for cls in asset_classes.ASSET_CLASSES:
        page = class_page(conn, cls.key, all_groups, min_years, store, stats=stats)
        out.append({"key": cls.key, "url": cls.url, **page["kpi"]})
    return out
