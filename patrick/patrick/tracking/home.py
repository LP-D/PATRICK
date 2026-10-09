"""Synthèse (page d'accueil) : l'état de l'application en six chiffres et trois questions -- les données sont-elles saines, que
valent les modèles, que disent les signaux du jour -- avec, pour chacune, le lien vers la page qui détaille.

Tout est lu sans réseau et sans calcul de modèle ; aucun nombre n'est mis en cache.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from patrick.clock import utc_now
from patrick.config import defaults as D
from patrick.data.store import DataStore
from patrick.tracking import class_overview, data_health
from patrick.tracking import db as trackdb

RECENT_DAYS = 14


def _median(values) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def home_summary(conn: sqlite3.Connection, groups: dict[str, list[tuple[str, str]]],
                 min_years: int = D.DEFAULT_MIN_HISTORY_YEARS, store: DataStore | None = None) -> dict:
    runs = trackdb.list_all_runs(conn)
    done = [r for r in runs if r["status"] == "done"]
    sane = [r for r in done if not r.get("suspect")]
    kinds = {"directional": {"n": 0, "auc": [], "f1": []}, "alpha": {"n": 0, "auc": [], "f1": []}}
    for r in sane:
        k = kinds[r["kind"]]
        k["n"] += 1
        k["auc"].append(r.get("best_auc"))
        k["f1"].append(r.get("best_f1_dir"))
    for k in kinds.values():
        k["auc"], k["f1"] = _median(k["auc"]), _median(k["f1"])

    failures = data_health.failures(conn)
    since = (utc_now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    recent_failures = [f for f in failures if (f["at"] or "") >= since and f["kind"] not in ("stopped",)]
    classes = class_overview.all_classes_summary(conn, groups, min_years, store)
    n_champions = conn.execute("SELECT COUNT(*) FROM champion").fetchone()[0]
    return {
        "n_done": len(done), "n_sane": len(sane), "n_suspect": len(done) - len(sane), "n_champions": n_champions,
        "kinds": kinds, "auc_median": _median(r.get("best_auc") for r in sane), "f1_median": _median(r.get("best_f1_dir") for r in sane),
        "n_failures": len(failures), "n_recent_failures": len(recent_failures), "recent_days": RECENT_DAYS,
        "n_short": sum(c["n_short"] for c in classes), "n_targets": sum(c["n_targets"] for c in classes),
        "classes": classes, "min_years": min_years,
    }
