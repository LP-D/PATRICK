"""Notifications Windows (A15) : un résumé en fin de nuit, seulement quand il y a quelque chose à dire.

Ce qui mérite une notification : la nuit a échoué, été partielle ou manquée (`system/night_status.py`), des champions ont été remplacés
pendant la nuit, des fonds sont à l'arrêt sur leur seuil de perte (`max_drawdown` du pilote). Une nuit sans histoire ne dérange personne.

Envoi par une notification « toast » Windows lancée via PowerShell (API Windows.UI.Notifications, sans module à installer), sous l'identifiant
d'application de PowerShell (un identifiant inventé n'afficherait rien sans raccourci du menu Démarrer). Ailleurs que sous Windows, ou si
l'envoi échoue, rien ne se passe : une notification ne fait jamais échouer la nuit. Désactivable : préférence `notify_night` (Réglages).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
import subprocess

logger = logging.getLogger(__name__)

POWERSHELL_AUMID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def toast(title: str, body: str) -> bool:
    """Affiche une notification Windows ; False ailleurs que sous Windows ou en cas d'échec (jamais d'exception)."""
    if os.name != "nt":
        return False
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$t = $x.GetElementsByTagName('text'); $t.Item(0).AppendChild($x.CreateTextNode({_ps_quote(title)})) > $null;"
        f"$t.Item(1).AppendChild($x.CreateTextNode({_ps_quote(body)})) > $null;"
        "$n = [Windows.UI.Notifications.ToastNotification]::new($x);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({_ps_quote(POWERSHELL_AUMID)}).Show($n)"
    )
    try:
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              timeout=30, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("notification non affichée : %s: %s", type(exc).__name__, exc)
        return False
    return done.returncode == 0


def night_summary(conn: sqlite3.Connection, night: dict) -> list[str]:
    """Lignes du résumé de la dernière nuit ; liste vide quand rien ne mérite d'être signalé."""
    lines: list[str] = []
    status = night.get("status")
    if status in ("failed", "partial", "missed"):
        what = {"failed": "le cycle des fonds n'a pas été fait", "partial": "étapes en échec : " + ", ".join(night.get("failed_steps") or []),
                "missed": "aucune tâche de nuit depuis plus de 36 h"}[status]
        lines.append(f"Nuit : {what}.")
    since = (night.get("started") or "").replace("T", " ")
    if since:
        start_utc = dt.datetime.fromisoformat(since).astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
        n = conn.execute("SELECT COUNT(*) FROM model_archive WHERE role = 'replaced_champion' AND decided_at >= ?", (start_utc,)).fetchone()[0]
        if n:
            lines.append(f"{n} champion(s) remplacé(s) pendant la nuit.")
    try:
        from patrick.fund import store
        halted = []
        for strategy in store.list_strategies(conn):
            stored = store.get_autopilot(conn, strategy["strategy_id"]) or {}
            if stored.get("enabled") and (stored.get("last_run") or {}).get("halted"):
                halted.append(strategy["name"])
        if halted:
            lines.append(f"Fonds à l'arrêt sur leur seuil de perte : {', '.join(halted[:3])}{' …' if len(halted) > 3 else ''}.")
    except sqlite3.Error as exc:
        logger.info("fonds non lus pour la notification : %s", exc)
    return lines
