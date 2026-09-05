"""Phase 6 -- sauvegarde périodique de la base SQLite de suivi (`patrick.db`).

Pourquoi pas `shutil.copy` : `tracking/db.py::connect()` active
`PRAGMA journal_mode = WAL` sur chaque connexion. En mode WAL, les écritures
récentes peuvent résider uniquement dans les fichiers séparés `<db>-wal` /
`<db>-shm` tant qu'aucun checkpoint n'a eu lieu -- copier le seul fichier
`.db` pendant une écriture concurrente (`patrick worker` actif, par
exemple) peut donc produire un fichier incohérent, reflétant un état
antérieur au dernier checkpoint plutôt que l'état réel de la base.

Méthode retenue : l'API de sauvegarde à chaud de sqlite3
(`sqlite3.Connection.backup()`), qui réplique la base page par page en
tenant compte du WAL et reste cohérente même en présence d'écritures
concurrentes sur la source -- documenté comme tel par la doc SQLite/CPython
("Connection.backup() ... online backup API"). Alternative envisagée :
`VACUUM INTO 'dest.db'` (SQLite >= 3.27), tout aussi cohérente et produisant
en prime un fichier compacté/défragmenté -- mais exécutée comme une
transaction unique, sans point de pause. `Connection.backup()` expose au
contraire `pages`/`sleep`, ce qui permet de copier par petits lots en
cédant la main régulièrement plutôt que de bloquer la connexion source
pendant toute la durée de la copie -- important sur la vraie base
(~4 Go), qui peut être activement écrite par un worker en cours
d'exécution pendant la sauvegarde planifiée.

Ce module ne s'exécute jamais sur le fichier réel pendant son
développement/ses tests : uniquement des bases SQLite légères créées par
l'appelant (voir `tests/test_backup_db.py`, `tmp_path`). Le point d'entrée
CLI planifiable est `scripts/backup_db.py`; la commande de planification
Windows (`schtasks`) est documentée (non exécutée) dans
`scripts/schtasks_daily_dbbackup.ps1`.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

from patrick.tracking.db import default_db_path

logger = logging.getLogger("patrick.tracking.backup")

DEFAULT_BACKUP_DIR = os.path.expanduser("~/.patrick/backups")

_FILENAME_TEMPLATE = "patrick_backup_{stamp}.db"


def backup_database(
    source_path: str | None = None,
    backup_dir: str | None = None,
    *,
    pages: int = 100,
    sleep_s: float = 0.25,
    timestamp: str | None = None,
) -> Path:
    """Produit une copie horodatée et cohérente de la base SQLite située à
    `source_path` (défaut : `db.default_db_path()`, donc
    `$PATRICK_DB_PATH` ou `~/.patrick/patrick.db`) dans `backup_dir`
    (défaut : `DEFAULT_BACKUP_DIR` = `~/.patrick/backups/`, créé si absent
    -- volontairement hors du dépôt git).

    Utilise `sqlite3.Connection.backup()` (voir docstring du module pour la
    justification vs. `shutil.copy` / `VACUUM INTO`). `pages`/`sleep_s`
    sont transmis à `Connection.backup()` pour copier par lots plutôt qu'en
    un seul bloc -- pertinent sur la vraie base (~4 Go), potentiellement
    écrite pendant la sauvegarde.

    Lève `FileNotFoundError` si `source_path` n'existe pas (rien à
    sauvegarder -- mieux vaut échouer bruyamment qu'écrire une "sauvegarde"
    vide silencieuse dans une tâche planifiée sans supervision).

    Retourne le chemin (`Path`) du fichier de sauvegarde effectivement créé.
    """
    src = source_path or default_db_path()
    if not os.path.exists(src):
        raise FileNotFoundError(f"Base source introuvable : {src}")

    dest_dir = Path(backup_dir or DEFAULT_BACKUP_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    dest_path = dest_dir / _FILENAME_TEMPLATE.format(stamp=stamp)

    def _log_progress(status: int, remaining: int, total: int) -> None:
        if total:
            done = total - remaining
            logger.info("backup: %d/%d pages copiees (%.1f%%)", done, total,
                        100.0 * done / total)

    source_conn = sqlite3.connect(src)
    try:
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            source_conn.backup(dest_conn, pages=pages, sleep=sleep_s, progress=_log_progress)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    return dest_path
