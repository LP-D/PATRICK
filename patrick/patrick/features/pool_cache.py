"""« Calculer une fois » -- on-disk cache of costly feature pools, keyed by
(data vintage, fold).

- Vintage: the CONTENT hash of the raw frame the pool is built from -- a
  revised snapshot (FRED revision, Yahoo split adjustment) is another key,
  never a stale hit.
- Fold: the fit cut of the parametric models (`fit_end_idx`/`test_end_idx`,
  `None` = whole history for export/predict/explain); the base pool is
  fold-independent (causal rolling windows only).
- Plus the feature configuration, the target column, and
  `FEATURE_CODE_HASH` -- a hash of the feature source code, so that a fix to
  any feature function invalidates every cached pool without anyone having
  to remember to bump a version.

Measured motivation: the base pool costs ~50-90 s on the real ^GSPC universe
and was recomputed by every run; every SHAP explanation, drift check and
live prediction rebuilt the FULL pool (parametric models included, ~33 s on
BTC-USD) even for a snapshot processed a minute earlier.

Layout: `<root>/<key[:2]>/<key>.parquet`, atomic writes (temp file +
`os.replace`), root = `PATRICK_FEATURE_CACHE_ROOT` or
`~/.patrick/feature_cache`. `PATRICK_FEATURE_CACHE=0` disables it.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from patrick import feature_cache_share, paths

_FEATURE_SOURCES = (
    "technical.py", "spike.py", "vol_models.py", "macro.py", "guida.py",
    "equity_fundamentals.py", "_utils.py", "interactions.py", "sanitize.py", "long_cycle.py",
)


def _feature_code_hash() -> str:
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in _FEATURE_SOURCES:
        path = here / name
        if path.exists():
            h.update(name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


FEATURE_CODE_HASH = _feature_code_hash()


def _root() -> Path:
    return paths.feature_cache_dir()


# Mesure (07/11/2026) : le cache pèse 143 Go pour 150 Go de plafond, mais la clé contient l'empreinte du cadre brut entier : dès qu'une barre s'ajoute, tout ce qui précède
# est inutilisable, et chaque cible a son propre cadre. Combien de lectures le cache sert-il vraiment ? Personne ne le savait ; `take_stats` le dit, par étape, et le worker
# l'écrit à la fin de chaque job.
_stats: dict[str, list[float]] = {}


def _count(stage: str, *, hit: bool, compute_s: float = 0.0) -> None:
    entry = _stats.setdefault(stage, [0, 0, 0.0])
    entry[0 if hit else 1] += 1
    entry[2] += compute_s


def take_stats() -> dict[str, dict]:
    """`{étape: {"hits", "misses", "compute_s"}}` depuis le dernier appel, puis remise à zéro (`compute_s` : secondes passées à calculer ce qui manquait)."""
    out = {stage: {"hits": int(v[0]), "misses": int(v[1]), "compute_s": round(v[2], 1)} for stage, v in _stats.items()}
    _stats.clear()
    return out


def stats_line(stats: dict[str, dict]) -> str:
    """Une phrase pour le journal du worker ; vide s'il n'y a rien à dire."""
    parts = [f"{stage} : {v['hits']} lus / {v['misses']} calculés ({v['compute_s']:.0f} s)" for stage, v in sorted(stats.items())]
    return "pools de variables, " + " ; ".join(parts) if parts else ""


def enabled() -> bool:
    return os.environ.get("PATRICK_FEATURE_CACHE", "1") != "0"


def float32_enabled() -> bool:
    """Mode compact (désactivé par défaut) : les pools sont stockés en float32, environ deux fois plus petits. Pour que le résultat ne
    dépende jamais de l'état du cache, la valeur ARRONDIE en float32 est aussi celle que reçoit l'appelant au premier calcul ; les
    pools de ce mode ont leur propre clé. Activer : réglage `feature_cache_float32` ou `PATRICK_FEATURE_CACHE_FLOAT32=1`. Les résultats
    diffèrent alors à la septième décimale de ceux du mode normal (jamais comparer bit à bit les deux modes)."""
    env = os.environ.get("PATRICK_FEATURE_CACHE_FLOAT32")
    if env is not None:
        return env == "1"
    from patrick import settings
    return bool(settings.load().get("feature_cache_float32", False))


def _to_float32(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c, t in df.dtypes.items() if t == "float64"]
    return df.astype({c: "float32" for c in cols}) if cols else df


def _to_float64(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c, t in df.dtypes.items() if t == "float32"]
    return df.astype({c: "float64" for c in cols}) if cols else df


def frame_hash(df: pd.DataFrame) -> str:
    """Content hash of a raw frame (values + index + column names)."""
    h = hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    h.update(json.dumps([str(c) for c in df.columns]).encode())
    return h.hexdigest()


def cache_key(stage: str, raw: pd.DataFrame, payload: dict) -> str:
    body = json.dumps({"stage": stage, "vintage": frame_hash(raw), "code": FEATURE_CODE_HASH,
                       **payload, **({"float32": True} if float32_enabled() else {})}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _path(key: str) -> Path:
    return _root() / key[:2] / f"{key}.parquet"


def load(key: str) -> pd.DataFrame | None:
    path = _path(key)
    fetched = False
    if not path.exists():
        if not feature_cache_share.fetch(key, path):    # défaut local : la réserve partagée (autre PC) peut l'avoir
            return None
        fetched = True
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError):
        if fetched:                                     # fichier de la réserve coupé : écarté, le prochain calcul le republie
            feature_cache_share.discard(key, path)
        return None
    try:
        os.utime(path)                      # « utilisé récemment » : l'éviction (`cache_eviction`) retire d'abord les moins récemment lus
    except OSError:
        pass
    return frame


def save(key: str, df: pd.DataFrame) -> None:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".parquet.tmp", dir=path.parent)
    os.close(fd)
    try:
        # zstd + byte_stream_split : sans perte (float64 conservés : une valeur relue est celle qui a été calculée, le déterminisme
        # ne change pas), nettement plus petit que snappy sur des colonnes de flottants. Les fichiers déjà écrits restent lisibles.
        df.to_parquet(tmp, compression="zstd", use_byte_stream_split=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    feature_cache_share.publish(key, path)  # au mieux : le fichier neuf rejoint la réserve partagée (jamais d'exception)


def cached(stage: str, raw: pd.DataFrame, payload: dict, compute: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    """`compute()` once per key; later calls read the stored frame. Column
    names that parquet cannot store verbatim are never an issue here: every
    pool column is a string."""
    if not enabled():
        return compute()
    key = cache_key(stage, raw, payload)
    compact = float32_enabled()
    hit = load(key)
    if hit is not None:
        if compact:
            hit = _to_float64(hit)
        # Parquet drops index metadata (e.g. `freq`): the pool is always
        # built on `raw`'s own index, restored as-is when it matches.
        if len(hit) == len(raw) and hit.index.equals(raw.index):
            hit.index = raw.index
        _count(stage, hit=True)
        return hit
    t0 = time.perf_counter()
    out = compute()
    _count(stage, hit=False, compute_s=time.perf_counter() - t0)
    if compact:
        out = _to_float32(out)
        save(key, out)
        return _to_float64(out)             # même valeur arrondie au premier calcul et aux lectures suivantes
    save(key, out)
    return out
