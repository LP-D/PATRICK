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
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from patrick import paths
from patrick.tracking.db import default_db_path

logger = logging.getLogger("patrick.tracking.backup")

_FILENAME_TEMPLATE = "patrick_backup_{stamp}.db"
_FILENAME_RE = re.compile(r"^patrick_backup_(\d{8}_\d{6})\.db$")

DEFAULT_RETENTION_DAYS = 30
# Nombre de sauvegardes complètes conservées (la base réelle pèse des dizaines de Go : trois copies, pas trente).
DEFAULT_KEEP_COUNT = 3
# Avant une mise à jour du code, le lanceur ne refait pas de copie si une complète date de moins que cela.
RECENT_BACKUP_HOURS = 24
# Un fichier incomplet, une copie `.part` ou une annexe orpheline plus jeunes que cela peuvent être une sauvegarde en cours.
_STALE_AFTER_SECONDS = 3600
_PART_SUFFIX = ".part"
_SQLITE_MAGIC = b"SQLite format 3\x00"
_SIDECAR_RE = re.compile(r"^(patrick_backup_\d{8}_\d{6}\.db)-(wal|shm|journal)$")


def _purge_old_backups(dest_dir: Path, retention_days: int, *, now: datetime | None = None) -> list[Path]:
    """Supprime dans `dest_dir` les fichiers `patrick_backup_<horodatage>.db`
    dont l'horodatage encodé dans le NOM (pas la date de modification du
    fichier, qui peut être faussée par une copie/restauration) est antérieur
    à `retention_days` jours. Ignore silencieusement tout fichier de
    `dest_dir` qui ne correspond pas au motif de nommage des sauvegardes
    (règle de sélection fiable : on ne touche qu'à ce que ce module a
    lui-même produit). Retourne la liste des fichiers effectivement
    supprimés."""
    if retention_days <= 0 or not dest_dir.exists():
        return []
    # Naive local datetimes throughout, by design: the stamp embedded in the
    # filename comes from `time.strftime(...)` (local time, no tz) in
    # `backup_database()` below -- comparing against an aware `now` here
    # would raise on the very first purge.
    cutoff = (now or datetime.now()) - timedelta(days=retention_days)  # noqa: DTZ005
    removed: list[Path] = []
    for path in dest_dir.glob("patrick_backup_*.db"):
        m = _FILENAME_RE.match(path.name)
        if not m:
            continue
        try:
            stamp_dt = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")  # noqa: DTZ007
        except ValueError:
            continue
        if stamp_dt < cutoff:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                logger.warning("Retention: impossible de supprimer l'ancienne sauvegarde %s", path)
    return removed


