"""Lecture d'un essai pour l'analyse : prédictions stockées, niveau de la cible (snapshot du run) et rendements futurs réalisés.

Tout est en LECTURE SEULE. Les prédictions se lisent par la clé primaire (`trial_id = ?`, `INDEXED BY sqlite_autoindex_prediction_1`) :
sans cette indication SQLite choisit `idx_pred_split` et balaie toute la table (> 100 s sur la vraie base, voir
`docs/superpowers/specs/2026-10-11-lots-pretes-a-lancer-design.md`).

Le niveau de la cible vient du snapshot exact du run (`DataStore`, colonne de la cible seule) : jamais le réseau, jamais le cache
de téléchargement (ce module n'écrit nulle part). Si le snapshot manque, les sections qui exigent un rendement le disent.
"""
from __future__ import annotations

import json
import os
import sqlite3
import types
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from patrick.analysis import stats_core as sc

EVAL_SPLITS = ("test", "test_path", "holdout", "live")
DISPLAY_SPLIT = {"test": "test", "test_path": "test", "holdout": "holdout", "live": "live"}
PRED_SQL = ("SELECT ts, fold_index, split, y_true, y_pred, y_proba, p_up, p_up_calibrated, path_id "
            "FROM prediction INDEXED BY sqlite_autoindex_prediction_1 WHERE trial_id = ? ORDER BY ts, path_id")


@dataclass
class Frame:
    """Tout ce qu'il faut pour analyser un essai. `df` : une ligne par prédiction ; voir `load_frame` pour les colonnes."""
    run: dict
    config: dict
    trial: dict
    horizon: int
    df: pd.DataFrame
    levels: pd.Series | None = None          # niveau de la cible (ou « niveau alpha » d'une cible alpha), index de dates
    fwd: pd.Series | None = None             # rendement futur à l'horizon, indexé comme `levels`
    daily: pd.Series | None = None           # rendement d'une barre, indexé comme `levels`
    is_alpha: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def is_cpcv(self) -> bool:
        return (self.config.get("validation") or {}).get("scheme") == "cpcv"

    def part(self, split: str) -> pd.DataFrame:
        """Lignes d'un échantillon affiché (`test` regroupe `test` et `test_path`)."""
        return self.df[self.df["split_name"] == split]

    @property
    def eval_df(self) -> pd.DataFrame:
        """Prédictions évaluables : test et holdout, avec classe réelle connue (le live en attente en est exclu)."""
        d = self.df
        return d[d["split_name"].isin(["test", "holdout"]) & d["yt"].notna()]


# ------------------------------------------------------------------------------------------------------------- base
def best_trial(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, params_json, artifact_path, category "
        "FROM trial WHERE run_id = ? AND is_best = 1 LIMIT 1", (run_id,)).fetchone()
    if row is None:
        return None
    keys = ("trial_id", "regime", "algo", "sampler", "n_features", "selector", "params_json", "artifact_path", "category")
    out = dict(zip(keys, row, strict=True))
    out["is_best"] = True
    return out


def get_trial(conn: sqlite3.Connection, run_id: str, trial_id: int) -> dict | None:
    row = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, params_json, artifact_path, category, is_best "
        "FROM trial WHERE run_id = ? AND trial_id = ?", (run_id, trial_id)).fetchone()
    if row is None:
        return None
    keys = ("trial_id", "regime", "algo", "sampler", "n_features", "selector", "params_json", "artifact_path", "category", "is_best")
    out = dict(zip(keys, row, strict=True))
    out["is_best"] = bool(out["is_best"])
    return out


def _outcome_class(y_true: float, split: str) -> float:
    """Classe réelle : le live stocke une direction binaire (1 hausse / 0 baisse), les autres échantillons la classe 0..3."""
    if y_true is None or (isinstance(y_true, float) and np.isnan(y_true)):
        return np.nan
    if split == "live":
        return np.nan                                   # direction connue seulement : pas de classe à 4 niveaux
    return float(round(float(y_true)))


