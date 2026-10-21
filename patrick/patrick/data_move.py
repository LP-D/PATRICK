"""`patrick data` : état, création et déplacement de la racine de données (spec 2026-10-21-donnees-sur-disque-d-design.md, §6).

La racine de données (`paths.data_root()`) porte `store`, `models`, `feature_cache`, `cache`, `backups`, `archive` et
`reports` ; la base active et les journaux restent dans le dossier maison. Ce module ne fait que lire l'état et déplacer :
tout emplacement se résout par `patrick.paths`.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from patrick import paths, sync
from patrick.desktop import prefs, runtime

COMPONENTS = ("store", "models", "feature_cache", "cache", "backups", "archive", "reports")
JOURNAL_NAME = "data_move_journal.json"           # anciennes valeurs de ce que `switch` réécrit (dans le dossier maison)
STATE_NAME = "data_move_state.json"               # avancement de la copie (dans le dossier maison)
README_NAME = "README.txt"
README_TEXT = ("Données de PATRICK de ce PC. Ne pas partager ni déplacer à la main : voir `patrick data status`.\n")

_COMPONENT_DIRS = {"store": paths.store_dir, "models": paths.models_dir, "feature_cache": paths.feature_cache_dir,
                   "cache": paths.cache_dir, "backups": paths.backups_dir, "archive": paths.archive_dir,
                   "reports": paths.reports_dir}


class MoveError(RuntimeError):
    """Opération refusée ou impossible, expliquée à l'utilisateur."""


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def component_path(name: str) -> Path:
    """Dossier actuel d'un composant ; si le disque de données manque, le dossier attendu (qui n'existe pas)."""
    try:
        return _COMPONENT_DIRS[name]()
    except paths.DataRootUnavailable:
        return paths.configured_data_root() / name


def _unresolved_artifacts(db_path: str) -> int:
    """`trial.artifact_path` absolus qui ne mènent à aucun fichier (les chemins relatifs dépendent du dossier de travail du worker)."""
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            rows = conn.execute("SELECT artifact_path FROM trial WHERE artifact_path IS NOT NULL AND artifact_path <> ''")
            return sum(1 for (p,) in rows if os.path.isabs(p) and not os.path.exists(p))
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _unresolved_store_entries(store: Path) -> int:
    """Snapshots de `_index.json` dont le fichier parquet est introuvable."""
    index = _read_json(store / "_index.json") or {}
    return sum(1 for value in index.values() for entry in (value or {}).get("snapshots", [])
               if not os.path.exists(entry.get("path", "")))


def status() -> dict:
    """Où sont les données de ce PC, combien de place il reste, et ce qui ne se résout plus (lecture seule)."""
    configured = paths.configured_data_root()
    available = paths.data_root_missing() is None
    home = paths.home_dir()
    volumes = [{"path": str(home), "free_gb": round(sync._free_bytes(home) / 1e9, 1)}]
    if configured is not None and available:
        volumes.append({"path": str(configured), "free_gb": round(sync._free_bytes(configured) / 1e9, 1)})
    components = [{"name": name, "path": str(component_path(name)), "exists": component_path(name).is_dir()}
                  for name in COMPONENTS]
    store = component_path("store")
    return {"data_root": str(configured) if configured is not None else None, "home": str(home), "db": paths.db_path(),
            "available": available, "volumes": volumes, "components": components,
            "unresolved": {"artifact_paths": _unresolved_artifacts(paths.db_path()),
                           "store_index": _unresolved_store_entries(store)},
            "progress": _read_json(home / STATE_NAME)}


def init_root(folder: str) -> Path:
    """Crée la racine de données, ses sept sous-dossiers et un `README.txt`. Le dossier parent doit exister (un lecteur
    absent ne se crée pas). N'écrit pas le réglage : c'est `move` qui le fait."""
    root = Path(folder)
    if not root.is_absolute():
        raise MoveError(f"Indique un chemin complet (par exemple D:\\PATRICK DATA), pas « {folder} ».")
    if not root.parent.is_dir():
        raise MoveError(f"Le dossier {root.parent} n'existe pas : le disque est-il branché ? Rien n'a été créé.")
    root.mkdir(exist_ok=True)
    for name in COMPONENTS:
        (root / name).mkdir(exist_ok=True)
    readme = root / README_NAME
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# Phase 1 : préconditions et copie
# --------------------------------------------------------------------------

_HASHED = ("store", "models")                     # petits (4,8 et 0,4 Go) : vérifiés par somme sha256
_SAME_MTIME_NS = 2_000_000_000                    # deux dates à moins de 2 s : même fichier (précision des systèmes de fichiers)
_TICK_FILES, _TICK_SECONDS = 200, 2.0             # fréquence d'écriture de l'avancement


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _inside(child, parent) -> bool:
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _tree(root: Path):
    """Chaque fichier sous `root` (sans suivre les liens)."""
    stack = [root]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)


