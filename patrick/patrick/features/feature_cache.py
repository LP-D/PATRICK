"""Versioned on-disk cache of the full feature pool (`pipeline.engine.
build_full_feature_pool`) -- the ~30s rebuild `explain.py` measured on a
real universe, repeated on every `/targets/{ticker}` SHAP/drift request.

Key = `(snapshot_id, feature_config_hash)`:
  - `snapshot_id`: the raw data version (`data/store.py`), so a newer
    FRED vintage / Yahoo revision never reuses an older pool.
  - `feature_config_hash`: sha256 of `feature_config_payload()` below --
    EVERY parameter that changes the pool's output. Two configs that differ
    on any of them get distinct entries (no stale reuse); two configs that
    differ only on parameters NOT listed (tuning, models, validation,
    selection, sampler, output dir, ...) share the same pool, as they should.

Parameters retained in the hash (explicit, reviewed against
`build_base_feature_pool` / `build_parametric_pool` / `_apply_interaction_formulas`):
  - features.families                      (which feature families are built)
  - features.vol_models                    (which vol models, base + parametric)
  - features.enable_guida_features         (Guida grid + estimated families)
  - features.enable_fundamentals_features  (equity fundamentals columns)
  - features.technical_lookbacks.*         (returns / z-score / moving-average
                                            ratio / rolling-vol / OHLC-vol windows)
  - config.defaults.GUIDA_LOOKBACKS         (code constant used when Guida is on)
  - objective.target_symbol                 (target column, OHLC vol download,
                                            fundamentals lookup)
  - universe.fred_series (keys)             (macro feature columns)
  - universe.start_date                     (OHLC download start)
  - interaction_formulas                    (interaction columns appended)
  - FEATURE_CACHE_VERSION                   (bump when feature CODE changes
                                            output for identical parameters)
Deliberately NOT retained: interact_top_base/top_pairs/final_n and
pool_prefilter -- they only affect interaction DISCOVERY / scan-time
filtering, never the pool rebuilt from already-discovered formulas.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Callable

import pandas as pd

from patrick.config import defaults as D
from patrick.config.schema import RunConfig

FEATURE_CACHE_VERSION = 1


def _default_root() -> str:
    return os.environ.get("PATRICK_FEATURE_CACHE_ROOT") or os.path.expanduser("~/.patrick/feature_cache")


def feature_config_payload(config: RunConfig, interaction_formulas: list[str] | None = None) -> dict:
    f = config.features
    return {
        "cache_version": FEATURE_CACHE_VERSION,
        "families": sorted(f.families),
        "vol_models": sorted(f.vol_models),
        "enable_guida_features": bool(f.enable_guida_features),
        "enable_fundamentals_features": bool(f.enable_fundamentals_features),
        "technical_lookbacks": f.technical_lookbacks.model_dump(),
        "guida_lookbacks": list(D.GUIDA_LOOKBACKS),
        "target_symbol": config.objective.target_symbol,
        "fred_series": sorted(config.universe.fred_series.keys()),
        "start_date": config.universe.start_date,
        "interaction_formulas": list(interaction_formulas or []),
    }


def feature_config_hash(config: RunConfig, interaction_formulas: list[str] | None = None) -> str:
    blob = json.dumps(feature_config_payload(config, interaction_formulas), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class FeatureCache:
    def __init__(self, root: str | None = None):
        self.root = root or _default_root()

    def path(self, snapshot_id: str, config_hash: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in snapshot_id)
        return os.path.join(self.root, safe, f"{config_hash}.parquet")

    def load(self, snapshot_id: str, config_hash: str) -> pd.DataFrame | None:
        p = self.path(snapshot_id, config_hash)
        return pd.read_parquet(p) if os.path.exists(p) else None

    def save(self, snapshot_id: str, config_hash: str, pool: pd.DataFrame, payload: dict) -> None:
        p = self.path(snapshot_id, config_hash)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".parquet.tmp", dir=os.path.dirname(p))
        os.close(fd)
        try:
            pool.to_parquet(tmp)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        with open(p[:-len(".parquet")] + ".json", "w", encoding="utf-8") as fh:
            json.dump({"snapshot_id": snapshot_id, **payload}, fh, indent=1, sort_keys=True)

    def get_or_build(self, raw: pd.DataFrame, config: RunConfig, target_col: str,
                     interaction_formulas: list[str] | None, snapshot_id: str,
                     builder: Callable[..., pd.DataFrame]) -> pd.DataFrame:
        """Returns the cached pool for `(snapshot_id, hash(config_features))`,
        or calls `builder(raw, config, target_col, interaction_formulas)` once
        and persists its output."""
        payload = feature_config_payload(config, interaction_formulas)
        key = feature_config_hash(config, interaction_formulas)
        cached = self.load(snapshot_id, key)
        if cached is not None:
            return cached
        pool = builder(raw, config, target_col, interaction_formulas)
        self.save(snapshot_id, key, pool, payload)
        return pool
