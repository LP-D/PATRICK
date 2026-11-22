"""Synthèse (page d'accueil) : l'état de l'application en six chiffres et trois questions -- les données sont-elles saines, que
valent les modèles, que disent les signaux du jour -- avec, pour chacune, le lien vers la page qui détaille.

Tout est lu sans réseau et sans calcul de modèle ; aucun nombre n'est mis en cache.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from patrick.config import defaults as D
from patrick.core.clock import utc_now
from patrick.data.store import DataStore
from patrick.tracking import class_overview, data_health, relaunch_stats
from patrick.tracking import db as trackdb
from patrick.validation import metric_panel

RECENT_DAYS = 14


def _median(values) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def panel_median(runs) -> dict[str, float | None]:
    """Médiane de chaque mesure du panneau (ADR 0023) sur les plis de test des runs donnés, chaque mesure sur les runs qui l'ont."""
    runs = list(runs)
    return {key: _median((r.get("panel") or {}).get(key) for r in runs) for key in metric_panel.PANEL_KEYS}


def recent_failures(failures: list[dict]) -> list[dict]:
    """Parmi `data_health.failures`, ceux des `RECENT_DAYS` derniers jours hors runs arrêtés à la main : le nombre de la ligne « échecs »
    de la synthèse, et la liste de sa page."""
    since = (utc_now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    return [f for f in failures if (f["at"] or "") >= since and f["kind"] not in ("stopped",)]


def action_items(conn: sqlite3.Connection, n_recent_failures: int, n_suspect: int) -> list[dict]:
    """Ce qui demande une action maintenant, une ligne par sujet, avec la page où agir (ADR 0010) : échecs récents, runs suspects, file d'attente,
    champions de change d'avant la correction d'alignement. Une ligne sans objet n'apparaît pas."""
    items: list[dict] = []
    if n_recent_failures:
        items.append({"key": "failures", "n": n_recent_failures, "href": "/a-faire/failures", "level": "warning", "days": RECENT_DAYS})
    if n_suspect:
        items.append({"key": "suspect", "n": n_suspect, "href": "/a-faire/suspect", "level": "error"})
    queued = conn.execute("SELECT COUNT(*) FROM job WHERE status = 'queued'").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM job WHERE status = 'running'").fetchone()[0]
    if queued or running:
        items.append({"key": "queue", "n": queued, "running": running, "href": "/a-faire/queue", "level": "neutral"})
    legacy = len(trackdb.legacy_alignment_champions(conn))      # devises (règle 1) et Asie (séries FRED du jour)
    if legacy:
        items.append({"key": "fx_legacy", "n": legacy, "href": "/a-faire/fx_legacy", "level": "warning"})
    lost = relaunch_stats.lost_series(conn)
    if lost:
        items.append({"key": "inputs_lost", "n": sum(s["n_models"] for s in lost), "level": "error", "href": "/data-quality",
                      "series": ", ".join(f"{s['series']} ({s['n_models']})" for s in lost[:3]) + ("…" if len(lost) > 3 else "")})
    return items


def home_summary(conn: sqlite3.Connection, groups: dict[str, list[tuple[str, str]]],
                 min_years: int = D.DEFAULT_MIN_HISTORY_YEARS, store: DataStore | None = None) -> dict:
    runs = trackdb.list_all_runs(conn, with_balance=False)          # ni la page ni les classes n'affichent la répartition haut / bas
    done = [r for r in runs if r["status"] == "done"]
    sane = [r for r in done if not r.get("suspect")]
    kinds = {"directional": {"n": 0, "panel": {}}, "alpha": {"n": 0, "panel": {}}}
    for r in sane:
        kinds[r["kind"]]["n"] += 1
    for kind, k in kinds.items():
        k["panel"] = panel_median(r for r in sane if r["kind"] == kind)

    failures = data_health.failures(conn)
    recent = recent_failures(failures)
    classes = class_overview.all_classes_summary(conn, groups, min_years, store, runs=runs)
    n_champions = conn.execute("SELECT COUNT(*) FROM champion").fetchone()[0]
    from patrick.tracking import pooled_signal

    return {
        "pooled": pooled_signal.summary(conn),
        "n_done": len(done), "n_sane": len(sane), "n_suspect": len(done) - len(sane), "n_champions": n_champions,
        "kinds": kinds, "panel_median": panel_median(sane),
        "n_failures": len(failures), "n_recent_failures": len(recent), "recent_days": RECENT_DAYS,
        "n_short": sum(c["n_short"] for c in classes), "n_targets": sum(c["n_targets"] for c in classes),
        "classes": classes, "min_years": min_years,
        "actions": action_items(conn, len(recent), len(done) - len(sane)),
    }
