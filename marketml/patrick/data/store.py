"""Data lake local en Parquet — remplace le hack Colab "push chaque checkpoint sur
une branche Git" : ici le disque est persistant, un fichier Parquet par jeu de
données suffit, avec un petit index JSON pour savoir ce qui est déjà présent et
jusqu'à quelle date.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

DEFAULT_STORE_DIR = os.path.expanduser("~/.patrick/store")


class DataStore:
    def __init__(self, root: str = DEFAULT_STORE_DIR):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = key.replace("/", "_").replace("^", "IDX_")
        return os.path.join(self.root, f"{safe}.parquet")

    def _index_path(self) -> str:
        return os.path.join(self.root, "_index.json")

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def load(self, key: str) -> pd.DataFrame:
        return pd.read_parquet(self._path(key))

    def save(self, key: str, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(key))
        self._touch_index(key, df)

    def _touch_index(self, key: str, df: pd.DataFrame) -> None:
        idx = {}
        if os.path.exists(self._index_path()):
            with open(self._index_path()) as f:
                idx = json.load(f)
        idx[key] = {
            "rows": int(len(df)),
            "cols": int(df.shape[1]) if df.ndim == 2 else 1,
            "date_min": str(df.index.min()) if len(df) else None,
            "date_max": str(df.index.max()) if len(df) else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._index_path(), "w") as f:
            json.dump(idx, f, indent=1)

    def info(self) -> dict:
        if not os.path.exists(self._index_path()):
            return {}
        with open(self._index_path()) as f:
            return json.load(f)
