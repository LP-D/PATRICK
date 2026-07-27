"""Phase 1.5 : le data lake est désormais partitionné par snapshot immuable
(hash de contenu), plus un cache "dernier connu" réécrit à chaque ingestion —
cf. anti-pattern Phase 0 "écraser un snapshot existant au lieu d'en créer un
nouveau"."""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd
import pytest

from patrick.data.store import DataStore


def _df(seed=0, n=20):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"x": rng.normal(0, 1, n)}, index=idx)


def test_save_creates_a_snapshot_partition(tmp_path):
    store = DataStore(root=str(tmp_path))
    df = _df()
    snapshot_id = store.save("mykey", df)

    assert store.exists("mykey")
    partitions = glob.glob(os.path.join(str(tmp_path), "snapshot=*"))
    assert len(partitions) == 1
    assert snapshot_id in store.info()["mykey"]["snapshots"][0]["snapshot_id"]


def test_save_never_overwrites_an_existing_snapshot_file(tmp_path):
    store = DataStore(root=str(tmp_path))
    df1 = _df(seed=0)
    df2 = _df(seed=1)  # contenu différent
    store.save("mykey", df1)
    store.save("mykey", df2)

    snapshots = store.list_snapshots("mykey")
    assert len(snapshots) == 2
    # les deux fichiers existent toujours sur disque (aucun écrasé)
    for s in snapshots:
        assert os.path.exists(s["path"])
    paths = {s["path"] for s in snapshots}
    assert len(paths) == 2


def test_save_deduplicates_identical_content(tmp_path):
    store = DataStore(root=str(tmp_path))
    df = _df(seed=0)
    id1 = store.save("mykey", df)
    id2 = store.save("mykey", df.copy())  # contenu identique

    assert id1 == id2
    assert len(store.list_snapshots("mykey")) == 1


def test_load_returns_latest_snapshot_by_default(tmp_path):
    store = DataStore(root=str(tmp_path))
    df1 = _df(seed=0)
    df2 = _df(seed=1)
    store.save("mykey", df1)
    id2 = store.save("mykey", df2)

    loaded = store.load("mykey")
    pd.testing.assert_frame_equal(loaded, df2, check_like=False, check_freq=False)
    assert loaded.attrs["snapshot_id"] == id2


def test_load_specific_snapshot_id(tmp_path):
    store = DataStore(root=str(tmp_path))
    df1 = _df(seed=0)
    df2 = _df(seed=1)
    id1 = store.save("mykey", df1)
    store.save("mykey", df2)

    loaded = store.load("mykey", snapshot_id=id1)
    pd.testing.assert_frame_equal(loaded, df1, check_like=False, check_freq=False)


def test_load_missing_key_raises():
    store = DataStore(root="/tmp/nonexistent_patrick_store_test")
    with pytest.raises(FileNotFoundError):
        store.load("nope")


def test_two_identical_ingestions_produce_the_same_snapshot_id(tmp_path):
    """Prérequis direct du critère de sortie Phase 1 : deux runs sur le même
    snapshot doivent être comparables — donc un contenu identique doit toujours
    retomber sur le même snapshot_id, même appelé à des moments différents."""
    store_a = DataStore(root=str(tmp_path))
    df = _df(seed=42)
    id_a = store_a.save("k", df)

    store_b = DataStore(root=str(tmp_path))  # nouvelle instance, même root
    id_b = store_b.save("k", df.copy())

    assert id_a == id_b


def test_query_via_duckdb_reads_parquet_directly(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    store = DataStore(root=str(tmp_path))
    store.save("mykey", _df(seed=0, n=5))

    result = store.query(f"SELECT count(*) AS n FROM read_parquet('{store.glob_pattern()}')")
    assert result["n"].iloc[0] == 5
