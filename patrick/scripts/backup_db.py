"""Phase 6 -- point d'entrée CLI pour la sauvegarde périodique de la base
SQLite de suivi (`patrick.db`).

La logique de sauvegarde elle-même (choix de la méthode, gestion du mode
WAL) vit dans `patrick.tracking.backup` -- testée par
`tests/test_backup_db.py` sur des bases légères sous `tmp_path`, jamais sur
le fichier réel. Ce script n'est qu'un habillage CLI/logging autour de
`backup_database()`, destiné à être invoqué directement par le
Planificateur de tâches Windows (voir `schtasks_daily_dbbackup.ps1` pour la
commande de planification, documentée mais non exécutée par l'agent qui
l'a écrite).

Usage :
    python scripts/backup_db.py
    python scripts/backup_db.py --backup-dir D:\\backups\\patrick
    python scripts/backup_db.py --log-file C:\\Users\\leonp\\.patrick\\backups\\backup.log

`--log-file` existe car le Planificateur de tâches Windows ne capture pas
la sortie standard d'une tâche par défaut (même remarque déjà faite pour
`daily_predict.py` sur la branche `feature/scheduled-inference`) -- sans
ça, un échec silencieux ne laisserait aucune trace exploitable.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from patrick.tracking.backup import DEFAULT_BACKUP_DIR, backup_database

logger = logging.getLogger("patrick.scripts.backup_db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", default=None,
        help="Chemin de la base a sauvegarder (defaut : $PATRICK_DB_PATH ou ~/.patrick/patrick.db).",
    )
    parser.add_argument(
        "--backup-dir", default=None,
        help=f"Dossier de destination des sauvegardes (defaut : {DEFAULT_BACKUP_DIR}).",
    )
    parser.add_argument(
        "--pages", type=int, default=100,
        help="Nombre de pages copiees par lot par sqlite3.Connection.backup() (defaut : 100).",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.25,
        help="Pause en secondes entre deux lots de copie (defaut : 0.25).",
    )
    parser.add_argument(
        "--log-file", default=None,
        help="Fichier de log en plus de stdout (recommande sous le Planificateur de taches Windows).",
    )
    args = parser.parse_args(argv)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        os.makedirs(os.path.dirname(args.log_file) or ".", exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )

    t0 = time.perf_counter()
    try:
        dest_path = backup_database(
            args.source, args.backup_dir, pages=args.pages, sleep_s=args.sleep,
        )
    except FileNotFoundError as exc:
        logger.error("Sauvegarde annulee : %s", exc)
        return 1

    dt = time.perf_counter() - t0
    size_mb = os.path.getsize(dest_path) / (1024 * 1024)
    logger.info("Sauvegarde terminee : %s (%.1f Mo, %.1fs)", dest_path, size_mb, dt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
