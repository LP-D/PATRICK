"""Exécution d'UN scénario (profil x schéma) dans un espace de travail isolé :
snapshot, base SQLite, cache de features, dossier Optuna neufs -> départ à froid.

Partagé par la CLI (`python -m patrick.benchmark`) et les tests.
"""
from __future__ import annotations

import gc
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from patrick.benchmark import artifacts, profiler, reference
from patrick.data.store import DataStore
from patrick.pipeline import engine

ISOLATED_ENV = ("PATRICK_DB_PATH", "PATRICK_STORE_ROOT", "PATRICK_CACHE_ROOT", "PATRICK_FEATURE_CACHE_ROOT")


@contextmanager
def _env(values: dict[str, str]):
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def _offline_ohlc():
    """`download_ohlc` (réseau Yahoo) est remplacé par un no-op déterministe,
    exactement comme `tests/test_run_pipeline_golden.py` : le téléchargement
    n'est donc PAS mesuré (documenté dans le rapport)."""
    orig = engine.download_ohlc
    engine.download_ohlc = lambda *a, **k: None
    try:
        yield
    finally:
        engine.download_ohlc = orig


def prepare_snapshot(spec: reference.ProfileSpec, store_root: str) -> tuple[DataStore, str, str, tuple]:
    raw = reference.make_raw(spec.dataset)
    store = DataStore(root=store_root)
    key = f"raw_{reference.TARGET_SYMBOL}"
    snapshot_id = store.save(key, raw)
    return store, snapshot_id, raw.attrs.get("data_hash", ""), raw.shape


def run_scenario(spec: reference.ProfileSpec, scheme: str, workdir: str | Path, *, instrument: bool = True,
                 baseline_dir: str | Path | None = None, feature_cache_dir: str | Path | None = None,
                 label: str = "run") -> dict:
    """`feature_cache_dir=None` -> cache de features neuf (départ à froid)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = str(workdir / "patrick.db")
    out_dir = str(workdir / "out")
    fcache = str(feature_cache_dir or (workdir / "feature_cache"))
    store, snapshot_id, data_hash, shape = prepare_snapshot(spec, str(workdir / "store"))
    config = reference.make_config(spec, scheme, out_dir)
    cfg_digest = reference.config_digest(config)

    env = {"PATRICK_DB_PATH": db_path, "PATRICK_STORE_ROOT": str(workdir / "store"),
           "PATRICK_CACHE_ROOT": str(workdir / "cache"), "PATRICK_FEATURE_CACHE_ROOT": fcache}
    gc.collect()
    prof = profiler.Profiler() if instrument else None
    t0 = time.perf_counter()
    with _env(env), _offline_ohlc():
        if instrument:
            with profiler.install(prof):
                result = engine.run_pipeline(config, store=store, db_path=db_path, snapshot_id=snapshot_id)
        else:
            result = engine.run_pipeline(config, store=store, db_path=db_path, snapshot_id=snapshot_id)
    wall = time.perf_counter() - t0

    conn = sqlite3.connect(db_path)
    try:
        n_trials_db = conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0]
        n_fold_metric = conn.execute("SELECT COUNT(*) FROM fold_metric").fetchone()[0]
        n_pred = conn.execute("SELECT COUNT(*) FROM prediction").fetchone()[0]
        engine_phases = [dict(zip(("phase", "seconds"), r, strict=True)) for r in conn.execute(
            "SELECT phase, SUM(strftime('%s', finished_at) - strftime('%s', started_at)) "
            "FROM run_phase_timing GROUP BY phase ORDER BY 2 DESC")]
    finally:
        conn.close()

    lb = result["leaderboard"]
    features_retained = set()
    if "features" in lb.columns:
        for f in lb["features"].dropna():
            features_retained.update(x for x in str(f).split("|") if x)
    digests = None
    if baseline_dir is not None:
        digests = artifacts.capture_baseline(result, db_path, str(baseline_dir),
                                             os.path.join(out_dir, "optuna.db"))

    out = {
        "label": label, "profile": spec.name, "scheme": scheme, "instrumented": instrument,
        "wall_s": round(wall, 3), "pipeline_elapsed_s": round(result["elapsed_s"], 3),
        "snapshot": {"snapshot_id": snapshot_id, "data_hash": data_hash or store.latest_entry(
            f"raw_{reference.TARGET_SYMBOL}")["content_hash"], "shape": list(shape)},
        "config_digest": cfg_digest, "seed": reference.PIPELINE_SEED,
        "results": {"leaderboard_rows": len(lb), "tuned_rows": len(result["tuned"]),
                    "trials_db": n_trials_db, "fold_metric_rows": n_fold_metric, "prediction_rows": n_pred,
                    "features_retained_distinct": len(features_retained),
                    "final_best": result["final_best"]},
        "engine_phase_timing_table_s": engine_phases,
        "digests": digests,
    }
    if prof is not None:
        out["profile_data"] = prof.summary()
        out["deterministic_view"] = prof.deterministic_view()
    return out