def is_complete_backup(path: Path) -> bool:
    """Vrai si l'en-tête SQLite du fichier annonce exactement les pages qu'il contient.

    `sqlite3.Connection.backup()` écrit d'abord la première page (donc le nombre total de pages) puis le reste : un
    fichier laissé par une sauvegarde interrompue (veille, redémarrage, tâche tuée) est plus court que ce que son
    en-tête annonce. On lit 100 octets, sans ouvrir la base (ouvrir une base en WAL crée des fichiers `-wal`/`-shm`)."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(100)
    except OSError:
        return False
    if len(head) < 100 or not head.startswith(_SQLITE_MAGIC):
        return False
    page_size = int.from_bytes(head[16:18], "big")
    if page_size == 1:
        page_size = 65536
    if page_size < 512 or size % page_size:
        return False
    if head[24:28] != head[92:96]:
        # Champ « taille en pages » périmé (SQLite ancien) : SQLite l'ignore aussi et compte d'après le fichier.
        return True
    return int.from_bytes(head[28:32], "big") * page_size == size


def latest_backup_age(dest_dir: Path | str | None = None, *, now: datetime | None = None) -> timedelta | None:
    """Âge de la sauvegarde COMPLÈTE la plus récente (horodatage lu dans le nom), ou `None` s'il n'y en a aucune
    (ou si le disque de données est absent)."""
    try:
        folder = Path(dest_dir) if dest_dir else paths.backups_dir()
    except paths.DataRootUnavailable:
        return None
    if not folder.is_dir():
        return None
    stamps: list[datetime] = []
    for path in folder.glob("patrick_backup_*.db"):
        m = _FILENAME_RE.match(path.name)
        if not m or not is_complete_backup(path):
            continue
        try:
            stamps.append(datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"))  # noqa: DTZ007
        except ValueError:
            continue
    if not stamps:
        return None
    return (now or datetime.now()) - max(stamps)  # noqa: DTZ005


def _delete_backup(path: Path) -> bool:
    """Supprime une sauvegarde et ses fichiers annexes (`-wal`, `-shm`, `-journal`). Vrai si le fichier a disparu."""
    try:
        path.unlink()
    except OSError:
        logger.warning("Impossible de supprimer la sauvegarde %s", path)
        return False
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass
    return True


def _purge_excess_backups(dest_dir: Path, keep: int, *, now: float | None = None) -> list[Path]:
    """Ne garde que les `keep` sauvegardes COMPLÈTES les plus récentes (ordre de l'horodatage du nom).

    Une copie complète pèse autant que la base (des dizaines de Go) : compter sur l'ancienneté seule
    (`_purge_old_backups`) laissait des dizaines de copies. Un fichier incomplet ne compte pas parmi les `keep`
    (il pousserait une bonne copie dehors) et est supprimé s'il n'a pas été touché depuis plus d'une heure, comme
    les copies `.part` et les fichiers annexes sans sauvegarde : plus jeunes, ils peuvent être une sauvegarde en
    cours. `keep <= 0` désactive le plafond. Retourne les fichiers supprimés."""
    if keep <= 0 or not dest_dir.exists():
        return []
    now_ts = time.time() if now is None else now
    complete: list[tuple[str, Path]] = []
    removed: list[Path] = []
    for path in dest_dir.glob("patrick_backup_*"):
        m = _FILENAME_RE.match(path.name)
        if m and is_complete_backup(path):
            complete.append((m.group(1), path))
            continue
        sidecar = _SIDECAR_RE.match(path.name)
        if sidecar and (dest_dir / sidecar.group(1)).exists():
            continue
        if not (m or sidecar or path.name.endswith(".db" + _PART_SUFFIX)):
            continue
        try:
            stale = now_ts - path.stat().st_mtime > _STALE_AFTER_SECONDS
        except OSError:
            continue
        if stale and _delete_backup(path):
            removed.append(path)
    complete.sort(reverse=True)
    for _, path in complete[keep:]:
        if _delete_backup(path):
            removed.append(path)
    return removed


def backup_database(
    source_path: str | None = None,
    backup_dir: str | None = None,
    *,
    pages: int = 100,
    sleep_s: float = 0.25,
    timestamp: str | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    keep: int = DEFAULT_KEEP_COUNT,
) -> Path:
    """Produit une copie horodatée et cohérente de la base SQLite située à
    `source_path` (défaut : `db.default_db_path()`, donc
    `$PATRICK_DB_PATH` ou `~/.patrick/patrick.db`) dans `backup_dir`
    (défaut : `paths.backups_dir()`, le dossier `backups` de la racine de
    données, créé si absent -- volontairement hors du dépôt git).

    Utilise `sqlite3.Connection.backup()` (voir docstring du module pour la
    justification vs. `shutil.copy` / `VACUUM INTO`). `pages`/`sleep_s`
    sont transmis à `Connection.backup()` pour copier par lots plutôt qu'en
    un seul bloc -- pertinent sur la vraie base (~4 Go), potentiellement
    écrite pendant la sauvegarde.

    Lève `FileNotFoundError` si `source_path` n'existe pas (rien à
    sauvegarder -- mieux vaut échouer bruyamment qu'écrire une "sauvegarde"
    vide silencieuse dans une tâche planifiée sans supervision). Si
    `Connection.backup()` échoue en cours de route (`sqlite3.Error`, p.ex.
    `sqlite3.OperationalError` sur une base source verrouillée), le fichier
    de destination partiel est supprimé avant de relever l'exception --
    mieux vaut aucune sauvegarde qu'une sauvegarde tronquée silencieusement
    laissée sur disque.

    Après une sauvegarde réussie, purge dans `backup_dir` les anciennes
    sauvegardes (motif `patrick_backup_<horodatage>.db`) dont l'horodatage
    dépasse `retention_days` jours (0 désactive la purge, défaut :
    `DEFAULT_RETENTION_DAYS` = 30) -- voir `_purge_old_backups` -- puis ne garde que les `keep` sauvegardes
    complètes les plus récentes (0 désactive le plafond, défaut : `DEFAULT_KEEP_COUNT` = 3) -- voir
    `_purge_excess_backups`. La copie s'écrit sous `<nom>.part` et ne prend son vrai nom qu'une fois terminée :
    un fichier `patrick_backup_*.db` est donc toujours complet (sauf anciens fichiers d'avant ce correctif).

    Retourne le chemin (`Path`) du fichier de sauvegarde effectivement créé.
    """
    src = source_path or default_db_path()
    if not os.path.exists(src):
        raise FileNotFoundError(f"Base source introuvable : {src}")

    dest_dir = Path(backup_dir or paths.backups_dir())
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    dest_path = dest_dir / _FILENAME_TEMPLATE.format(stamp=stamp)
    part_path = dest_path.with_name(dest_path.name + _PART_SUFFIX)

    def _log_progress(status: int, remaining: int, total: int) -> None:
        if total:
            done = total - remaining
            logger.info("backup: %d/%d pages copiees (%.1f%%)", done, total,
                        100.0 * done / total)

    source_conn = sqlite3.connect(src)
    try:
        dest_conn = sqlite3.connect(str(part_path))
        try:
            source_conn.backup(dest_conn, pages=pages, sleep=sleep_s, progress=_log_progress)
        finally:
            dest_conn.close()
    except sqlite3.Error:
        logger.error("Echec de sqlite3.Connection.backup(), suppression du fichier partiel : %s", part_path)
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                logger.warning("Impossible de supprimer le fichier de sauvegarde partiel : %s", part_path)
        raise
    finally:
        source_conn.close()

    os.replace(part_path, dest_path)

    removed = _purge_old_backups(dest_dir, retention_days)
    if removed:
        logger.info("Retention: %d ancienne(s) sauvegarde(s) supprimee(s) (> %d jours) : %s",
                    len(removed), retention_days, ", ".join(p.name for p in removed))

    excess = _purge_excess_backups(dest_dir, keep)
    if excess:
        logger.info("Plafond: %d fichier(s) de sauvegarde supprime(s) (on garde les %d plus recentes) : %s",
                    len(excess), keep, ", ".join(p.name for p in excess))

    return dest_path
