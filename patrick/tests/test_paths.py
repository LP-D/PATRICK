"""`patrick/paths.py` : où vivent la base, les journaux et la racine de données (spec 2026-10-21, §3 et §4)."""
from __future__ import annotations

import pytest

from patrick import paths, settings

_ENV = ("PATRICK_DATA_ROOT", "PATRICK_DB_PATH", "PATRICK_STORE_ROOT", "PATRICK_CACHE_ROOT", "PATRICK_FEATURE_CACHE_ROOT")


@pytest.fixture(autouse=True)
def _unconfigured(monkeypatch):
    """Le `conftest.py` pose `PATRICK_DATA_ROOT` pour tous les tests : ici on part d'un PC sans aucun réglage."""
    for var in _ENV:
        monkeypatch.delenv(var, raising=False)


def test_default_is_the_home_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))

    assert paths.data_root() == tmp_path
    assert paths.models_dir() == tmp_path / "models"
    assert paths.backups_dir() == tmp_path / "backups"
    assert paths.db_path() == str(tmp_path / "patrick.db")


def test_priority_component_env_over_env_over_setting(monkeypatch, tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for folder in (a, b, c):
        folder.mkdir()
    settings.save({"data_root": str(a)})
    assert paths.store_dir() == a / "store"

    monkeypatch.setenv("PATRICK_DATA_ROOT", str(b))
    assert paths.store_dir() == b / "store"
    assert paths.archive_dir() == b / "archive" and paths.reports_dir() == b / "reports"

    monkeypatch.setenv("PATRICK_STORE_ROOT", str(c))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(c / "x"))
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(c / "y"))
    assert paths.store_dir() == c
    assert paths.cache_dir() == c / "x" and paths.feature_cache_dir() == c / "y"


@pytest.mark.parametrize("how", ["env", "setting"])
def test_missing_root_raises_and_creates_nothing(monkeypatch, tmp_path, how):
    missing = tmp_path / "PATRICK DATA"
    if how == "env":
        monkeypatch.setenv("PATRICK_DATA_ROOT", str(missing))
    else:
        settings.save({"data_root": str(missing)})

    with pytest.raises(paths.DataRootUnavailable, match="PATRICK DATA"):
        paths.models_dir()
    assert not missing.exists()
    assert paths.data_root_missing() == str(missing)
    assert "PATRICK DATA" in paths.data_root_problem()


def test_component_env_does_not_need_the_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "absent"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))

    assert paths.store_dir() == tmp_path / "store"


def test_db_and_logs_stay_in_home_with_a_data_root(monkeypatch, tmp_path):
    root = tmp_path / "PATRICK DATA"
    root.mkdir()
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(root))
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "ssd" / "patrick.db"))

    assert paths.home_dir() == tmp_path / "ssd"
    assert paths.db_path() == str(tmp_path / "ssd" / "patrick.db")
    assert paths.logs_dir() == tmp_path / "ssd" / "logs"
    assert paths.models_dir() == root / "models"


def test_setting_is_reread_on_every_call(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    settings.save({"data_root": str(a)})
    assert paths.backups_dir() == a / "backups"

    settings.save({"data_root": str(b)})
    assert paths.backups_dir() == b / "backups"

    settings.save({"data_root": None})
    assert paths.configured_data_root() is None


def test_no_problem_when_unconfigured():
    assert paths.configured_data_root() is None
    assert paths.data_root_missing() is None
    assert paths.data_root_problem() is None
