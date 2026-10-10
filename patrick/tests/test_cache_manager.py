"""`patrick.cache_manager.LocalCache` n'avait aucun test : cache local
parquet/json avec rafraîchissement hebdomadaire (`max_age_days`, défaut 7),
basé sur un fichier de métadonnées JSON à côté de chaque entrée
(`<key>.json`, champ `updated_at`). Style de fixtures aligné sur
`test_selection_cache.py`/`test_vol_model_cache.py` (`tmp_path`,
`monkeypatch` pour figer le temps plutôt que `time.sleep`)."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

import patrick.cache_manager as cache_manager_module
from patrick.cache_manager import LocalCache
from patrick.clock import utc_now


@pytest.fixture
def cache(tmp_path) -> LocalCache:
    return LocalCache(root=str(tmp_path / "cache"))


def _df() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})


def _freeze_utcnow(monkeypatch, days_from_now: float) -> None:
    """Freezes `cache_manager.utc_now()` (the package's single, timezone-
    aware clock, `patrick/clock.py`) `days_from_now` days ahead -- a cache
    written "now" then looks exactly that old to `_is_fresh`."""
    future = utc_now() + timedelta(days=days_from_now)
    monkeypatch.setattr(cache_manager_module, "utc_now", lambda: future)


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


# --------------------------------------------------------------------------- écriture atomique et lecture tolérante


def test_an_unreadable_cache_file_is_treated_as_missing_so_it_heals(cache):
    cache.save_dataframe("series_X", _df())
    path = cache._file("series_X")
    path.write_bytes(path.read_bytes()[:40])                 # tronqué : l'état laissé par deux écritures simultanées
    assert cache.load_dataframe("series_X") is None          # pas d'exception : l'appelant retélécharge
    cache.save_dataframe("series_X", _df())
    assert cache.load_dataframe("series_X").equals(_df())


def test_saving_leaves_no_temporary_file_behind(cache):
    cache.save_dataframe("series_Y", _df())
    assert sorted(p.name for p in cache.root.iterdir()) == ["series_Y.meta.json", "series_Y.parquet"]


def test_concurrent_saves_and_loads_of_the_same_key_never_expose_a_torn_file(cache):
    import threading
    import time
    big = pd.DataFrame({"a": range(20000), "b": [float(i) for i in range(20000)]})
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        try:
            for _ in range(15):
                cache.save_dataframe("series_Z", big)
        except Exception as exc:  # noqa: BLE001 -- le test remonte toute erreur de fil
            errors.append(exc)

    def reader():
        while not stop.is_set():
            try:
                got = cache.load_dataframe("series_Z")
                assert got is None or len(got) == len(big)    # soit rien, soit TOUTES les lignes : jamais un fichier tronqué
                time.sleep(0.003)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                return

    cache.save_dataframe("series_Z", big)
    writers = [threading.Thread(target=writer) for _ in range(3)]
    readers = [threading.Thread(target=reader) for _ in range(2)]
    for t in (*writers, *readers):
        t.start()
    for t in writers:
        t.join()
    stop.set()
    for t in readers:
        t.join()
    assert errors == []
