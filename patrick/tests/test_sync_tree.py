"""`patrick sync` : mise en page « arborescence en clair » (format 2) du dossier partagé.

Avant, chaque publication reconstruisait `store.zip` (~30 Go) dans le dossier temporaire puis le recopiait en entier
vers Google Drive : les 10 et 11/11/2026 cela a saturé `C:` (cache du Drive) et figé la synchronisation. Désormais un
dossier reçoit des fichiers en clair, copiés SEULEMENT s'ils manquent (les parquet du magasin et les modèles sont
immuables) ; `manifest.json` est écrit en dernier. Chaque test crée ses bases sous `tmp_path`."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from test_sync import _count, _make_db
from test_sync_auto import PC

from patrick import sync
from patrick.tracking import db as trackdb


def _push(dest: Path, src_db: Path, tmp_path: Path, **kw) -> dict:
    kw.setdefault("store_root", str(tmp_path / "no_store"))
    kw.setdefault("models_roots", [])
    return sync.push(str(dest), db_path=str(src_db), **kw)


def _pull(source: Path, dst_db: Path, tmp_path: Path, **kw) -> dict:
    kw.setdefault("store_root", str(tmp_path / "pc2_store"))
    kw.setdefault("models_dir", str(tmp_path / "pc2_models"))
    kw.setdefault("backup_dir", str(tmp_path / "pc2_backups"))
    return sync.pull(str(source), db_path=str(dst_db), **kw)


def _write_store(root: Path, files: dict[str, bytes]) -> None:
    index = {}
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entry = {"snapshot_id": Path(rel).stem, "content_hash": "h", "rows": 1, "cols": 1, "path": str(target)}
        index[Path(rel).stem] = {"snapshots": [entry]}
    (root / "_index.json").write_text(json.dumps(index), encoding="utf-8")


def _add_trial(db_path: Path, run_id: str, model: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best, "
                 "artifact_path) VALUES (?, 'all', 'lgbm', 'tpe', 10, 'shap', '{}', 1, ?)", (run_id, str(model)))
    conn.commit()
    conn.close()


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_push_to_a_folder_publishes_a_clear_tree_without_any_archive(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"

    manifest = _push(dest, src, tmp_path)

    assert manifest["format"] == 2
    assert _files(dest) == ["db/patrick.db", "manifest.json"]            # ni zip, ni gz, ni .part
    published = dest / "db" / "patrick.db"
    assert _count(published, "run") == 2                                 # une base SQLite lisible telle quelle
    assert hashlib.sha256(published.read_bytes()).hexdigest() == manifest["files"]["db/patrick.db"]["sha256"]
    assert json.loads((dest / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_the_published_database_holds_no_personal_row_and_no_username(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=True)
    dest = tmp_path / "share"

    _push(dest, src, tmp_path)

    conn = sqlite3.connect(str(dest / "db" / "patrick.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM wealth_account").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM fund_strategy").fetchone()[0] == 0
    finally:
        conn.close()
    assert b"Dufour" not in (dest / "db" / "patrick.db").read_bytes()


def test_a_second_push_does_not_recopy_files_that_are_already_published(tmp_path):
    store = tmp_path / "pc1_store"
    _write_store(store, {"snapshot=2026-08-19/raw_VIX__abc.parquet": b"parquet-1"})
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    first = _push(dest, src, tmp_path, store_root=str(store))
    published = dest / "store" / "snapshot=2026-08-19" / "raw_VIX__abc.parquet"
    os.utime(published, ns=(10**18, 10**18))                             # date reconnaissable : une recopie la changerait

    _write_store(store, {"snapshot=2026-08-19/raw_VIX__abc.parquet": b"parquet-1",
                         "snapshot=2026-08-20/raw_VIX__def.parquet": b"parquet-2"})
    second = _push(dest, src, tmp_path, store_root=str(store))

    assert published.stat().st_mtime_ns == 10**18
    assert (dest / "store" / "snapshot=2026-08-20" / "raw_VIX__def.parquet").read_bytes() == b"parquet-2"
    assert first["store"]["files"] == 1 and second["store"]["files"] == 2
    assert second["uploaded"]["files"] == first["uploaded"]["files"]     # base + index + UN parquet neuf, à chaque fois


def test_a_truncated_file_left_by_an_interrupted_push_is_copied_again(tmp_path):
    store = tmp_path / "pc1_store"
    _write_store(store, {"snapshot=2026-08-19/raw_VIX__abc.parquet": b"parquet-complet"})
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path, store_root=str(store))
    published = dest / "store" / "snapshot=2026-08-19" / "raw_VIX__abc.parquet"
    published.write_bytes(b"parq")                                       # coupure en pleine copie

    _push(dest, src, tmp_path, store_root=str(store))

    assert published.read_bytes() == b"parquet-complet"


def test_pull_refuses_a_share_whose_files_were_not_fully_copied(tmp_path):
    store = tmp_path / "pc1_store"
    _write_store(store, {"snapshot=2026-08-19/raw_VIX__abc.parquet": b"parquet-complet"})
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path, store_root=str(store))
    (dest / "store" / "snapshot=2026-08-19" / "raw_VIX__abc.parquet").write_bytes(b"parq")

    with pytest.raises(sync.SyncError, match="pas entièrement"):
        _pull(dest, tmp_path / "pc2.db", tmp_path)


def test_pull_rejects_a_corrupted_database(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)
    published = dest / "db" / "patrick.db"
    published.write_bytes(b"x" * published.stat().st_size)               # même taille, autre contenu

    with pytest.raises(sync.SyncError, match="sha256"):
        _pull(dest, tmp_path / "pc2.db", tmp_path)
    assert not (tmp_path / "pc2.db").exists()


def test_models_roundtrip_in_a_clear_tree(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    models = tmp_path / "pc1_runs"
    models.mkdir()
    (models / "VIX_best_model_h1.joblib").write_bytes(b"modele-1")
    (models / "VIX_best_model_h1_meta.json").write_text('{"k": 1}', encoding="utf-8")
    _add_trial(src, "run_1", models / "VIX_best_model_h1.joblib")
    _add_trial(src, "run_2", Path("runs/absent/x.joblib"))
    dest = tmp_path / "share"

    manifest = _push(dest, src, tmp_path, models_roots=[str(tmp_path)])

    assert manifest["models"]["included"] == 1
    assert manifest["models"]["missing"] == ["runs/absent/x.joblib"]
    pc2 = tmp_path / "pc2.db"
    _pull(dest, pc2, tmp_path)
    conn = sqlite3.connect(str(pc2))
    (new_path,) = {r[0] for r in conn.execute("SELECT artifact_path FROM trial WHERE run_id = 'run_1'")}
    conn.close()
    assert Path(new_path).read_bytes() == b"modele-1"
    assert Path(new_path).is_relative_to(tmp_path / "pc2_models")
    assert Path(new_path).with_name("VIX_best_model_h1_meta.json").exists()


def test_two_pcs_publishing_a_model_with_the_same_name_do_not_overwrite_each_other(tmp_path):
    """Les identifiants d'essai sont propres à chaque base : deux PC ont chacun un essai n° 1 et un fichier du même nom."""
    share = tmp_path / "share"
    pc1_db, pc2_db = tmp_path / "pc1.db", tmp_path / "pc2.db"
    for db_file, who, content in ((pc1_db, "pc1", b"modele-A"), (pc2_db, "pc2", b"modele-B")):
        _make_db(db_file, personal=False)
        folder = tmp_path / f"{who}_runs"
        folder.mkdir()
        (folder / "m.joblib").write_bytes(content)
        _add_trial(db_file, "run_1", folder / "m.joblib")
        _push(share, db_file, tmp_path, models_roots=[str(tmp_path)])

    assert len(list(share.glob("models/*/m.joblib"))) == 2               # les deux versions coexistent
    pc3 = tmp_path / "pc3.db"
    _pull(share, pc3, tmp_path)                                          # le dernier publié (pc2) est restauré
    conn = sqlite3.connect(str(pc3))
    (path,) = [r[0] for r in conn.execute("SELECT artifact_path FROM trial")]
    conn.close()
    assert Path(path).read_bytes() == b"modele-B"


