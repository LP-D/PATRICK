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
    pytest.importorskip("duckdb")
    store = DataStore(root=str(tmp_path))
    store.save("mykey", _df(seed=0, n=5))

    result = store.query(f"SELECT count(*) AS n FROM read_parquet('{store.glob_pattern()}')")
    assert result["n"].iloc[0] == 5


# -- fichier d'index verrouillé un instant par un autre processus (Windows) ----

def test_index_read_survives_a_transient_permission_error(tmp_path, monkeypatch):
    """07/11/2026 : `POST /runs` répondait 500 quand la lecture de `_index.json` tombait pendant que le worker le remplaçait."""
    import builtins

    from patrick.data import store as store_mod

    store = DataStore(root=str(tmp_path))
    store.save("mykey", _df())
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)

    real_open = builtins.open
    calls = {"n": 0}

    def flaky_open(path, *a, **k):
        if str(path).endswith("_index.json") and calls["n"] < 3:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(store_mod, "open", flaky_open, raising=False)
    assert store.exists("mykey")
    assert calls["n"] == 3


def test_index_read_gives_up_when_the_lock_never_lifts(tmp_path, monkeypatch):
    from patrick.data import store as store_mod

    store = DataStore(root=str(tmp_path))
    store.save("mykey", _df())
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)

    def locked(path, *a, **k):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(store_mod, "open", locked, raising=False)
    with pytest.raises(PermissionError):
        store.exists("mykey")


def test_index_write_retries_the_replace(tmp_path, monkeypatch):
    from patrick.data import store as store_mod

    store = DataStore(root=str(tmp_path))
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        if calls["n"] < 2:
            calls["n"] += 1
            raise PermissionError(13, "Accès refusé", str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(store_mod.os, "replace", flaky_replace)
    store.save("mykey", _df())
    assert calls["n"] == 2
    assert store.exists("mykey")
    assert not glob.glob(os.path.join(str(tmp_path), "_index.*.tmp"))


def test_series_index_survives_a_transient_permission_error(tmp_path, monkeypatch):
    import builtins

    from patrick.data import store as store_mod

    store = DataStore(root=str(tmp_path))
    store.record_series_observations({"AAA": "2026-01-02"}, "yfinance")
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)
    real_open = builtins.open
    calls = {"n": 0}

    def flaky_open(path, *a, **k):
        if str(path).endswith("_series_observations.json") and calls["n"] < 2:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(store_mod, "open", flaky_open, raising=False)
    assert store.series_observation("AAA")["date_max"] == "2026-01-02"


# --- Écriture atomique du fichier Parquet (disque plein du 14/11/2026) --------------------------------------------------------
# Le 14/11/2026, D: pleine : `df.to_parquet(chemin)` avait laissé `raw_FCX__a09f723cf153.parquet` coupé à 986 828 octets (environ 1,4 Mo
# attendus), non référencé par l'index (écrit après, de façon atomique). Un fichier qu'on n'a pas fini d'écrire ne doit jamais porter le nom
# définitif : on écrit dans un fichier temporaire du même dossier, puis `os.replace`.

def _fill_disk_halfway(monkeypatch):
    """`DataFrame.to_parquet` qui écrit la moitié du fichier puis lève « No space left on device »."""
    def half_write(self, path, *args, **kwargs):
        with open(path, "wb") as handle:
            handle.write(b"PAR1" + b"x" * 1000)
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(pd.DataFrame, "to_parquet", half_write)


def test_save_on_a_full_disk_leaves_no_file_at_all(tmp_path, monkeypatch):
    store = DataStore(root=str(tmp_path))
    _fill_disk_halfway(monkeypatch)

    with pytest.raises(OSError, match="No space left"):
        store.save("mykey", _df())

    assert glob.glob(os.path.join(str(tmp_path), "snapshot=*", "*")) == []      # ni fichier définitif tronqué, ni temporaire orphelin
    assert not store.exists("mykey")                                            # l'index n'a rien enregistré


def test_save_replaces_a_truncated_orphan_with_the_same_name(tmp_path):
    """Le fichier tronqué de la nuit du 14/11 portait le nom qu'aura le prochain `save` du même contenu : il doit être remplacé, pas relu."""
    store = DataStore(root=str(tmp_path))
    df = _df()
    snapshot_id = store.save("mykey", df)
    store2 = DataStore(root=str(tmp_path / "autre"))
    orphan = store2._snapshot_path("mykey", snapshot_id.split("__")[0], snapshot_id.split("__")[-1])
    os.makedirs(os.path.dirname(orphan), exist_ok=True)
    with open(orphan, "wb") as handle:
        handle.write(b"PAR1" + b"x" * 100)                                       # orphelin tronqué, absent de l'index de `store2`

    store2.save("mykey", df)

    pd.testing.assert_frame_equal(store2.load("mykey"), df, check_freq=False)          # le fichier est complet : relisible


def test_a_successful_save_leaves_no_temporary_file(tmp_path):
    store = DataStore(root=str(tmp_path))
    store.save("mykey", _df())

    names = [os.path.basename(p) for p in glob.glob(os.path.join(str(tmp_path), "snapshot=*", "*"))]
    assert len(names) == 1 and names[0].endswith(".parquet")


def test_the_temporary_file_is_invisible_to_a_parquet_glob(tmp_path, monkeypatch):
    """Pendant l'écriture, le fichier temporaire ne doit pas être pris pour un snapshot (`query()` lit `snapshot=*/*.parquet`)."""
    store = DataStore(root=str(tmp_path))
    seen = []
    real = pd.DataFrame.to_parquet

    def spy(self, path, *args, **kwargs):
        seen.append(str(path))
        return real(self, path, *args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", spy)

    store.save("mykey", _df())

    assert len(seen) == 1 and not seen[0].endswith(".parquet")                  # écrit sous un autre nom, renommé ensuite
