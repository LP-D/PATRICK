"""Archivage des prédictions du scan (ADR 0009).

92 % des lignes de `prediction` (25,5 M sur 27,8 M le 28/10/2026) sont les prédictions de test de CHAQUE essai du scan : des centaines
d'essais par run, dont presque aucun n'est jamais relu. Les lecteurs (synthèse, page d'un run, équilibre des classes, simulateur,
duel de champions, PBO via `fold_metric`) ne lisent que le MEILLEUR essai d'un run, son champion et quelques essais de tête. Ici :

- on garde en SQLite, par run, le meilleur essai (`is_best`) et les `top_k` essais de plus haut F1_dir moyen sur les plis ;
- les prédictions `test` / `test_path` / `valid` des autres essais vont dans un fichier Parquet par run (`<archive>/predictions/<run_id>.parquet`,
  zstd) puis sont supprimées de la base ; rien n'est perdu (`restore_run` les remet) ;
- les prédictions `holdout` et `live` ne sont jamais touchées ; `fold_metric` non plus (le PBO s'appuie sur elle).

L'archivage automatique se fait en fin de job dans le worker, pour les runs de ce job. L'archivage de l'existant et la maintenance de la base
(index, ANALYZE, VACUUM) se font par `patrick archive-predictions`, jamais avec un worker vivant (suppressions en masse : voir la note
« pas de maintenance de base pendant un run »).
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from patrick import paths

SCAN_SPLITS = ("test", "test_path", "valid")
DEFAULT_TOP_K = 5
ENV_KEEP_ALL = "PATRICK_KEEP_SCAN_PREDICTIONS"          # "1" : n'archive rien (benchmarks, comparaisons bit à bit)
COLUMNS = ("trial_id", "ts", "fold_index", "split", "y_true", "y_pred", "y_proba", "path_id", "p_up")
_TRIAL_CHUNK = 100
_DELETE_COMMIT_EVERY = 20


def enabled() -> bool:
    return os.environ.get(ENV_KEEP_ALL, "").lower() not in ("1", "true", "yes")


def archive_root(root: str | Path | None = None) -> Path:
    return Path(root) if root is not None else paths.archive_dir() / "predictions"


def archive_path(run_id: str, root: str | Path | None = None) -> Path:
    return archive_root(root) / f"{run_id}.parquet"


def keep_trials(conn: sqlite3.Connection, run_id: str, top_k: int = DEFAULT_TOP_K) -> set[int]:
    """Essais dont les prédictions de scan restent en base : le meilleur du run et les `top_k` de plus haut F1_dir moyen (plis de test)."""
    keep = {t for (t,) in conn.execute("SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1", (run_id,))}
    if top_k > 0:
        keep |= {t for (t,) in conn.execute(
            "SELECT fm.trial_id FROM fold_metric fm JOIN trial t ON t.trial_id = fm.trial_id "
            "WHERE t.run_id = ? AND fm.split IN ('test', 'test_path') AND fm.metric = 'F1_dir' "
            "GROUP BY fm.trial_id ORDER BY AVG(fm.value) DESC, fm.trial_id LIMIT ?", (run_id, top_k))}
    return keep


def _scan_where(trial_ids: list[int]) -> tuple[str, list]:
    marks = ",".join("?" for _ in trial_ids)
    splits = ",".join("?" for _ in SCAN_SPLITS)
    return f"trial_id IN ({marks}) AND split IN ({splits})", [*trial_ids, *SCAN_SPLITS]


def _chunks(items: list[int], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _read_rows(conn: sqlite3.Connection, trial_ids: list[int]) -> pd.DataFrame:
    where, params = _scan_where(trial_ids)
    rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM prediction INDEXED BY sqlite_autoindex_prediction_1 WHERE {where}",
                        params).fetchall()
    return pd.DataFrame(rows, columns=list(COLUMNS))


def _count_rows(conn: sqlite3.Connection, trial_ids: list[int]) -> int:
    where, params = _scan_where(trial_ids)
    return int(conn.execute(f"SELECT COUNT(*) FROM prediction INDEXED BY sqlite_autoindex_prediction_1 WHERE {where}",
                            params).fetchone()[0])


def _write_parquet(frame: pd.DataFrame, path: Path) -> int:
    """Écriture atomique ; renvoie le nombre de lignes relu dans le fichier (vérification avant toute suppression)."""
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    try:
        frame.to_parquet(tmp, index=False, compression="zstd")
        n = pq.read_metadata(tmp).num_rows
        os.replace(tmp, path)
        return int(n)
    finally:
        if tmp.exists():
            tmp.unlink()


def archive_run(conn: sqlite3.Connection, run_id: str, *, top_k: int = DEFAULT_TOP_K, root: str | Path | None = None,
                dry_run: bool = False) -> dict:
    """Archive puis supprime les prédictions de scan des essais de `run_id` qui ne sont ni le meilleur ni dans le top `top_k`.
    Renvoie `{run_id, kept_trials, trials, rows, deleted, bytes, path}` ; `dry_run` ne lit que des comptes."""
    keep = keep_trials(conn, run_id, top_k)
    trial_ids = [t for (t,) in conn.execute("SELECT trial_id FROM trial WHERE run_id = ? ORDER BY trial_id", (run_id,))
                 if t not in keep]
    out = {"run_id": run_id, "kept_trials": len(keep), "trials": len(trial_ids), "rows": 0, "deleted": 0, "bytes": 0, "path": None}
    if not trial_ids:
        return out
    if dry_run:
        out["rows"] = sum(_count_rows(conn, chunk) for chunk in _chunks(trial_ids, _TRIAL_CHUNK))
        return out
    frames = [f for chunk in _chunks(trial_ids, _TRIAL_CHUNK) if len(f := _read_rows(conn, chunk))]
    if not frames:
        return out
    new = pd.concat(frames, ignore_index=True)
    path = archive_path(run_id, root)
    frame = new
    if path.exists():                                   # une archive précédente (essai relancé) : on fusionne sans doublon
        old = pd.read_parquet(path)
        frame = pd.concat([old, new], ignore_index=True).drop_duplicates(["trial_id", "ts", "split", "path_id"], keep="last")
    written = _write_parquet(frame, path)
    if written != len(frame):
        raise RuntimeError(f"archive {path} incomplète ({written} lignes relues sur {len(frame)}) : rien n'est supprimé")
    out.update(rows=len(new), path=str(path), bytes=path.stat().st_size)
    deleted = 0
    where_cache: dict[int, str] = {}
    for i, chunk in enumerate(_chunks(trial_ids, _TRIAL_CHUNK)):
        where, params = _scan_where(chunk)
        where_cache[len(chunk)] = where
        cur = conn.execute(f"DELETE FROM prediction INDEXED BY sqlite_autoindex_prediction_1 WHERE {where}", params)
        deleted += cur.rowcount
        if (i + 1) % _DELETE_COMMIT_EVERY == 0:
            conn.commit()
    conn.commit()
    out["deleted"] = deleted
    return out


def restore_run(conn: sqlite3.Connection, run_id: str, root: str | Path | None = None) -> int:
    """Remet en base les prédictions archivées d'un run (sans écraser ce qui y est déjà) ; renvoie le nombre de lignes lues."""
    path = archive_path(run_id, root)
    if not path.exists():
        return 0
    frame = pd.read_parquet(path)
    marks = ",".join("?" for _ in COLUMNS)
    rows = [tuple(None if pd.isna(v) else v for v in r) for r in frame[list(COLUMNS)].itertuples(index=False, name=None)]
    with conn:
        conn.executemany(f"INSERT OR IGNORE INTO prediction ({', '.join(COLUMNS)}) VALUES ({marks})", rows)
    return len(rows)


