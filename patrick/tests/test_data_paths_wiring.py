"""Les composants de données lisent leur emplacement par `patrick.paths` (spec 2026-10-21, §5).

Chaque test pose une racine de données `R` et retire les variables propres à un composant : sans elles, le composant doit
tomber sous `R`. La base active, elle, ne suit jamais la racine de données."""
from __future__ import annotations

import pytest
from test_sync_auto import pcs  # noqa: F401  (fixture)

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


# --- sync.py : emplacements, messages, statut, autre PC -------------------------------------------------------

def test_sync_default_folders_follow_the_data_root(root):
    from patrick import sync

    assert sync._default_store_root() == str(root / "store")
    assert str(root / "models") in sync._default_models_roots()


def test_the_disk_full_message_names_the_real_folders(root):
    from patrick import sync

    message = sync._disk_full_message(root)

    assert str(root / "feature_cache") in message and str(root / "backups") in message
    assert "~/.patrick" not in message


def test_status_reports_the_data_root_and_its_free_space(root, tmp_path):
    from patrick import sync

    out = sync.status(str(tmp_path / "share"), db_path=str(tmp_path / "x.db"))

    assert out["data_root"] == str(root) and out["data_available"] is True and out["data_free_gb"] > 0


def test_status_and_auto_do_not_crash_when_the_data_disk_is_missing(monkeypatch, tmp_path):
    from patrick import sync

    absent = tmp_path / "absent"
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(absent))

    status = sync.status(str(tmp_path / "share"), db_path=str(tmp_path / "x.db"))
    auto = sync.auto(str(tmp_path / "share"), db_path=str(tmp_path / "x.db"))

    assert status["data_available"] is False and status["data_root"] == str(absent) and status["data_free_gb"] is None
    assert auto["actions"] == [] and any("introuvable" in s for s in auto["skipped"])


def test_a_second_pc_restores_models_and_backup_under_its_own_data_root(pcs, tmp_path, monkeypatch):  # noqa: F811
    import sqlite3
    from pathlib import Path

    from patrick import sync

    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    models = tmp_path / "pc1_models"
    models.mkdir()
    (models / "a1_lgbm.joblib").write_bytes(b"modele-a1")
    conn = sqlite3.connect(pc1.db)
    conn.execute("UPDATE trial SET artifact_path = ? WHERE run_id = 'a1' AND algo = 'lgbm'",
                 (str(models / "a1_lgbm.joblib"),))
    conn.commit()
    conn.close()
    pc1.auto(share, models_roots=[str(tmp_path)])
    pc2.seed(["b1"])
    data2 = tmp_path / "PC2 DATA"
    data2.mkdir()
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(data2))
    kw = {k: v for k, v in pc2.kw.items() if k not in ("models_dir", "backup_dir")}

    pc2.use()
    out = sync.auto(str(share), only="pull", **kw)

    conn = sqlite3.connect(pc2.db)
    (path,) = [r[0] for r in conn.execute("SELECT artifact_path FROM trial WHERE run_id = 'a1' AND algo = 'lgbm'")]
    conn.close()
    assert Path(path).is_absolute() and Path(path).parent.parent == data2 / "models"
    assert Path(path).read_bytes() == b"modele-a1"
    assert out["merge"]["backup"] and Path(out["merge"]["backup"]).parent == data2 / "backups"
