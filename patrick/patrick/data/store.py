"""Local Parquet data lake, partitioned by immutable snapshot -- replaces the
"latest known" cache (a file rewritten on every ingestion): yfinance/FRED
rewrite their own history (dividends, splits, revisions), so without a
content identity, two runs on different execution dates aren't comparable
even if "nothing changed". Every `save()` computes a content hash and writes
to a new `snapshot=<ingestion date>/` partition, never rewriting an existing
partition (Phase 0 anti-pattern: "overwrite an existing snapshot instead of
creating a new one") -- two ingestions on the same day with different
content produce two distinct files (different hash), two ingestions with
identical content resolve to the same snapshot_id (hash-based deduplication,
no useless duplicate on disk).

DuckDB (`query()`) reads the Parquet files directly with no import step --
useful for exploring/aggregating multiple snapshots via SQL without loading
them one by one into pandas memory.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from glob import glob

import pandas as pd

def _default_store_dir() -> str:
    """See `tracking.db.default_db_path`: read from the environment on EVERY
    call (not frozen at import time) so the worker (separate process) shares
    the same data lake as the web process that launched it, and for test
    isolation (`PATRICK_STORE_ROOT` set before instantiating `DataStore()`)."""
    return os.environ.get("PATRICK_STORE_ROOT") or os.path.expanduser("~/.patrick/store")


DEFAULT_STORE_DIR = _default_store_dir()  # value at module load time, for display/CLI only


def _content_hash(df: pd.DataFrame) -> str:
    """Deterministic hash of the CONTENT (values + index), not the write
    date -- two DataFrames with the same data produce the same hash
    regardless of when `save()` is called."""
    row_hashes = pd.util.hash_pandas_object(df, index=True).values
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:12]


class DataStore:
    def __init__(self, root: str | None = None):
        self.root = root or _default_store_dir()
        os.makedirs(self.root, exist_ok=True)

    def _safe_key(self, key: str) -> str:
        return key.replace("/", "_").replace("^", "IDX_")

    def _index_path(self) -> str:
        return os.path.join(self.root, "_index.json")

    def _partition_dir(self, snapshot_date: str) -> str:
        return os.path.join(self.root, f"snapshot={snapshot_date}")

    def _snapshot_path(self, key: str, snapshot_date: str, content_hash: str) -> str:
        return os.path.join(self._partition_dir(snapshot_date),
                             f"{self._safe_key(key)}__{content_hash}.parquet")

    def _read_index(self) -> dict:
        if os.path.exists(self._index_path()):
            with open(self._index_path()) as f:
                return json.load(f)
        return {}

    def _write_index(self, idx: dict) -> None:
        with open(self._index_path(), "w") as f:
            json.dump(idx, f, indent=1)

    def exists(self, key: str) -> bool:
        return bool(self._read_index().get(key, {}).get("snapshots"))

    def latest_snapshot_id(self, key: str) -> str | None:
        entries = self._read_index().get(key, {}).get("snapshots", [])
        return entries[-1]["snapshot_id"] if entries else None

    def load(self, key: str, snapshot_id: str | None = None) -> pd.DataFrame:
        entries = self._read_index().get(key, {}).get("snapshots", [])
        # Kept in French: these messages are interpolated verbatim into
        # webapp/app.py's French HTTPException detail (f"Données de la
        # cible introuvables : {exc}") -- an English message here would
        # produce a mixed-language error string in the French web UI.
        if not entries:
            raise FileNotFoundError(f"Aucun snapshot pour la clé '{key}'.")
        entry = entries[-1] if snapshot_id is None else next(
            (e for e in entries if e["snapshot_id"] == snapshot_id), None)
        if entry is None:
            raise FileNotFoundError(f"Snapshot '{snapshot_id}' introuvable pour la clé '{key}'.")
        df = pd.read_parquet(entry["path"])
        df.attrs["snapshot_id"] = entry["snapshot_id"]
        df.attrs["data_hash"] = entry["content_hash"]
        return df

    def save(self, key: str, df: pd.DataFrame) -> str:
        """Writes `df` to a new immutable partition (deduplicates by content
        hash: if an identical snapshot already exists for this key, reuses
        it rather than creating a new one). Returns the snapshot_id."""
        content_hash = _content_hash(df)
        idx = self._read_index()
        entries = idx.setdefault(key, {}).setdefault("snapshots", [])

        existing = next((e for e in entries if e["content_hash"] == content_hash), None)
        if existing is not None:
            return existing["snapshot_id"]

        snapshot_date = date.today().isoformat()
        snapshot_id = f"{snapshot_date}__{self._safe_key(key)}__{content_hash}"
        path = self._snapshot_path(key, snapshot_date, content_hash)
        os.makedirs(self._partition_dir(snapshot_date), exist_ok=True)
        df.to_parquet(path)

        entries.append({
            "snapshot_id": snapshot_id,
            "content_hash": content_hash,
            "path": path,
            "rows": int(len(df)),
            "cols": int(df.shape[1]) if df.ndim == 2 else 1,
            "date_min": str(df.index.min()) if len(df) else None,
            "date_max": str(df.index.max()) if len(df) else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write_index(idx)
        df.attrs["snapshot_id"] = snapshot_id
        df.attrs["data_hash"] = content_hash
        return snapshot_id

    def info(self) -> dict:
        return self._read_index()

    def query(self, sql: str) -> pd.DataFrame:
        """Executes `sql` via DuckDB (reads the Parquet files directly,
        without first reloading them into pandas) -- e.g. `store.query("SELECT * FROM "
        "read_parquet('~/.patrick/store/snapshot=*/*.parquet', "
        "hive_partitioning=true) LIMIT 10")`."""
        import duckdb

        return duckdb.sql(sql).df()

    def glob_pattern(self, key: str | None = None) -> str:
        """DuckDB glob pattern (`hive_partitioning=true`) covering all
        snapshots for a key (or all keys if `key` is omitted)."""
        pattern = f"{self._safe_key(key)}__*" if key else "*"
        return os.path.join(self.root, "snapshot=*", f"{pattern}.parquet")

    def list_snapshots(self, key: str | None = None) -> list[dict]:
        idx = self._read_index()
        if key is not None:
            return list(idx.get(key, {}).get("snapshots", []))
        out = []
        for k, v in idx.items():
            for e in v.get("snapshots", []):
                out.append({"key": k, **e})
        return out