def predictions_frame(conn: sqlite3.Connection, trial_id: int) -> pd.DataFrame:
    """Prédictions d'un essai, une ligne chacune.

    Colonnes : ts (Timestamp, jour), fold, split (valeur de la base), split_name (affiché : test/holdout/live), path, yt (classe réelle
    0..3, NaN si inconnue ou live), ut (direction réelle : 1.0 hausse, 0.0 baisse, NaN si inconnue), yp (classe prédite), up (direction
    prédite, booléen), conf (probabilité de la classe prédite), p_up (P(hausse)), p_cal (1 si P(hausse) est calibrée, sinon 0)."""
    rows = conn.execute(PRED_SQL, (trial_id,)).fetchall()
    cols = ["ts_raw", "fold", "split", "y_true", "yp", "conf", "p_up", "p_cal", "path"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        for c in ("ts", "split_name", "yt", "ut", "up"):
            df[c] = pd.Series(dtype=float)
        return df
    df["ts"] = pd.to_datetime(df["ts_raw"].astype(str).str.slice(0, 10), errors="coerce")
    df["split_name"] = df["split"].map(DISPLAY_SPLIT).fillna(df["split"])
    df["yt"] = [_outcome_class(y, s) for y, s in zip(df["y_true"], df["split"], strict=True)]
    ut = pd.Series(np.nan, index=df.index)
    known = df["y_true"].notna()
    live = df["split"] == "live"
    ut[known & ~live] = (df.loc[known & ~live, "y_true"].round() >= sc.UP_FROM).astype(float)
    ut[known & live] = (df.loc[known & live, "y_true"] >= 0.5).astype(float)
    df["ut"] = ut
    df["yp"] = df["yp"].round()
    df["up"] = df["yp"] >= sc.UP_FROM
    df["fold"] = df["fold"].fillna(0).astype(int)
    df["path"] = df["path"].fillna(-1).astype(int)
    for c in ("conf", "p_up", "p_cal"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.drop(columns=["y_true"])


# ------------------------------------------------------------------------------------------------------------ niveaux
def _snapshot_path(store, key: str, snapshot_id: str | None) -> tuple[str | None, str | None]:
    """Chemin du parquet du snapshot du run (sinon du plus récent de la clé) et une note si on a dû se rabattre."""
    entries = store.list_snapshots(key)
    chosen, note = None, None
    if snapshot_id:
        chosen = next((e for e in entries if e.get("snapshot_id") == snapshot_id), None)
    if chosen is None and entries:
        chosen = entries[-1]
        note = "snapshot_fallback"
    if chosen is None:
        return None, None
    candidates = [chosen.get("path")]
    sid = chosen.get("snapshot_id", "")
    parts = sid.split("__")
    if len(parts) >= 3:
        candidates.append(os.path.join(store.root, f"snapshot={parts[0]}", "__".join(parts[1:]) + ".parquet"))
    for p in candidates:
        if p and os.path.exists(p):
            return p, note
    return None, None


def _read_columns(path: str, wanted: list[str]) -> pd.DataFrame | None:
    import pyarrow.parquet as pq
    try:
        names = pq.read_schema(path).names
    except (OSError, ValueError):
        return None
    cols = [c for c in wanted if c in names]
    if not cols:
        return None
    try:
        df = pd.read_parquet(path, columns=cols)
    except (OSError, ValueError):
        return None
    df.index = pd.to_datetime(df.index)
    return df


def load_levels(run: dict, config: dict, store=None) -> tuple[pd.Series | None, pd.Series | None, list[str]]:
    """(niveaux de la cible, niveaux du benchmark pour une cible alpha, notes). `(None, None, [raison])` si introuvable."""
    from patrick.data.sources.yfinance_source import clean_symbol
    from patrick.data.store import DataStore
    obj = config.get("objective") or {}
    symbol = obj.get("target_symbol")
    if not symbol:
        return None, None, ["symbol_missing"]
    store = store or DataStore()
    label = run.get("target") or symbol
    key = f"raw_{label}"
    path, note = _snapshot_path(store, key, run.get("snapshot_id"))
    notes = [note] if note else []
    if path is None:
        return None, None, [f"snapshot_missing:{key}"]
    col = clean_symbol(symbol)
    wanted = [col]
    bench_col = None
    if obj.get("target_kind") == "alpha" and obj.get("benchmark"):
        bench_col = clean_symbol(obj["benchmark"])
        wanted.append(bench_col)
    df = _read_columns(path, wanted)
    if df is None or col not in df.columns:
        # certains snapshots anciens nomment la cible autrement : la première colonne est la cible par construction
        df = _read_columns(path, [_first_column(path)]) if _first_column(path) else None
        if df is None:
            return None, None, [*notes, "column_missing"]
        col = df.columns[0]
    levels = df[col].astype(float)
    levels = levels[~levels.index.duplicated(keep="last")].sort_index()
    bench = None
    if bench_col and bench_col in df.columns:
        bench = df[bench_col].astype(float)
        bench = bench[~bench.index.duplicated(keep="last")].sort_index()
    return levels, bench, notes


def _first_column(path: str) -> str | None:
    import pyarrow.parquet as pq
    try:
        names = [n for n in pq.read_schema(path).names if not n.startswith("__index_level")]
    except (OSError, ValueError):
        return None
    return names[0] if names else None


def forward_and_daily(levels: pd.Series, bench: pd.Series | None, config: dict, horizon: int) -> tuple[pd.Series, pd.Series, pd.Series, bool]:
    """(niveau de travail, rendement futur à `horizon`, rendement d'une barre, est_alpha).

    Cible brute : comme le pipeline (`s.shift(-h)/s - 1` sur la série remplie). Cible alpha : rendement excédentaire
    `actif - β_connu × benchmark` (`features/alpha_target.py`), le « niveau » étant le portefeuille long actif / short β benchmark."""
    obj = config.get("objective") or {}
    s = levels.ffill().bfill()
    if obj.get("target_kind") == "alpha" and bench is not None and obj.get("benchmark"):
        from patrick.features import alpha_target
        ns = types.SimpleNamespace(**{k: obj.get(k) for k in ("disable_session_lag", "benchmark", "target_symbol", "target_source")})
        lag = alpha_target.bench_lag(ns)
        fwd = alpha_target.alpha_labels(s, bench, horizon, bench_lag=lag)
        level, _beta = alpha_target.alpha_pair_level(s, bench, bench_lag=lag)
        return level, fwd, level.pct_change(), True
    return s, s.shift(-horizon) / s - 1.0, s.pct_change(), False


def load_frame(conn: sqlite3.Connection, run_id: str, trial_id: int | None = None, with_levels: bool = True, store=None) -> Frame | None:
    """Frame d'un run : essai gagnant (ou `trial_id` donné), prédictions, et si `with_levels` niveaux + rendements. `None` si le run
    ou son essai n'existe pas."""
    row = conn.execute("SELECT run_id, target, horizon, snapshot_id, config_json, started_at, finished_at, status, config_hash, "
                       "git_sha, seed, n_trials FROM run WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    keys = ("run_id", "target", "horizon", "snapshot_id", "config_json", "started_at", "finished_at", "status", "config_hash",
            "git_sha", "seed", "n_trials")
    run = dict(zip(keys, row, strict=True))
    config = json.loads(run["config_json"]) if run.get("config_json") else {}
    trial = best_trial(conn, run_id) if trial_id is None else get_trial(conn, run_id, trial_id)
    if trial is None:
        return None
    horizon = int(run["horizon"])
    df = predictions_frame(conn, trial["trial_id"])
    fr = Frame(run=run, config=config, trial=trial, horizon=horizon, df=df)
    if with_levels and not df.empty:
        levels, bench, notes = load_levels(run, config, store)
        fr.notes.extend(notes)
        if levels is not None:
            try:
                fr.levels, fwd, daily, fr.is_alpha = forward_and_daily(levels, bench, config, horizon)
                fr.fwd, fr.daily = fwd, daily
                fr.df = fr.df.copy()
                fr.df["ret"] = fr.df["ts"].map(fwd)
            except (ValueError, KeyError, TypeError) as exc:
                fr.notes.append(f"returns_failed:{exc}")
    if "ret" not in fr.df.columns:
        fr.df = fr.df.copy()
        fr.df["ret"] = np.nan
    return fr


def quick_split_counts(df: pd.DataFrame) -> dict:
    """Effectifs, première et dernière date de chaque échantillon affiché."""
    out = {}
    for name in ("test", "holdout", "live"):
        d = df[df["split_name"] == name]
        if d.empty:
            continue
        resolved = int(d["ut"].notna().sum())
        out[name] = {"n": len(d), "resolved": resolved, "pending": len(d) - resolved,
                     "start": d["ts"].min().strftime("%Y-%m-%d"), "end": d["ts"].max().strftime("%Y-%m-%d"),
                     "n_folds": int(d["fold"].nunique())}
    return out
