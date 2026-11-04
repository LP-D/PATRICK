"""Éviction des caches (ADR 0009) : plafond en taille, les moins récemment utilisés partent d'abord.

- `feature_cache` (pools de variables, fichiers Parquet de `features/pool_cache.py`, 126 Go le 28/10/2026) : `evict_feature_cache` retire
  les fichiers les plus anciennement LUS (la lecture met à jour la date du fichier) jusqu'à passer sous le plafond ;
- `vol_model_cache` / `shap_selection_cache` (dans la base) : `prune_db_caches` supprime les entrées plus vieilles que `max_age_days` ;
  `recompress_vol_cache` compresse (zlib, sans perte) les anciennes entrées en clair.

Tout ce qui est évincé se recalcule : l'éviction ne change aucun résultat, elle coûte du temps de calcul à la prochaine demande.
Les suppressions en masse dans la base ne se font jamais avec un worker vivant.
"""
from __future__ import annotations

import sqlite3
import time
import zlib
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from patrick import paths, settings

KEY_FEATURE_CACHE_MAX_GB = "feature_cache_max_gb"
DEFAULT_FEATURE_CACHE_MAX_GB = 150.0
KEY_VOL_CACHE_KEEP_DAYS = "vol_cache_keep_days"
DEFAULT_VOL_CACHE_KEEP_DAYS = 3      # 04/11/2026 : 751 678 entrées en 11 jours (base de 69 Go) quand rien ne les retirait
MIN_AGE_S = 3600                    # un fichier écrit ou lu depuis moins d'une heure peut servir à un run en cours : jamais évincé
DB_CACHE_TABLES = ("vol_model_cache", "shap_selection_cache")


def feature_cache_cap_bytes() -> int:
    value = settings.load().get(KEY_FEATURE_CACHE_MAX_GB, DEFAULT_FEATURE_CACHE_MAX_GB)
    try:
        return int(float(value) * 1e9)
    except (TypeError, ValueError):
        return int(DEFAULT_FEATURE_CACHE_MAX_GB * 1e9)


def vol_cache_keep_days() -> int:
    """Réglage `vol_cache_keep_days` : jours de snapshots gardés dans `vol_model_cache` par l'éviction de fin de job (0 : pas d'éviction)."""
    value = settings.load().get(KEY_VOL_CACHE_KEEP_DAYS, DEFAULT_VOL_CACHE_KEEP_DAYS)
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_VOL_CACHE_KEEP_DAYS


def _cache_files(root: Path) -> list[tuple[float, int, Path]]:
    out = []
    for path in root.rglob("*.parquet"):
        try:
            st = path.stat()
        except OSError:
            continue
        out.append((st.st_mtime, st.st_size, path))
    return out


def evict_feature_cache(max_bytes: int | None = None, root: Path | None = None, dry_run: bool = False,
                        now: float | None = None) -> dict:
    """Retire les fichiers les moins récemment utilisés jusqu'à ce que le dossier tienne sous `max_bytes`."""
    root = Path(root) if root is not None else paths.feature_cache_dir()
    cap = feature_cache_cap_bytes() if max_bytes is None else int(max_bytes)
    now = time.time() if now is None else now
    out = {"root": str(root), "files": 0, "bytes": 0, "cap": cap, "removed_files": 0, "removed_bytes": 0}
    if not root.is_dir():
        return out
    files = sorted(_cache_files(root))
    total = sum(size for _, size, _ in files)
    out.update(files=len(files), bytes=total)
    for mtime, size, path in files:
        if total <= cap:
            break
        if now - mtime < MIN_AGE_S:
            continue
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        total -= size
        out["removed_files"] += 1
        out["removed_bytes"] += size
    return out