def test_store_roundtrip_in_a_clear_tree_makes_index_paths_local_and_username_free(tmp_path):
    store1 = tmp_path / "pc1_store"
    _write_store(store1, {"snapshot=2026-08-19/raw_VIX__abc.parquet": b"parquet-1"})
    (store1 / "_series_observations.json").write_text(
        json.dumps({"BTC-USD": {"date_max": "2026-10-01", "source": "yahoo"}}), encoding="utf-8")
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path, store_root=str(store1))

    store2 = tmp_path / "pc2_store"
    store2.mkdir()
    local_entry = {"snapshot_id": "2026-09-30__raw_GSPC__zzz", "content_hash": "zzz", "rows": 1, "cols": 6,
                   "path": str(store2 / "snapshot=2026-09-30" / "raw_GSPC__zzz.parquet")}
    (store2 / "_index.json").write_text(json.dumps({"raw_^GSPC": {"snapshots": [local_entry]}}), encoding="utf-8")
    _pull(dest, tmp_path / "pc2.db", tmp_path, store_root=str(store2))

    index = json.loads((store2 / "_index.json").read_text(encoding="utf-8"))
    assert set(index) == {"raw_VIX__abc", "raw_^GSPC"}
    (merged,) = index["raw_VIX__abc"]["snapshots"]
    assert Path(merged["path"]) == store2 / "snapshot=2026-08-19" / "raw_VIX__abc.parquet"
    assert Path(merged["path"]).read_bytes() == b"parquet-1"
    assert json.loads((store2 / "_series_observations.json").read_text(encoding="utf-8"))["BTC-USD"]["date_max"] == "2026-10-01"
    assert str(tmp_path) not in (dest / "store" / "_index.json").read_text(encoding="utf-8")


