"""Diagnostics système en lecture seule : processeur, mémoire, disques, processus PATRICK (serveur, worker), base de suivi, file de jobs, dossiers de
données et journaux (dernières lignes). Rien n'est modifié, aucun processus n'est arrêté d'ici.

Les tailles de dossiers se calculent avec un budget de temps (le cache de variables fait plusieurs Go en milliers de fichiers) et sont gardées
deux minutes ; au-delà du budget, la taille est donnée comme partielle."""
from __future__ import annotations

import contextlib
import os
import platform
import re
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from patrick import paths

SIZE_BUDGET_S = 6.0
SIZE_TTL_S = 120.0
LOG_TAIL_BYTES = 400_000
MAX_LOG_LINES = 500
_NAME = re.compile(r"^[\w.\-]+$")
_size_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def home() -> Path:
    return paths.home_dir()


def logs_dir() -> Path:
    return paths.logs_dir()


def _data_folder(name: str, folder) -> str:
    """Chemin d'un dossier de données ; si le disque de données manque, le chemin attendu (listé comme absent)."""
    try:
        return str(folder())
    except paths.DataRootUnavailable:
        return str(paths.configured_data_root() / name)


def system() -> dict:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    disks = []
    seen = set()
    data_root = paths.configured_data_root()
    data_places = [str(home()).lower()] + ([str(data_root).lower()] if data_root else [])      # base ET données
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype or part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append({"mount": part.mountpoint, "total": u.total, "used": u.used, "free": u.free, "percent": u.percent,
                      "holds_data": any(place.startswith(part.mountpoint.lower()) for place in data_places)})
    freq = None
    with contextlib.suppress(Exception):
        f = psutil.cpu_freq()
        freq = f.current if f else None
    return {"cpu_percent": psutil.cpu_percent(interval=0.25), "cpu_per_core": psutil.cpu_percent(interval=None, percpu=True), "cpu_count": psutil.cpu_count(logical=True),
            "cpu_physical": psutil.cpu_count(logical=False), "cpu_freq_mhz": freq,
            "memory": {"total": vm.total, "available": vm.available, "percent": vm.percent}, "swap": {"total": sw.total, "used": sw.used, "percent": sw.percent},
            "disks": disks, "boot_time": datetime.fromtimestamp(psutil.boot_time(), UTC).strftime("%Y-%m-%d %H:%M"),
            "python": sys.version.split()[0], "platform": platform.platform(), "home": str(home())}


def processes() -> list[dict]:
    """Processus Python de PATRICK : serveur web (uvicorn / `patrick serve`), worker de jobs, autres."""
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "create_time", "cpu_percent"]):
        try:
            info = p.info
            name = (info["name"] or "").lower()
            if "python" not in name:
                continue
            cmd = " ".join(info["cmdline"] or [])
            low = cmd.lower()
            if "patrick" not in low and "uvicorn" not in low:
                continue
            role = "worker" if " worker" in low or "cli worker" in low else ("server" if ("serve" in low or "uvicorn" in low) else "other")
            out.append({"pid": info["pid"], "name": info["name"], "role": role, "cmd": cmd[:220], "rss": info["memory_info"].rss if info["memory_info"] else None,
                        "started": datetime.fromtimestamp(info["create_time"], UTC).strftime("%Y-%m-%d %H:%M"), "cpu": info["cpu_percent"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    out.sort(key=lambda r: (r["role"], -(r["rss"] or 0)))
    return out


def app_state(conn: sqlite3.Connection) -> dict:
    from patrick.tracking import db as trackdb
    db_path = trackdb.default_db_path()
    files = {}
    for suffix in ("", "-wal", "-shm"):
        f = db_path + suffix
        if os.path.exists(f):
            files[suffix or "db"] = os.path.getsize(f)
    jobs = dict(conn.execute("SELECT status, COUNT(*) FROM job GROUP BY status"))
    hb = conn.execute("SELECT pid, updated_at FROM worker_heartbeat WHERE id = 1").fetchone()
    heartbeat = None
    if hb:
        age = None
        try:
            age = (datetime.now(UTC).replace(tzinfo=None) - datetime.fromisoformat(str(hb[1]).replace(" ", "T"))).total_seconds()
        except ValueError:
            age = None
        heartbeat = {"pid": hb[0], "updated_at": hb[1], "age_s": age, "alive": bool(psutil.pid_exists(hb[0]))}
    runs = dict(conn.execute("SELECT status, COUNT(*) FROM run GROUP BY status"))
    from patrick.tracking import db as _db
    return {"db_path": db_path, "db_files": files, "jobs": jobs, "runs": runs, "heartbeat": heartbeat, "git": _db.current_git_sha(), "version": _version(),
            "schema_version": conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]}


def _version() -> str | None:
    try:
        from importlib.metadata import version
        return version("patrick")
    except Exception:  # noqa: BLE001 -- paquet non installé en mode éditable : version inconnue, pas une erreur
        return None


def _dir_size(path: Path, deadline: float) -> tuple[int, int, bool]:
    total = files = 0
    stack = [str(path)]
    while stack:
        if time.monotonic() > deadline:
            return total, files, True
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files, False


def storage() -> dict:
    """Taille des dossiers de données (cache de téléchargement, cache de variables, lac de données, modèles, sauvegardes, journaux, archives)."""
    dirs = {"cache": _data_folder("cache", paths.cache_dir), "feature_cache": _data_folder("feature_cache", paths.feature_cache_dir),
            "store": _data_folder("store", paths.store_dir), "models": _data_folder("models", paths.models_dir),
            "backups": _data_folder("backups", paths.backups_dir), "logs": str(paths.logs_dir()),
            "archive": _data_folder("archive", paths.archive_dir)}
    key = "|".join(dirs.values())
    with _lock:
        hit = _size_cache.get(key)
    if hit and time.monotonic() - hit[0] < SIZE_TTL_S:
        return hit[1]
    deadline = time.monotonic() + SIZE_BUDGET_S
    items = []
    for name, p in dirs.items():
        path = Path(p)
        if not path.exists():
            items.append({"name": name, "path": p, "exists": False, "bytes": 0, "files": 0, "partial": False})
            continue
        size, n, partial = _dir_size(path, deadline)
        items.append({"name": name, "path": p, "exists": True, "bytes": size, "files": n, "partial": partial})
    res = {"items": items, "total": sum(i["bytes"] for i in items), "partial": any(i["partial"] for i in items)}
    with _lock:
        _size_cache[key] = (time.monotonic(), res)
    return res


def list_logs() -> list[dict]:
    d = logs_dir()
    if not d.is_dir():
        return []
    out = []
    for f in d.iterdir():
        try:
            if f.is_file() and _NAME.match(f.name):
                st = f.stat()
                out.append({"name": f.name, "bytes": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%d %H:%M")})
        except OSError:
            continue
    out.sort(key=lambda r: r["modified"], reverse=True)
    return out[:80]


def tail_log(name: str, lines: int = 200) -> dict | None:
    """Dernières lignes d'un journal du dossier des journaux. `None` si le nom est invalide ou absent (aucun chemin n'est accepté, seulement un nom)."""
    if not _NAME.match(name or ""):
        return None
    path = logs_dir() / name
    try:
        if not path.is_file() or path.resolve().parent != logs_dir().resolve():
            return None
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - LOG_TAIL_BYTES))
            raw = fh.read()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace").splitlines()
    n = max(1, min(MAX_LOG_LINES, lines))
    return {"name": name, "bytes": size, "lines": text[-n:], "truncated": size > LOG_TAIL_BYTES or len(text) > n}
