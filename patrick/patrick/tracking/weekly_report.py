"""Rapport hebdomadaire : ce qui s'est passé sur la plateforme pendant la semaine écoulée, en un fichier Markdown.

Écrit dans `paths.reports_dir()` sous le nom `hebdo-<lundi>.md`, une fois par semaine, par l'actualisation quotidienne
(`live_refresh.write_weekly_report`) ou par la commande `patrick report weekly`. Lecture seule sur la base ; le seul effet est le fichier.
Le texte est en français, comme les journaux et les rapports d'audit du projet.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

from patrick import paths
from patrick.clock import utc_today
from patrick.tracking import health, live_board, pooled_signal, relaunch_stats

PREFIX = "hebdo-"


def default_folder(db_path: str | None = None) -> Path:
    """Dossier des rapports : celui des données (`paths.reports_dir()`), sauf pour une base désignée explicitement (argument ou
    `PATRICK_DB_PATH` : essais, base de démonstration), dont les rapports restent à côté d'elle et jamais dans les vraies données."""
    explicit = db_path or os.environ.get("PATRICK_DB_PATH")
    return Path(explicit).parent / "reports" if explicit else paths.reports_dir()


def week_start(day: dt.date) -> dt.date:
    """Lundi de la semaine ÉCOULÉE au moment où `day` produit le rapport (la semaine précédente, complète)."""
    return day - dt.timedelta(days=day.weekday() + 7)


def _count(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    try:
        return int(conn.execute(sql, params).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def build(conn: sqlite3.Connection, today: dt.date | None = None) -> dict:
    """Les faits de la semaine `[lundi, lundi + 7 jours[`."""
    today = today or utc_today()
    start = week_start(today)
    end = start + dt.timedelta(days=7)
    span = (start.isoformat(), end.isoformat())
    board = live_board.board(conn, today)
    week = next((r for r in board["by_week"] if r["key"] == start.isoformat()), None)
    duels = dict(conn.execute("SELECT decision, COUNT(*) FROM duel_outcome WHERE decided_at >= ? AND decided_at < ? GROUP BY decision",
                              span).fetchall()) if _count(conn, "SELECT COUNT(*) FROM duel_outcome WHERE decided_at >= ? AND decided_at < ?", span) else {}
    return {
        "start": start.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(),
        "live_week": week, "live_total": board["total"], "bias": board["bias"],
        "runs_done": _count(conn, "SELECT COUNT(*) FROM run WHERE status = 'done' AND finished_at >= ? AND finished_at < ?", span),
        "runs_failed": _count(conn, "SELECT COUNT(*) FROM run WHERE status = 'failed' AND finished_at >= ? AND finished_at < ? "
                                    "AND COALESCE(error, '') NOT LIKE 'Stopped by user%'", span),
        "duels": duels,
        "champions_replaced": _count(conn, "SELECT COUNT(*) FROM model_archive WHERE role = 'replaced_champion' AND decided_at >= ? AND decided_at < ?", span),
        "fund_replacements": _count(conn, "SELECT COUNT(*) FROM fund_replacement WHERE replaced_at >= ? AND replaced_at < ?", span),
        "lost_series": relaunch_stats.lost_series(conn, days=7),
        "pooled": pooled_signal.summary(conn),
        "health": [c for c in health.checks(conn) if c["status"] in ("warning", "error")],
    }


def _pct(value: float | None) -> str:
    return "n.d." if value is None else f"{value * 100:.1f} %".replace(".", ",")


def _pts(value: float | None) -> str:
    return "n.d." if value is None else f"{value * 100:+.1f} pt".replace(".", ",")


def _live_line(label: str, stat: dict | None) -> str:
    if not stat or not stat.get("n"):
        return f"- {label} : aucune prédiction jugée."
    naive = max(stat["up_rate"], 1 - stat["up_rate"])
    return (f"- {label} : {_pct(stat['rate'])} de bonnes directions sur {stat['n']} prédictions jugées ; stratégie sans modèle {_pct(naive)} ; "
            f"apport des modèles {_pts(stat['edge'])}.")


def render(report: dict) -> str:
    """Le rapport en Markdown."""
    lines = [f"# Rapport hebdomadaire — semaine du {report['start']} au {report['end']}", "",
             "## Résultat réel des champions", "",
             _live_line("Signaux de la semaine", report["live_week"]), _live_line("Depuis le début", report["live_total"])]
    if report["bias"]:
        lines.append(f"- Seuil recalé (mesure seule) : {_pct(report['bias']['shadow_rate'])} contre {_pct(report['bias']['rate'])} "
                     f"sur {report['bias']['n']} prédictions ({_pts(report['bias']['gain'])}).")
    duels = report["duels"]
    lines += ["", "## Entraînements", "",
              f"- Runs terminés : {report['runs_done']} ; en échec : {report['runs_failed']}.",
              (f"- Duels : {duels.get('challenger_wins', 0)} gagnés par le challenger, {duels.get('champion_wins', 0)} gardés par le champion, "
               f"{duels.get('promoted_first', 0)} premiers champions."),
              f"- Champions remplacés : {report['champions_replaced']} ; modèles remplacés dans les fonds : {report['fund_replacements']}."]
    pooled = report["pooled"]
    if pooled:
        lines.append(f"- Signal regroupé : {pooled['n_significant']} paires significatives sur {pooled['n_tested']} testées "
                     f"(calcul du {str(pooled['computed_at'])[:10]}).")
    lines += ["", "## Données", ""]
    if report["lost_series"]:
        lines += [f"- Série d'entrée perdue : {s['series']} ({s['n_models']} modèle(s) touché(s))." for s in report["lost_series"][:10]]
    else:
        lines.append("- Aucune série d'entrée perdue.")
    lines += ["", "## Points d'attention", ""]
    if report["health"]:
        lines += [f"- {c['key']} : {c['status']}" + (f" ({c['value']})" if c["value"] is not None else "") for c in report["health"]]
    else:
        lines.append("- Aucun.")
    return "\n".join(lines) + "\n"


def path_for(today: dt.date | None = None, folder: Path | None = None) -> Path:
    return (folder or default_folder()) / f"{PREFIX}{week_start(today or utc_today()).isoformat()}.md"


def write_if_due(conn: sqlite3.Connection, today: dt.date | None = None, folder: Path | None = None) -> Path | None:
    """Écrit le rapport de la semaine écoulée s'il n'existe pas encore ; renvoie son chemin, ou `None` s'il était déjà là."""
    target = path_for(today, folder)
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(build(conn, today)), encoding="utf-8")
    return target


def list_reports(folder: Path | None = None) -> list[str]:
    """Noms des rapports présents, le plus récent d'abord."""
    try:
        root = folder or default_folder()
    except paths.DataRootUnavailable:
        return []
    return sorted((p.name for p in root.glob(f"{PREFIX}*.md")), reverse=True) if root.is_dir() else []


def read(name: str, folder: Path | None = None) -> str | None:
    """Le texte d'un rapport listé par `list_reports`, ou `None` (nom inconnu : jamais un chemin fourni par l'appelant)."""
    if name not in list_reports(folder):
        return None
    return ((folder or default_folder()) / name).read_text(encoding="utf-8")