def test_push_removes_the_part_files_left_by_the_old_mechanism(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    dest.mkdir()
    for name in ("store.zip.part", "patrick.db.gz.part", "patrick (1).db.gz.part", "funds-PC1.db.gz.part"):
        (dest / name).write_bytes(b"")
    (dest / "photo.part").write_bytes(b"pas a nous")

    _push(dest, src, tmp_path)

    assert sorted(p.name for p in dest.glob("*.part")) == ["photo.part"]


def test_folder_transport_writes_final_names_directly(tmp_path):
    """Un `.part` oublié rendait le nom inutilisable sur Google Drive (Errno 22) : plus aucun fichier temporaire."""
    dest = tmp_path / "share"
    (dest / "a.bin.part").mkdir(parents=True)                            # nom `.part` inutilisable : l'ancien mécanisme échouait ici
    a, manifest = tmp_path / "a.bin", tmp_path / "manifest.json"
    a.write_bytes(b"x")
    manifest.write_text("{}", encoding="utf-8")

    sync.FolderTransport(str(dest)).upload({"a.bin": a, sync.MANIFEST: manifest})

    assert (dest / "a.bin").read_bytes() == b"x" and (dest / sync.MANIFEST).exists()


def test_push_stops_cleanly_when_the_share_disk_is_nearly_full_then_resumes(tmp_path, monkeypatch):
    store = tmp_path / "pc1_store"
    _write_store(store, {f"snapshot=2026-08-{d:02d}/raw_VIX__{d}.parquet": b"p" * 1000 for d in range(1, 6)})
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    real_free = sync._free_bytes
    monkeypatch.setattr(sync, "_free_bytes",
                        lambda p: 1 << 30 if Path(p).resolve().is_relative_to(dest.resolve()) else real_free(p))

    with pytest.raises(sync.SyncError, match="presque plein"):
        _push(dest, src, tmp_path, store_root=str(store))
    assert not (dest / "manifest.json").exists()                         # le partage garde son ancien état

    monkeypatch.setattr(sync, "_free_bytes", real_free)                  # de la place est revenue : la reprise termine
    _push(dest, src, tmp_path, store_root=str(store))
    assert len(list(dest.glob("store/snapshot=*/*.parquet"))) == 5 and (dest / "manifest.json").exists()


def test_a_share_in_the_old_zip_layout_can_still_be_read(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    manifest = _push(dest, src, tmp_path, layout="zip")

    assert manifest["format"] == 1 and (dest / "patrick.db.gz").exists()
    _pull(dest, tmp_path / "pc2.db", tmp_path)
    assert _count(tmp_path / "pc2.db", "run") == 2


def test_the_first_tree_push_over_an_old_share_reports_the_zip_files_left_behind(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path, layout="zip")

    manifest = _push(dest, src, tmp_path)

    assert manifest["format"] == 2
    assert manifest["legacy_assets_left"] == ["patrick.db.gz"]           # signalés, jamais supprimés par le programme
    assert (dest / "patrick.db.gz").exists()


@pytest.fixture
def pcs(tmp_path, monkeypatch):
    return PC(tmp_path, "pc1", monkeypatch), PC(tmp_path, "pc2", monkeypatch), tmp_path / "share"


def test_auto_publishes_at_most_once_per_interval(pcs):
    pc1, _, share = pcs
    pc1.seed(["a1"])
    assert [a.split(" :")[0] for a in pc1.auto(share, min_push_hours=24)["actions"]] == ["publication"]
    conn = trackdb.connect(pc1.db)
    trackdb.create_run(conn, "a_new", "T_new", 5, "snap_pc1", json.dumps({}), "cfg", "sha", 1)
    conn.close()

    held = pc1.auto(share, min_push_hours=24)

    assert held["actions"] == [] and "dernière publication il y a" in held["skipped"][0]
    assert json.loads((share / "manifest.json").read_text(encoding="utf-8"))["runs"] == 1
    assert [a.split(" :")[0] for a in pc1.auto(share, min_push_hours=0)["actions"]] == ["publication"]
    assert json.loads((share / "manifest.json").read_text(encoding="utf-8"))["runs"] == 2


def test_auto_merges_a_tree_share_including_models_under_the_new_ids(pcs, tmp_path):
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

    out = pc2.auto(share, only="pull")

    assert (share / "db" / "patrick.db").exists() and not (share / "patrick.db.gz").exists()
    assert out["merge"]["models"] == 1
    conn = sqlite3.connect(pc2.db)
    (path,) = [r[0] for r in conn.execute("SELECT artifact_path FROM trial WHERE run_id = 'a1' AND algo = 'lgbm'")]
    new_id = conn.execute("SELECT trial_id FROM trial WHERE run_id = 'a1' AND algo = 'lgbm'").fetchone()[0]
    conn.close()
    assert Path(path).read_bytes() == b"modele-a1" and Path(path).parent.name == str(new_id)


def test_changing_the_shared_folder_also_forgets_the_last_publication_time(tmp_path, monkeypatch):
    """Sinon la première publication vers le nouveau dossier (déjà occupé par l'autre PC) attendrait jusqu'à 24 h."""
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "settings.json"))
    sync.save_state(remote_sha="x", local_fp="y", pushed_at="2026-11-12T10:00:00+00:00", funds_fp="f")

    sync.forget_exchange()

    state = sync.load_state()
    assert "pushed_at" not in state and "remote_sha" not in state and "local_fp" not in state
    assert state["funds_fp"] == "f"                                      # les fonds ont leur propre suivi : inchangé
