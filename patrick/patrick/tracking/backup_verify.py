"""Vérification qu'une sauvegarde se restaure (A29) : une sauvegarde jamais relue n'est qu'une promesse.

La plus récente sauvegarde complète (`patrick_backup_*.db`, `tracking/backup.py`) est ouverte en lecture seule absolue (`immutable=1` : SQLite
ne crée ni `-wal` ni `-shm` à côté et n'écrit rien). Contrôles légers, en quelques secondes sur des dizaines de Go :
- l'en-tête annonce exactement les pages du fichier (sauvegarde non tronquée) ;
- la version de schéma est celle d'une base connue ;
- chaque table clé se lit, et compte au plus autant de lignes que la base vivante (une sauvegarde est un instantané du passé) mais pas zéro
  quand la base vivante en a ;
- les derniers enregistrements de `prediction` se relisent (les pages de la fin du fichier sont saines).
`full=True` ajoute `PRAGMA quick_check`, qui relit tout le fichier (plusieurs minutes sur la vraie base).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from patrick.core import paths
from patrick.tracking import backup as backup_mod

KEY_TABLES = ("run", "trial", "champion", "prediction", "fund_strategy", "fund_order")


def latest_backup(dest_dir: Path | str | None = None) -> Path | None:
    """La sauvegarde COMPLÈTE la plus récente, ou None."""
    try:
        folder = Path(dest_dir) if dest_dir else paths.backups_dir()
    except paths.DataRootUnavailable:
        return None
    if not folder.is_dir():
        return None
    files = sorted((p for p in folder.glob("patrick_backup_*.db") if backup_mod.is_complete_backup(p)), key=lambda p: p.name)
    return files[-1] if files else None


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)


def _count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])          # `table` vient de KEY_TABLES
    except sqlite3.Error:
        return None


def verify(path: Path, live: sqlite3.Connection | None = None, full: bool = False) -> dict:
    """Contrôles de la sauvegarde `path` (voir l'en-tête). `ok` = tous passés ; `checks` = [{name, ok, detail}]."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    check("complete", backup_mod.is_complete_backup(path), "en-tête et taille du fichier cohérents")
    try:
        conn = _ro(path)
    except sqlite3.Error as exc:
        check("open", False, str(exc))
        return {"ok": False, "file": str(path), "checks": checks}
    try:
        try:
            version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            check("schema", version is not None and version > 0, f"migration {version}")
        except sqlite3.Error as exc:
            check("schema", False, str(exc))
        for table in KEY_TABLES:
            n = _count(conn, table)
            live_n = _count(live, table) if live is not None else None
            if n is None:
                check(f"table:{table}", False, "illisible")
            elif live_n is not None:
                check(f"table:{table}", n <= live_n and (n > 0 or live_n == 0), f"{n} lignes (base vivante : {live_n})")
            else:
                check(f"table:{table}", True, f"{n} lignes")
        try:
            rows = conn.execute("SELECT trial_id, ts, split FROM prediction ORDER BY rowid DESC LIMIT 50").fetchall()
            check("tail", True, f"{len(rows)} dernières prédictions relues")
        except sqlite3.Error as exc:
            check("tail", False, str(exc))
        if full:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
            check("quick_check", result == "ok", result)
    finally:
        conn.close()
    return {"ok": all(c["ok"] for c in checks), "file": str(path), "checks": checks}
