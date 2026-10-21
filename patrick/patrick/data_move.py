"""`patrick data` : état, création et déplacement de la racine de données (spec 2026-10-21-donnees-sur-disque-d-design.md, §6).

La racine de données (`paths.data_root()`) porte `store`, `models`, `feature_cache`, `cache`, `backups`, `archive` et
`reports` ; la base active et les journaux restent dans le dossier maison. Ce module ne fait que lire l'état et déplacer :
tout emplacement se résout par `patrick.paths`.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from patrick import paths, sync

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
