"""Manifeste de run : de quoi refaire ou comparer un run (audit externe du 2026-10-19).

Un résultat qui ne se reproduit pas sur une autre machine a trois causes possibles : le code, les données,
l'environnement. Le SHA git, la graine, l'empreinte de configuration, les versions de bibliothèques et l'empreinte des données
(snapshot) sont déjà dans la base ; ce module y ajoute ce qui manquait -- la plateforme (système, processeur, BLAS,
instructions SIMD que numpy utilise), l'empreinte de l'environnement installé et celle du fichier de contraintes de la CI --
écrits à la création du run (`run.manifest_json`, migration 0039), et rassemble le tout (`build_manifest`).
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import platform
import sqlite3
from importlib import metadata as importlib_metadata
from pathlib import Path

CONSTRAINTS_FILE = Path(__file__).resolve().parents[3] / ".github" / "constraints-py311.txt"


@functools.lru_cache(maxsize=1)
def platform_fingerprint() -> dict:
    """Ce qui, hors du code et des données, fait bouger les derniers chiffres : système, processeur, noyau BLAS, SIMD de numpy."""
    import numpy as np

    blas: list[str] = []
    simd: list[str] = []
    with contextlib.suppress(Exception):    # la plateforme se décrit au mieux, sans jamais empêcher un run
        import threadpoolctl

        blas = sorted({f"{lib['internal_api']}:{lib.get('architecture')}"
                       for lib in threadpoolctl.threadpool_info() if lib["user_api"] == "blas"})
    with contextlib.suppress(Exception):
        from numpy._core import _multiarray_umath

        simd = [f for f in _multiarray_umath.__cpu_dispatch__ if _multiarray_umath.__cpu_features__.get(f)]
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "os": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
            "cpu_count": os.cpu_count() or 1, "numpy": np.__version__, "blas": blas, "numpy_simd": simd}


def installed_packages() -> dict[str, str]:
    """{nom normalisé: version} de tout ce qui est installé dans l'environnement courant."""
    out: dict[str, str] = {}
    for dist in importlib_metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            out[name.lower().replace("_", "-")] = dist.version
    return out


def environment_digest() -> str:
    """Empreinte courte de l'environnement installé (noms et versions, triés)."""
    packages = installed_packages()
    listing = "\n".join(f"{k}=={packages[k]}" for k in sorted(packages))
    return hashlib.sha256(listing.encode()).hexdigest()[:16]


def constraints_digest() -> str | None:
    """Empreinte du fichier de contraintes de la CI (les versions que la suite lente épingle), `None` s'il est absent."""
    try:
        return hashlib.sha256(CONSTRAINTS_FILE.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def launch_manifest() -> str:
    """JSON écrit dans `run.manifest_json` à la création d'un run."""
    return json.dumps({"platform": platform_fingerprint(), "environment_digest": environment_digest(),
                       "constraints_digest": constraints_digest()}, sort_keys=True)


def build_manifest(conn: sqlite3.Connection, run_id: str) -> dict:
    """Tout ce qu'on sait pour refaire `run_id` : code (SHA), données (empreinte du snapshot), configuration, graine,
    bibliothèques, plateforme et environnement. `recorded_at_launch` est faux pour un run d'avant le manifeste : sa
    plateforme et son environnement sont alors inconnus (`None`), jamais ceux de la machine d'aujourd'hui."""
    row = conn.execute(
        "SELECT run.run_id, run.target, run.horizon, run.git_sha, run.seed, run.config_hash, run.lib_versions, "
        "run.snapshot_id, run.started_at, run.finished_at, run.manifest_json, "
        "snapshot.data_hash, snapshot.n_tickers, snapshot.n_fred_series, snapshot.fred_source "
        "FROM run LEFT JOIN snapshot ON snapshot.snapshot_id = run.snapshot_id WHERE run.run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    (rid, target, horizon, git_sha, seed, config_hash, lib_versions, snapshot_id, started_at, finished_at,
     manifest_json, data_hash, n_tickers, n_fred_series, fred_source) = row
    launch = json.loads(manifest_json) if manifest_json else None
    return {
        "run_id": rid, "target": target, "horizon": horizon, "started_at": started_at, "finished_at": finished_at,
        "git_sha": git_sha, "seed": seed, "config_hash": config_hash,
        "data": {"snapshot_id": snapshot_id, "data_hash": data_hash, "n_tickers": n_tickers,
                 "n_fred_series": n_fred_series, "fred_source": fred_source},
        "libraries": json.loads(lib_versions) if lib_versions else {},
        "platform": launch["platform"] if launch else None,
        "environment_digest": launch["environment_digest"] if launch else None,
        "constraints_digest": launch.get("constraints_digest") if launch else None,
        "recorded_at_launch": launch is not None,
    }
