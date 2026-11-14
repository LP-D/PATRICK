"""Réserve partagée du cache de variables entre deux PC (ADR 0021).

Le cache de variables (`features/pool_cache.py`, des centaines de Go de fichiers `<clé>.parquet`) est un bon candidat au partage :
la clé est l'empreinte du CONTENU brut, du code des variables et des paramètres, donc deux PC qui calculent la même chose produisent
le même fichier. Mais le mettre tel quel sur un Google Drive coûterait cher : chaque lecture y met à jour la date du fichier (base
de l'éviction), l'éviction y supprime des fichiers (la corbeille de Google les garde 30 jours et les compte dans le quota), un
Drive figé bloquerait PATRICK, et chaque défaut de cache deviendrait un téléchargement.

D'où deux étages :
- le cache LOCAL, inchangé : celui que les runs lisent, et le seul que l'éviction vide ;
- une RÉSERVE PARTAGÉE (dossier d'un Drive, réglage `feature_cache_shared_root`) : consultée seulement quand le cache local n'a pas
  la clé, alimentée seulement par du neuf, jamais supprimée par le programme, plafonnée (`feature_cache_shared_max_gb`, 150 Go).

Tout est « au mieux » : une erreur de la réserve (Drive figé, `Errno 22`, disque plein) n'interrompt jamais un run, la clé est
simplement recalculée. Aucun fichier temporaire dans la réserve : chaque fichier y est écrit une fois sous son nom final (le
lecteur de l'autre PC ne le voit qu'une fois envoyé), et un fichier coupé est écarté à la lecture (`discard`)."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from patrick import paths, settings

KEY_MAX_GB = "feature_cache_shared_max_gb"
DEFAULT_MAX_GB = 150.0
STATE_NAME = "feature_cache_shared_state.json"
_SCAN_MAX_AGE_S = 24 * 3600              # un balayage de 50 000 fichiers sur un Drive : au plus un par jour
WAIT_STEP_S = 30.0


def max_bytes() -> int:
    value = settings.load().get(KEY_MAX_GB, DEFAULT_MAX_GB)
    try:
        return int(float(value) * 1e9)
    except (TypeError, ValueError):
        return int(DEFAULT_MAX_GB * 1e9)


def _free_bytes(path: Path) -> int:
    p = Path(path).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def available_memory_bytes() -> int:
    """Mémoire encore allouable. Windows : la limite « allouée » (RAM + fichier d'échange), celle qui a fait échouer l'amorçage du 14/11/2026
    (`MemoryError` sur un tampon de 1 Mo : l'interface web de Google Drive tenait 21 Go de mémoire privée) ; ailleurs : la mémoire
    disponible. Une mesure impossible ne bloque jamais (valeur énorme)."""
    if os.name == "nt":
        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullAvailPageFile)
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:                         # noqa: BLE001 -- une mesure qui échoue ne doit jamais arrêter une copie
        return 1 << 62


def scan_bytes(shared: Path) -> int:
    total = 0
    for p in Path(shared).rglob("*.parquet"):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def _state_path() -> Path:
    return paths.home_dir() / STATE_NAME


def _load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                                  # le suivi de taille est une aide : jamais bloquant


def shared_bytes(shared: Path, *, now: float | None = None) -> int:
    """Taille de la réserve : balayée au plus une fois par jour (50 000 fichiers sur un Drive), puis tenue à jour à chaque ajout."""
    now = time.time() if now is None else now
    state = _load_state()
    if state.get("root") == str(shared) and now - float(state.get("scanned_at", 0)) < _SCAN_MAX_AGE_S:
        return int(state.get("bytes", 0))
    total = scan_bytes(shared)
    _save_state({"root": str(shared), "bytes": total, "scanned_at": now})
    return total


def _add_bytes(shared: Path, n: int) -> None:
    state = _load_state()
    if state.get("root") == str(shared):
        state["bytes"] = int(state.get("bytes", 0)) + n
        _save_state(state)


def fetch(key: str, local_path: Path) -> bool:
    """Copie la clé de la réserve vers le cache local (défaut de cache) ; faux si elle n'y est pas ou si la copie échoue."""
    shared = paths.feature_cache_shared_dir()
    if shared is None:
        return False
    src = shared / key[:2] / f"{key}.parquet"
    try:
        if not src.is_file():
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".", suffix=".parquet.tmp", dir=local_path.parent)
        os.close(fd)
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, local_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return True
    except (OSError, MemoryError):
        return False


def discard(key: str, local_path: Path) -> None:
    """Retire des deux étages un fichier de la réserve qui ne se lit pas (envoi coupé côté Drive) : le prochain calcul de cette clé le
    republie. Seul cas où le programme supprime quelque chose dans la réserve : un fichier cassé, jamais un fichier valide."""
    local_path.unlink(missing_ok=True)
    shared = paths.feature_cache_shared_dir()
    if shared is None:
        return
    try:
        (shared / key[:2] / f"{key}.parquet").unlink(missing_ok=True)
    except OSError:
        pass


def publish(key: str, local_path: Path) -> bool:
    """Ajoute à la réserve un fichier du cache local qui n'y est pas encore (jamais d'écrasement : deux PC dont les versions de pyarrow
    n'écrivent pas les mêmes octets se renverraient le fichier indéfiniment) et seulement sous le plafond ; vrai si copié."""
    shared = paths.feature_cache_shared_dir()
    if shared is None:
        return False
    try:
        size = local_path.stat().st_size
        dest = shared / key[:2] / f"{key}.parquet"
        if dest.exists() or shared_bytes(shared) + size > max_bytes():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(local_path, dest)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        _add_bytes(shared, size)
        return True
    except (OSError, MemoryError):
        return False


def seed(local: Path, shared: Path, *, max_bytes: int, min_free_bytes: int,
         free_bytes: Callable[[Path], int] = _free_bytes, sleep: Callable[[float], None] = time.sleep,
         wait_max_s: float = 3600.0, dry_run: bool = False,
         progress: Callable[[int, int], None] | None = None,
         free_memory: Callable[[], int] | None = None, min_free_memory_bytes: int = 2 << 30) -> dict:
    """Copie le cache local vers la réserve, les fichiers les plus récents d'abord, jusqu'à `max_bytes` au total (déjà présent compris).

    Reprenable : un fichier présent avec la même taille est sauté, un fichier plus court (copie coupée) est recopié. Avant chaque copie,
    l'espace libre du disque de la réserve doit dépasser `min_free_bytes` (avec Google Drive « en streaming », c'est celui de `C:`, qui
    sert de cache au Drive) et la mémoire allouable `min_free_memory_bytes` (2 Go : un `MemoryError` est survenu le 14/11/2026, la
    mémoire de l'ordinateur étant saturée par l'interface web de Drive) ; sinon on attend (par pas de 30 s) jusqu'à `wait_max_s`,
    puis on s'arrête proprement. Un `MemoryError` en pleine copie retire le fichier coupé et arrête de la même façon.
    Retourne `copied_files`, `copied_bytes`, `skipped_files`, `shared_bytes`, `stopped` (`None`, `"plafond"`, `"espace"` ou `"memoire"`)."""
    local, shared = Path(local), Path(shared)
    entries = []
    for p in local.rglob("*.parquet"):
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, p))
    entries.sort(key=lambda e: e[0], reverse=True)

    total = scan_bytes(shared) if shared.exists() else 0
    out = {"copied_files": 0, "copied_bytes": 0, "skipped_files": 0, "shared_bytes": total, "stopped": None, "dry_run": dry_run}
    waited = 0.0
    memory = free_memory or available_memory_bytes             # relu à chaque appel (les tests le remplacent)

    def blocker() -> str | None:
        if free_bytes(shared) < min_free_bytes:
            return "espace"
        if memory() < min_free_memory_bytes:
            return "memoire"
        return None

    for _mtime, size, path in entries:
        dest = shared / path.relative_to(local)
        try:
            if dest.exists() and dest.stat().st_size == size:
                out["skipped_files"] += 1
                continue
        except OSError:
            pass
        if total + size > max_bytes:
            out["stopped"] = "plafond"
            break
        if not dry_run:
            while (why := blocker()) is not None:
                if waited >= wait_max_s:
                    out["stopped"] = why
                    break
                sleep(WAIT_STEP_S)
                waited += WAIT_STEP_S
            if out["stopped"]:
                break
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(path, dest)
            except MemoryError:
                dest.unlink(missing_ok=True)
                out["stopped"] = "memoire"
                break
            except BaseException:
                dest.unlink(missing_ok=True)
                raise
        total += size
        out["copied_files"] += 1
        out["copied_bytes"] += size
        if progress and out["copied_files"] % 500 == 0:
            progress(out["copied_files"], out["copied_bytes"])
    out["shared_bytes"] = total
    if not dry_run and out["copied_files"]:
        _save_state({"root": str(shared), "bytes": total, "scanned_at": time.time()})
    return out
