"""Data lake local en Parquet, partitionné par snapshot immuable — remplace le
cache "dernier connu" (un fichier réécrit à chaque ingestion) : yfinance/FRED
réécrivent leur propre historique (dividendes, splits, révisions), donc sans
identité de contenu, deux runs à des dates d'exécution différentes ne sont pas
comparables même si "rien n'a changé". Chaque `save()` calcule un hash du
contenu et écrit dans une nouvelle partition `snapshot=<date d'ingestion>/`,
sans jamais réécrire une partition existante (anti-pattern Phase 0 : "écraser
un snapshot existant au lieu d'en créer un nouveau") — deux ingestions le même
jour avec un contenu différent produisent deux fichiers distincts (hash
différent), deux ingestions avec un contenu identique retrouvent le même
snapshot_id (déduplication par hash, pas de doublon inutile sur disque).

DuckDB (`query()`) lit directement les Parquet sans étape d'import — utile pour
explorer/agréger plusieurs snapshots par SQL sans les recharger un par un en
mémoire pandas.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from glob import glob

import pandas as pd

DEFAULT_STORE_DIR = os.path.expanduser("~/.patrick/store")


def _content_hash(df: pd.DataFrame) -> str:
    """Hash déterministe du CONTENU (valeurs + index), pas de la date d'écriture
    — deux DataFrames avec les mêmes données produisent le même hash quel que
    soit le moment où `save()` est appelé."""
    row_hashes = pd.util.hash_pandas_object(df, index=True).values
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:12]


class DataStore:
    def __init__(self, root: str = DEFAULT_STORE_DIR):
        self.root = root
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
        """Écrit `df` dans une nouvelle partition immuable (déduplique par hash de
        contenu : si un snapshot identique existe déjà pour cette clé, le
        réutilise plutôt que d'en créer un nouveau). Retourne le snapshot_id."""
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
        """Exécute `sql` via DuckDB (lit les Parquet directement, sans les
        recharger en pandas au préalable) — ex. `store.query("SELECT * FROM "
        "read_parquet('~/.patrick/store/snapshot=*/*.parquet', "
        "hive_partitioning=true) LIMIT 10")`."""
        import duckdb

        return duckdb.sql(sql).df()

    def glob_pattern(self, key: str | None = None) -> str:
        """Motif glob DuckDB (`hive_partitioning=true`) couvrant tous les
        snapshots d'une clé (ou de toutes les clés si `key` omis)."""
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
