"""Verrou entre processus sur un fichier, libéré par le système si le processus meurt.

`threading.Lock` ne protège qu'un processus. Or l'application (cycle des fonds après les prédictions), la tâche de nuit
(`daily_predict.py`) et la CLI (`patrick fund autopilot-run`) sont trois processus qui peuvent lancer le même travail en même
temps. Constaté le 22/11 : deux cycles du pilote simultanés risquaient de doubler les ordres.

Verrou de plage d'octets du système (`msvcrt.locking` sous Windows, `fcntl.flock` ailleurs) : contrairement à un fichier créé
en exclusif, il ne laisse pas de verrou périmé quand le processus est tué. L'octet verrouillé est loin au-delà de la fin du fichier
(vide) : une copie ou une lecture du fichier par un autre programme n'est jamais bloquée.
"""
from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


# Windows : octet verrouillé loin au-delà de la fin du fichier (vide). Un lecteur demande un bloc à partir de 0 (8 Kio pour Python) :
# un verrou à l'octet 0, même au-delà de la fin, lui renverrait « permission refusée ».
_WIN_OFFSET = 2**31 - 2


class LockTimeout(TimeoutError):
    """Le verrou est resté tenu par un autre processus au-delà du délai."""


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            os.lseek(fd, _WIN_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    with contextlib.suppress(OSError):
        if os.name == "nt":
            os.lseek(fd, _WIN_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path: str | os.PathLike, timeout_s: float = 0.0, poll_s: float = 0.5) -> Iterator[None]:
    """Tient le verrou `path` le temps du bloc. Attend au plus `timeout_s` secondes (0 = un seul essai), puis lève `LockTimeout`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise LockTimeout(f"verrou tenu par un autre processus : {path}")
            time.sleep(poll_s)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def sqlite_file(conn) -> str | None:
    """Chemin du fichier de la base principale d'une connexion SQLite, None pour une base en mémoire."""
    for _seq, name, file in conn.execute("PRAGMA database_list").fetchall():
        if name == "main":
            return file or None
    return None
