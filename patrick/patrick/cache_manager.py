from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def _cache_root() -> Path:
    return Path(os.environ.get("PATRICK_CACHE_ROOT", Path.home() / ".patrick" / "cache"))


class LocalCache:
    """Simple local cache for data, features and selections, with weekly refresh."""

    def __init__(self, root: str | None = None):
        self.root = Path(root) if root else _cache_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, key: str, suffix: str = ".parquet") -> Path:
        return self.root / f"{key}{suffix}"

    def _meta_path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def _write_meta(self, key: str, payload: dict) -> None:
        with open(self._meta_path(key), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    def _read_meta(self, key: str) -> dict:
        path = self._meta_path(key)
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _is_fresh(self, key: str, max_age_days: int = 7) -> bool:
        meta = self._read_meta(key)
        last = meta.get("updated_at")
        if not last:
            return False
        try:
            dt = datetime.fromisoformat(last)
            return datetime.utcnow() - dt < timedelta(days=max_age_days)
        except Exception:
            return False

    def save_dataframe(self, key: str, df: pd.DataFrame, *, max_age_days: int = 7) -> pd.DataFrame:
        path = self._file(key)
        df.to_parquet(path)
        self._write_meta(key, {"updated_at": datetime.utcnow().isoformat(), "rows": int(len(df)), "cols": int(df.shape[1])})
        return df

    def load_dataframe(self, key: str, *, max_age_days: int = 7) -> pd.DataFrame | None:
        path = self._file(key)
        if not path.exists() or not self._is_fresh(key, max_age_days=max_age_days):
            return None
        return pd.read_parquet(path)

    def save_json(self, key: str, payload: dict) -> None:
        path = self._file(key, suffix=".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        self._write_meta(key, {"updated_at": datetime.utcnow().isoformat()})

    def load_json(self, key: str, *, max_age_days: int = 7) -> dict | None:
        path = self._file(key, suffix=".json")
        if not path.exists() or not self._is_fresh(key, max_age_days=max_age_days):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def known_symbols(self, prefix: str = "universe") -> list[str]:
        out = []
        for p in self.root.glob(f"{prefix}*.parquet"):
            out.append(p.stem)
        return out