def _tree_bytes(root: Path) -> int:
    total = 0
    for file in _tree(root):
        try:
            total += file.stat().st_size
        except OSError:
            continue
    return total


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check_preconditions(target: str, *, db_path: str | None = None, port: int | None = None) -> list[str]:
    """Raisons (en français) pour lesquelles `target` ne peut pas devenir la racine de données maintenant ; vide si tout va."""
    db_path = db_path or paths.db_path()
    root, home = Path(target), paths.home_dir()
    if not root.is_absolute():
        return [f"Indique un chemin complet (par exemple D:\\PATRICK DATA), pas « {target} »."]
    if (problem := paths.data_root_problem()):
        return [problem]
    source = paths.data_root()
    problems: list[str] = []
    configured = paths.configured_data_root()
    if configured is not None and _norm(configured) == _norm(root):
        problems.append(f"{target} est déjà la racine de données de ce PC.")
    if _inside(root, home):
        problems.append(f"{target} est dans le dossier maison de PATRICK ({home}), qui garde la base : choisis un autre dossier.")
    elif _inside(root, source):
        problems.append(f"{target} est dans la source de la copie ({source}) : choisis un autre dossier.")
    if _inside(home, root):
        problems.append(f"{target} contient le dossier maison de PATRICK ({home}) : choisis un dossier plus précis.")
    if _inside(source, root) and _norm(source) != _norm(home):
        problems.append(f"{target} contient la source de la copie ({source}) : choisis un dossier plus précis.")
    share = sync.configured_folder()
    if share and (_inside(root, share) or _inside(share, root)):
        problems.append(f"{target} chevauche le dossier de partage ({share}) : choisis un autre dossier.")
    if not root.parent.is_dir():
        problems.append(f"Le dossier {root.parent} n'existe pas : le disque est-il branché ?")
    if runtime.port_open(port or prefs.get_port()):
        problems.append("PATRICK est ouvert (le serveur écoute) : ferme-le d'abord.")
    try:
        if sync._job_running(db_path):
            problems.append("Un entraînement est en cours ou un worker est vivant : attends sa fin.")
    except sqlite3.Error as exc:
        problems.append(f"La base {db_path} est illisible ({exc}) : impossible de vérifier qu'aucun entraînement ne tourne.")
    needed = sum(_tree_bytes(source / name) for name in COMPONENTS if (source / name).is_dir())
    free = sync._free_bytes(root)
    if free < needed + sync.MIN_FREE_BYTES:
        problems.append(f"Pas assez d'espace libre sur le disque cible : il faut environ {sync._gb(needed + sync.MIN_FREE_BYTES)} Go, "
                        f"il en reste {sync._gb(free)}.")
    return problems


def _copy_file(src: Path, dst: Path) -> None:
    """Copie via un fichier `.part` puis renommage : une copie interrompue ne laisse jamais un fichier tronqué sous son vrai nom."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    shutil.copy2(src, part)
    os.replace(part, dst)


def _same_file(src: Path, dst: Path) -> bool:
    try:
        a, b = src.stat(), dst.stat()
    except OSError:
        return False
    return a.st_size == b.st_size and abs(a.st_mtime_ns - b.st_mtime_ns) < _SAME_MTIME_NS


def _drop_orphan_parts(src_dir: Path, dst_dir: Path) -> None:
    """Supprime les `.part` laissés par une copie interrompue (seulement ceux dont le fichier existe à la source)."""
    for part in dst_dir.rglob("*.part"):
        if (src_dir / part.with_name(part.name[: -len(".part")]).relative_to(dst_dir)).is_file():
            part.unlink(missing_ok=True)


def _verify_copy(src_root: Path, dst_root: Path, names: list[str]) -> None:
    for name in names:
        for file in _tree(src_root / name):
            rel = file.relative_to(src_root)
            copy = dst_root / rel
            if not copy.is_file() or copy.stat().st_size != file.stat().st_size:
                raise MoveError(f"Copie incomplète : {rel} est absent ou de taille différente dans {dst_root}.")
            if name in _HASHED and sync._sha256(file) != sync._sha256(copy):
                raise MoveError(f"Copie corrompue (sha256 différent) : {rel}.")


def copy_components(target: str, *, source_root: Path | None = None, progress=None) -> dict:
    """Phase 1 : copie les sept composants de la source vers `target`, sans rien modifier à la source. Reprenable : un fichier
    déjà là, de même taille et de même date, est sauté ; un fichier tronqué est recopié. Renvoie `{"files", "bytes", "skipped"}`
    (fichiers copiés, octets copiés, fichiers sautés). `progress(component, files_done, bytes_done, total_bytes)` est appelé
    régulièrement ; l'avancement est aussi écrit dans `STATE_NAME` (dossier maison)."""
    src_root = Path(source_root) if source_root is not None else paths.data_root()
    dst_root = init_root(target)
    names = [name for name in COMPONENTS if (src_root / name).is_dir()]
    total = sum(_tree_bytes(src_root / name) for name in names)
    state_path = paths.home_dir() / STATE_NAME
    done = {"files": 0, "bytes": 0, "skipped": 0}
    last = [time.monotonic()]

    def record(phase: str, component: str, *, force: bool = False) -> None:
        count = done["files"] + done["skipped"]
        if not force and time.monotonic() - last[0] < _TICK_SECONDS and count % _TICK_FILES:
            return
        last[0] = time.monotonic()
        _write_json(state_path, {"phase": phase, "component": component, "files_done": count, "bytes_done": done["bytes"],
                                 "total_bytes": total, "target": str(dst_root),
                                 "updated_at": datetime.now(UTC).isoformat(timespec="seconds")})
        if progress:
            progress(component, count, done["bytes"], total)

    record("copy", "", force=True)
    for name in names:
        src_dir, dst_dir = src_root / name, dst_root / name
        _drop_orphan_parts(src_dir, dst_dir)
        for file in _tree(src_dir):
            copy = dst_dir / file.relative_to(src_dir)
            if _same_file(file, copy):
                done["skipped"] += 1
            else:
                _copy_file(file, copy)
                done["files"] += 1
                done["bytes"] += file.stat().st_size
            record("copy", name)
    _verify_copy(src_root, dst_root, names)
    record("copied", "", force=True)
    return dict(done)
