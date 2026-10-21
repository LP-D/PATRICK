"""Les composants de données lisent leur emplacement par `patrick.paths` (spec 2026-10-21, §5).

Chaque test pose une racine de données `R` et retire les variables propres à un composant : sans elles, le composant doit
tomber sous `R`. La base active, elle, ne suit jamais la racine de données."""
from __future__ import annotations

import pytest

from patrick import paths


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "PATRICK DATA"
    r.mkdir()
    for var in ("PATRICK_STORE_ROOT", "PATRICK_CACHE_ROOT", "PATRICK_FEATURE_CACHE_ROOT", "PATRICK_DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(r))
    return r


def test_datastore_default_root_follows_the_data_root(root):
    from patrick.data.store import DataStore

    assert DataStore().root == str(root / "store")


def test_local_cache_default_root_follows_the_data_root(root):
    from patrick import cache_manager

    assert cache_manager.LocalCache().root == root / "cache"


def test_feature_cache_default_root_follows_the_data_root(root):
    from patrick.features import pool_cache

    assert pool_cache._root() == root / "feature_cache"


def test_default_db_path_ignores_the_data_root(root):
    from patrick.tracking import db as trackdb

    assert trackdb.default_db_path() == paths.db_path()
    assert not trackdb.default_db_path().startswith(str(root))


def test_artifact_roots_search_the_models_folder(root):
    from patrick.tracking import usage

    assert root / "models" in usage.artifact_roots()


def test_a_component_env_var_still_wins(root, monkeypatch, tmp_path):
    from patrick.data.store import DataStore

    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "ailleurs"))

    assert DataStore().root == str(tmp_path / "ailleurs")


def test_backup_database_defaults_to_the_data_root_backups(root, tmp_path):
    from patrick.tracking import backup
    from patrick.tracking import db as trackdb

    source = tmp_path / "ssd" / "patrick.db"
    source.parent.mkdir()
    trackdb.connect(str(source)).close()

    saved = backup.backup_database(str(source), pages=-1, sleep_s=0.0)

    assert saved.parent == root / "backups" and saved.is_file()


def test_default_reports_dir_follows_the_data_root(root):
    from patrick.tracking import report

    assert report.default_reports_dir() == str(root / "reports")
