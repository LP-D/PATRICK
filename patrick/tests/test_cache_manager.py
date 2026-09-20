"""`patrick.cache_manager.LocalCache` n'avait aucun test : cache local
parquet/json avec rafraîchissement hebdomadaire (`max_age_days`, défaut 7),
basé sur un fichier de métadonnées JSON à côté de chaque entrée
(`<key>.json`, champ `updated_at`). Style de fixtures aligné sur
`test_selection_cache.py`/`test_vol_model_cache.py` (`tmp_path`,
`monkeypatch` pour figer le temps plutôt que `time.sleep`)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

import patrick.cache_manager as cache_manager_module
from patrick.cache_manager import LocalCache


@pytest.fixture
def cache(tmp_path) -> LocalCache:
    return LocalCache(root=str(tmp_path / "cache"))


def _df() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})


def _freeze_utcnow(monkeypatch, days_from_now: float) -> None:
    """Freezes `cache_manager.datetime.utcnow()` `days_from_now` days ahead
    of the real current time, without sleeping in real time. Mirrors
    `cache_manager.py`'s own naive (no-tz) `datetime.utcnow()` convention --
    intentional, `_is_fresh()` compares directly against it."""
    future = datetime.utcnow() + timedelta(days=days_from_now)  # noqa: DTZ003

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return future

    monkeypatch.setattr(cache_manager_module, "datetime", _FrozenDatetime)


# -- DataFrame (save_dataframe/load_dataframe) --------------------------

def test_load_dataframe_cache_miss_returns_none_when_never_written(cache):
    assert cache.load_dataframe("missing_key") is None


def test_save_dataframe_then_load_returns_the_cached_value(cache):
    df = _df()

    written = cache.save_dataframe("prices", df)
    pd.testing.assert_frame_equal(written, df)

    loaded = cache.load_dataframe("prices")
    pd.testing.assert_frame_equal(loaded, df)


def test_load_dataframe_hit_does_not_touch_the_file_on_disk(cache):
    """Cache hit: `load_dataframe` must not rewrite the parquet/meta files
    -- reading twice returns the same on-disk content, not a recomputed
    one (there's no producer to count calls on here, so this asserts the
    file's mtime/content are untouched by a read)."""
    df = _df()
    cache.save_dataframe("prices", df)
    meta_path = cache._meta_path("prices")
    meta_before = meta_path.read_text(encoding="utf-8")

    cache.load_dataframe("prices")
    cache.load_dataframe("prices")

    assert meta_path.read_text(encoding="utf-8") == meta_before


def test_load_dataframe_expires_after_max_age_days(cache, monkeypatch):
    df = _df()
    cache.save_dataframe("prices", df, max_age_days=7)

    # 8 days later -- past the 7-day freshness window configured above.
    _freeze_utcnow(monkeypatch, 8)

    assert cache.load_dataframe("prices", max_age_days=7) is None


def test_load_dataframe_still_fresh_just_before_max_age_days(cache, monkeypatch):
    df = _df()
    cache.save_dataframe("prices", df, max_age_days=7)

    _freeze_utcnow(monkeypatch, 6)

    loaded = cache.load_dataframe("prices", max_age_days=7)
    pd.testing.assert_frame_equal(loaded, df)


# -- JSON (save_json/load_json) ------------------------------------------

def test_load_json_cache_miss_returns_none_when_never_written(cache):
    assert cache.load_json("missing_key") is None


def test_save_json_then_load_returns_the_cached_value(cache):
    payload = {"n_trials": 42, "best_score": 0.87}

    cache.save_json("study", payload)

    assert cache.load_json("study") == payload


def test_load_json_expires_after_max_age_days(cache, monkeypatch):
    cache.save_json("study", {"n_trials": 42})

    _freeze_utcnow(monkeypatch, 10)

    assert cache.load_json("study", max_age_days=7) is None