def prune_db_caches(conn: sqlite3.Connection, max_age_days: int = 90, dry_run: bool = False, chunk: int = 5000) -> dict[str, int]:
    """Supprime les entrées de cache de la base plus vieilles que `max_age_days` (par paquets : le verrou d'écriture reste court)."""
    out = {}
    for table in DB_CACHE_TABLES:
        cutoff = f"-{int(max_age_days)} days"
        if dry_run:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE created_at < datetime('now', ?)", (cutoff,)).fetchone()[0]
            continue
        removed = 0
        while True:
            cur = conn.execute(f"DELETE FROM {table} WHERE rowid IN "
                               f"(SELECT rowid FROM {table} WHERE created_at < datetime('now', ?) LIMIT ?)", (cutoff, chunk))
            conn.commit()
            removed += cur.rowcount
            if cur.rowcount < chunk:
                break
        out[table] = removed
    return out


# `snapshot_id` commence par la date du snapshot (`AAAA-MM-JJ__<clé>__<empreinte>`, voir `DataStore`).
_DATED_SNAPSHOT = "snapshot_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'"


def evict_vol_cache(conn: sqlite3.Connection, keep_days: int | None = None, *, dry_run: bool = False, chunk: int = 2000,
                    today: date | None = None) -> int:
    """Supprime de `vol_model_cache` les entrées des snapshots datés de plus de `keep_days` jours (défaut : réglage
    `vol_cache_keep_days`, 3 ; 0 : rien). Retourne le nombre d'entrées retirées (à retirer, en `dry_run`).

    La sélection se fait sur la DATE DU SNAPSHOT, lue dans `snapshot_id` (début de la clé primaire, donc dans l'index), et non sur
    `created_at` : `created_at` est la dernière colonne de la ligne, derrière ~100 Ko de JSON ; la lire parcourt toute la chaîne de pages de
    débordement, soit toute la table (60 Go le 04/11/2026) à chaque passage. Un snapshot ne change jamais : une entrée de plus de quelques
    jours ne sert plus qu'à rejouer ce snapshot (reprise d'un run interrompu), qui la recalculera. Un identifiant qui ne commence pas par
    une date n'est jamais évincé.

    Par paquets de `chunk` lignes validés un à un (le verrou d'écriture reste court). Les pages libérées sont réutilisées par les écritures
    suivantes : le fichier cesse de grossir mais ne rétrécit que par `patrick storage vacuum`."""
    days = vol_cache_keep_days() if keep_days is None else keep_days
    if days <= 0:
        return 0
    cutoff = ((today or date.today()) - timedelta(days=days)).isoformat()  # noqa: DTZ011 -- date locale, comme celle des snapshots
    if dry_run:
        return conn.execute(f"SELECT COUNT(*) FROM vol_model_cache WHERE snapshot_id < ? AND {_DATED_SNAPSHOT}", (cutoff,)).fetchone()[0]
    removed = 0
    while True:
        cur = conn.execute("DELETE FROM vol_model_cache WHERE rowid IN "
                           f"(SELECT rowid FROM vol_model_cache WHERE snapshot_id < ? AND {_DATED_SNAPSHOT} LIMIT ?)", (cutoff, chunk))
        conn.commit()
        removed += cur.rowcount
        if cur.rowcount < chunk:
            return removed


def recompress_vol_cache(conn: sqlite3.Connection, chunk: int = 500, limit_rows: int | None = None,
                         progress: Callable[[int, int], None] | None = None) -> dict:
    """Compresse (zlib, sans perte) les entrées en clair de `vol_model_cache`. Reprenable : une entrée déjà compressée est sautée."""
    last, done, saved = 0, 0, 0
    while limit_rows is None or done < limit_rows:
        rows = conn.execute("SELECT rowid, result_json FROM vol_model_cache WHERE rowid > ? ORDER BY rowid LIMIT ?", (last, chunk)).fetchall()
        if not rows:
            break
        updates = []
        for rowid, stored in rows:
            last = rowid
            if isinstance(stored, str):
                packed = zlib.compress(stored.encode(), 6)
                saved += len(stored.encode()) - len(packed)
                updates.append((packed, rowid))
        if updates:
            conn.executemany("UPDATE vol_model_cache SET result_json = ? WHERE rowid = ?", updates)
            conn.commit()
        done += len(updates)
        if progress is not None:
            progress(done, saved)
    return {"recompressed": done, "bytes_saved": saved}
