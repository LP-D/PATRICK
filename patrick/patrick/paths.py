"""Emplacements des données de PATRICK sur ce PC : le seul module qui connaît `~/.patrick` et la racine de données.

Deux dossiers, deux rôles (spec 2026-10-21-donnees-sur-disque-d-design.md) :

- le **dossier maison** (`~/.patrick`, ou le dossier de `PATRICK_DB_PATH`) : la base active, les journaux, l'état de la
  machine ; il reste sur le disque rapide ;
- la **racine de données** (`PATRICK_DATA_ROOT`, sinon le réglage `data_root` de `settings.json`, sinon le dossier maison) :
  `store`, `models`, `feature_cache`, `cache`, `backups`, `archive`, `reports`.

Une variable propre à un composant (`PATRICK_STORE_ROOT`, `PATRICK_CACHE_ROOT`, `PATRICK_FEATURE_CACHE_ROOT`) l'emporte sur
tout le reste : c'est ce qui isole les tests et l'aperçu. Tout est relu à CHAQUE appel (comme `settings.py`) : un worker déjà
lancé voit un changement de réglage. Une racine configurée mais absente (disque débranché) lève `DataRootUnavailable` : on ne
recrée jamais silencieusement un second jeu de données sur le mauvais disque.
"""
from __future__ import annotations

import os
from pathlib import Path

from patrick import settings

ENV_DATA_ROOT = "PATRICK_DATA_ROOT"
KEY_DATA_ROOT = "data_root"


class DataRootUnavailable(RuntimeError):
    """La racine de données configurée n'existe pas (message destiné à l'utilisateur)."""


def home_dir() -> Path:
    """Dossier de la base active, des journaux et de l'état de la machine."""
    db = os.environ.get("PATRICK_DB_PATH")
    return Path(db).parent if db else Path.home() / ".patrick"


def db_path() -> str:
    """Base active : toujours dans le dossier maison, jamais sous la racine de données."""
    return os.environ.get("PATRICK_DB_PATH") or str(Path.home() / ".patrick" / "patrick.db")


def logs_dir() -> Path:
    return home_dir() / "logs"


def configured_data_root() -> Path | None:
    """Racine demandée (variable d'environnement, puis réglage), sans vérifier qu'elle existe."""
    env = os.environ.get(ENV_DATA_ROOT)
    if env:
        return Path(env)
    value = settings.load().get(KEY_DATA_ROOT)
    return Path(value) if isinstance(value, str) and value else None


def _unavailable_message(root: Path) -> str:
    return (f"Le disque de données {root} est introuvable. Branche-le, ou lance `patrick data use <dossier>` "
            "(ou `patrick data use --none`) pour changer de racine de données.")


def data_root() -> Path:
    """Racine configurée (elle doit exister), sinon le dossier maison."""
    configured = configured_data_root()
    if configured is None:
        return home_dir()
    if not configured.is_dir():
        raise DataRootUnavailable(_unavailable_message(configured))
    return configured


def data_root_missing() -> str | None:
    """Chemin de la racine configurée si elle est absente, sinon None."""
    configured = configured_data_root()
    return str(configured) if configured is not None and not configured.is_dir() else None


def data_root_problem() -> str | None:
    """Message expliqué si la racine configurée est absente, sinon None."""
    missing = data_root_missing()
    return _unavailable_message(Path(missing)) if missing else None


def _component(env_var: str | None, name: str) -> Path:
    override = os.environ.get(env_var) if env_var else None
    return Path(override) if override else data_root() / name


def store_dir() -> Path:
    return _component("PATRICK_STORE_ROOT", "store")


def cache_dir() -> Path:
    return _component("PATRICK_CACHE_ROOT", "cache")


def feature_cache_dir() -> Path:
    return _component("PATRICK_FEATURE_CACHE_ROOT", "feature_cache")


def models_dir() -> Path:
    return _component(None, "models")


def backups_dir() -> Path:
    return _component(None, "backups")


def archive_dir() -> Path:
    return _component(None, "archive")


def reports_dir() -> Path:
    return _component(None, "reports")
