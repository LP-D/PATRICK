from __future__ import annotations

import json
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa

from patrick import paths
from patrick.clock import parse_utc, utc_now


def _cache_root() -> Path:
    return paths.cache_dir()


# Un verrou par fichier, partagé par tous les `LocalCache` du processus. Sous Windows un fichier ouvert en lecture ne se remplace pas :
# deux lecteurs qui se relaient gardaient le fichier ouvert plus longtemps que les reprises de `_replace` (2,25 s), et l'écriture levait
# `PermissionError` (test `..._never_expose_a_torn_file` intermittent depuis octobre). Lecture et remplacement s'excluent maintenant.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


class LocalCache:
    """Simple local cache for data, features and selections, with weekly refresh."""

    def __init__(self, root: str | None = None):
        self.root = Path(root) if root else _cache_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, key: str, suffix: str = ".parquet") -> Path:
        return self.root / f"{key}{suffix}"

    def _meta_path(self, key: str) -> Path:
        return self.root / f"{key}.meta.json"

    @staticmethod
    def _replace(tmp: Path, path: Path) -> None:
        """`os.replace` avec reprises : sous Windows le fichier cible, ouvert en lecture un instant par un autre fil, refuse le remplacement."""
        for attempt in range(10):
            try:
                with _path_lock(path):               # aucun fil de CE processus ne lit le fichier pendant son remplacement
                    os.replace(tmp, path)
                return
            except PermissionError:                  # un AUTRE processus (worker, serveur) le lit : on réessaie
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _write_meta(self, key: str, payload: dict) -> None:
        # Atomique, comme le fichier de données : un lecteur ne voit jamais un fichier de métadonnées à moitié écrit, et deux écritures simultanées
        # de la même clé ne se disputent plus l'ouverture (PermissionError mesuré sous charge le 30/10 : trois écrivains et deux lecteurs).
        path = self._meta_path(key)
        tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            self._replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _read_meta(self, key: str) -> dict:
        path = self._meta_path(key)
        if not path.exists():
            return {}
        try:
            with _path_lock(path), open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _is_fresh(self, key: str, max_age_days: int = 7) -> bool:
        meta = self._read_meta(key)
        last = meta.get("updated_at")
        if not last:
            return False
        try:
            return utc_now() - parse_utc(last) < timedelta(days=max_age_days)
        except (TypeError, ValueError):
            return False

    def save_dataframe(self, key: str, df: pd.DataFrame, *, max_age_days: int = 7,
                       extra_meta: dict | None = None) -> pd.DataFrame:
        path = self._file(key)
        # Écriture atomique : fichier temporaire propre à ce fil puis remplacement. Deux écritures simultanées de la même clé (deux
        # requêtes web, un run et une page) ne produisent plus un fichier tronqué que le lecteur suivant ne saurait pas lire.
        tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        try:
            df.to_parquet(tmp)
            self._replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        self._write_meta(key, {"updated_at": utc_now().isoformat(), "rows": len(df),
                               "cols": int(df.shape[1]), **(extra_meta or {})})
        return df

    def read_meta(self, key: str) -> dict:
        return self._read_meta(key)

    def load_dataframe(self, key: str, *, max_age_days: int = 7) -> pd.DataFrame | None:
        path = self._file(key)
        if not path.exists() or not self._is_fresh(key, max_age_days=max_age_days):
            return None
        try:
            with _path_lock(path):
                return pd.read_parquet(path)
        except (OSError, ValueError, pa.ArrowException):
            return None                          # fichier tronqué ou corrompu : traité comme absent (il sera retéléchargé et réécrit)

    def save_json(self, key: str, payload: dict) -> None:
        path = self._file(key, suffix=".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        self._write_meta(key, {"updated_at": utc_now().isoformat()})

    def load_json(self, key: str, *, max_age_days: int = 7) -> dict | None:
        path = self._file(key, suffix=".json")
        if not path.exists() or not self._is_fresh(key, max_age_days=max_age_days):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