def archive_runs(conn: sqlite3.Connection, run_ids: list[str], *, top_k: int = DEFAULT_TOP_K, root: str | Path | None = None,
                 dry_run: bool = False, progress: Callable[[dict], None] | None = None) -> list[dict]:
    results = []
    for run_id in run_ids:
        result = archive_run(conn, run_id, top_k=top_k, root=root, dry_run=dry_run)
        results.append(result)
        if progress is not None:
            progress(result)
    return results


def finished_run_ids(conn: sqlite3.Connection) -> list[str]:
    """Runs terminés (`done`) ; les runs en cours et en échec ne sont jamais archivés."""
    return [r for (r,) in conn.execute("SELECT run_id FROM run WHERE status = 'done' ORDER BY started_at")]


def archive_job_runs(conn: sqlite3.Connection, job_id: str, *, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Archivage automatique de fin de job (worker) : les runs `done` de ce job. Ne fait jamais échouer le job."""
    if not enabled():
        return []
    try:
        run_ids = [r for (r,) in conn.execute("SELECT run_id FROM run WHERE job_id = ? AND status = 'done'", (job_id,))]
        return archive_runs(conn, run_ids, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 -- l'archivage est de l'entretien : il ne doit jamais faire échouer un job terminé
        print(f"[ARCHIVE] prédictions de scan non archivées : {type(exc).__name__}: {exc}")
        return []


# --------------------------------------------------------------------------- index (entretien, worker arrêté)

LIVE_INDEX = "idx_pred_live"


def live_index_hint(conn: sqlite3.Connection) -> str:
    """Nom de l'index à imposer pour lire les prédictions `live` par date : le partiel s'il existe, sinon `idx_pred_split`."""
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'prediction'")}
    return LIVE_INDEX if LIVE_INDEX in names else "idx_pred_split"


def reindex_predictions(conn: sqlite3.Connection) -> list[str]:
    """`idx_pred_path` supprimé (path_id vaut -1 hors CPCV : presque jamais utile) ; `idx_pred_split(split, ts)` remplacé par un index
    PARTIEL sur les seules lignes `live`. Chaque ligne de scan écrite n'a plus trois index à mettre à jour, et l'index tient dans le cache."""
    done = []
    conn.execute(f"CREATE INDEX IF NOT EXISTS {LIVE_INDEX} ON prediction(ts, trial_id) WHERE split = 'live'")
    done.append(f"index {LIVE_INDEX} créé")
    for name in ("idx_pred_path", "idx_pred_split"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone():
            conn.execute(f"DROP INDEX {name}")
            done.append(f"index {name} supprimé")
    conn.commit()
    return done


def optimize_planner(conn: sqlite3.Connection, analysis_limit: int = 1000) -> None:
    """Statistiques du planificateur (`sqlite_stat1`, absent de la base jusqu'ici) : `ANALYZE` borné par `analysis_limit` lignes par index."""
    conn.execute(f"PRAGMA analysis_limit = {int(analysis_limit)}")
    conn.execute("ANALYZE")
    conn.commit()
