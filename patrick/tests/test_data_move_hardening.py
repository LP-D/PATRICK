"""Passe de correction après la relecture finale de la branche `feat/donnees-disque-d` (constats C1, I1 à I4, I6).

Ce que la relecture a montré : une finalisation qui refuse (à tort) dès que l'application a servi sur la nouvelle racine, une copie
qui pouvait écraser des snapshots créés là-bas, une finalisation partielle suivie d'un retour arrière, un journal écrasable, et la
page Réglages qui lisait encore les sauvegardes à l'ancien endroit. Tout sur des arbres et de petites bases sous `tmp_path`."""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_data_move import (  # noqa: F401  (fixtures et aides)
    artifact_paths,
    calm,
    make_db,
    pc,
    prepare,
    switched,
)
from typer.testing import CliRunner

from patrick import data_move, paths, settings
from patrick.cli import app as cli_app
from patrick.desktop import runtime, update
from patrick.webapp import settings_routes


def _newer(target: Path, than: Path, seconds: int = 10) -> None:
    ns = than.stat().st_mtime_ns + seconds * 10**9
    os.utime(target, ns=(ns, ns))


def live_move(pc):  # noqa: F811
    """Une source avec en plus des fichiers que l'application réécrit (séries observées, cache), copiée puis basculée."""
    p = prepare(pc, copy=False)
    (p.store / "_series_observations.json").write_text(json.dumps({"A": {"date_max": "2026-01-01"}}), encoding="utf-8")
    (pc.home / "cache").mkdir()
    (pc.home / "cache" / "x.json").write_text("v1", encoding="utf-8")
    data_move.copy_components(str(p.target))
    data_move.switch(str(p.target), db_path=p.db)
    return p


def app_activity(p) -> Path:
    """Ce que l'application fait sur la NOUVELLE racine après la bascule : un snapshot de plus (et son entrée d'index), des
    séries observées plus récentes, un cache rafraîchi (plus long, donc de taille différente)."""
    snapshot = p.target / "store" / "snapshot=2026-10-22" / "b__2.parquet"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(b"nouveau")
    index_path = p.target / "store" / "_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["k"]["snapshots"].append({"snapshot_id": "s2", "path": str(snapshot)})
    index_path.write_text(json.dumps(index), encoding="utf-8")
    series = p.target / "store" / "_series_observations.json"
    series.write_text(json.dumps({"A": {"date_max": "2026-10-22"}}), encoding="utf-8")
    _newer(series, p.store / "_series_observations.json")
    cache = p.target / "cache" / "x.json"
    cache.write_text("version-2-plus-longue", encoding="utf-8")
    _newer(cache, pc_cache(p))
    return snapshot


def pc_cache(p) -> Path:
    return p.store.parent / "cache" / "x.json"


def snapshot_ids(index_path: Path) -> set[str]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return {entry["snapshot_id"] for value in index.values() for entry in value["snapshots"]}


# --- C1 : la finalisation supporte une racine que l'application a utilisée --------------------------------------

def test_finalize_accepts_what_the_app_rewrote_on_the_new_root(pc):  # noqa: F811
    p = live_move(pc)
    snapshot = app_activity(p)

    out = data_move.finalize()

    assert sorted(out["removed"]) == ["cache", "models", "store"] and out["kept"] == []
    assert not (pc.home / "store").exists() and not (pc.home / "cache").exists()
    assert snapshot.read_bytes() == b"nouveau" and snapshot_ids(p.target / "store" / "_index.json") == {"s1", "s2"}
    assert (p.target / "cache" / "x.json").read_text(encoding="utf-8") == "version-2-plus-longue"


def test_finalize_refuses_when_the_source_is_newer_than_the_copy_for_a_mutable_file(pc):  # noqa: F811
    p = live_move(pc)
    _newer(pc_cache(p), p.target / "cache" / "x.json", seconds=100)

    with pytest.raises(data_move.MoveError, match="plus récente"):
        data_move.finalize()

    assert pc_cache(p).exists() and p.model.exists()


def test_finalize_refuses_when_a_source_snapshot_is_missing_from_the_target_index(pc):  # noqa: F811
    p = live_move(pc)
    index_path = p.target / "store" / "_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["k"]["snapshots"] = []
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(data_move.MoveError, match="index"):
        data_move.finalize()

    assert (p.store / "_index.json").exists()


def test_a_second_copy_never_loses_what_the_app_created_on_the_new_root(pc):  # noqa: F811
    p = live_move(pc)
    snapshot = app_activity(p)
    data_move.rollback(p.db, force=True)

    data_move.copy_components(str(p.target))

    assert snapshot_ids(p.target / "store" / "_index.json") == {"s1", "s2"} and snapshot.exists()
    assert json.loads((p.target / "store" / "_series_observations.json").read_text(encoding="utf-8"))["A"]["date_max"] == "2026-10-22"
    assert (p.target / "cache" / "x.json").read_text(encoding="utf-8") == "version-2-plus-longue"


def test_rollback_refuses_when_files_were_created_on_the_new_root_unless_forced(pc):  # noqa: F811
    p = live_move(pc)
    app_activity(p)
    before = artifact_paths(p.db)

    with pytest.raises(data_move.MoveError, match="créés dans la nouvelle racine"):
        data_move.rollback(p.db)
    assert artifact_paths(p.db) == before and settings.load()["data_root"] == str(p.target)

    assert data_move.rollback(p.db, force=True)["status"] == "rolled_back"
    assert "data_root" not in settings.load()


# --- I1 : une finalisation interrompue ne se défait pas, elle se reprend ------------------------------------------

def test_a_partial_finalize_blocks_rollback_and_can_be_resumed(pc, monkeypatch):  # noqa: F811
    p = switched(pc)
    real_rmtree, failed = shutil.rmtree, []

    def flaky(path, *args, **kwargs):
        if Path(path).name == "models" and not failed:
            failed.append(path)
            raise PermissionError("fichier verrouillé")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(data_move.shutil, "rmtree", flaky)

    with pytest.raises(data_move.MoveError, match="relance"):
        data_move.finalize()

    assert not (pc.home / "store").exists() and (pc.home / "models").exists()
    assert json.loads((pc.home / data_move.JOURNAL_NAME).read_text(encoding="utf-8"))["status"] == "finalizing"
    with pytest.raises(data_move.MoveError, match="finalisation"):
        data_move.rollback(p.db)

    out = data_move.finalize()

    assert out["removed"] == ["models"]                                               # la reprise ne supprime que le reste
    assert not (pc.home / "models").exists() and (p.target / "models" / "1" / "m.joblib").exists()
    assert json.loads((pc.home / data_move.JOURNAL_NAME).read_text(encoding="utf-8"))["status"] == "finalized"


def test_finalize_removes_read_only_files(pc):  # noqa: F811
    p = prepare(pc, copy=False)
    locked = pc.home / "models" / "1" / "lecture-seule.joblib"
    locked.write_bytes(b"verrou")
    os.chmod(locked, stat.S_IREAD)
    data_move.copy_components(str(p.target))
    data_move.switch(str(p.target), db_path=p.db)

    data_move.finalize()

    assert not (pc.home / "models").exists()


# --- I2 : finalize respecte les emplacements réellement actifs ---------------------------------------------------

def test_finalize_keeps_a_component_whose_active_folder_is_in_the_source(pc, monkeypatch):  # noqa: F811
    p = prepare(pc, copy=False)
    (pc.home / "feature_cache" / "ab").mkdir(parents=True)
    (pc.home / "feature_cache" / "ab" / "k.parquet").write_bytes(b"fc")
    data_move.copy_components(str(p.target))
    data_move.switch(str(p.target), db_path=p.db)
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(pc.home / "feature_cache"))     # « garder feature_cache sur C: »

    out = data_move.finalize()

    assert out["kept"] == ["feature_cache"] and sorted(out["removed"]) == ["models", "store"]
    assert (pc.home / "feature_cache" / "ab" / "k.parquet").read_bytes() == b"fc"


def test_finalize_refuses_when_the_active_root_is_not_the_target(pc, monkeypatch):  # noqa: F811
    p = switched(pc)
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(pc.home))

    with pytest.raises(data_move.MoveError, match="active"):
        data_move.finalize()

    assert p.model.exists()


# --- I3 : le journal n'est jamais écrasé -------------------------------------------------------------------------

def test_another_target_is_refused_while_a_move_is_pending(pc, calm):  # noqa: F811
    p = switched(pc)
    other = pc.tmp / "AUTRE"
    other.mkdir()
    journal_bytes = (pc.home / data_move.JOURNAL_NAME).read_bytes()

    problems = data_move.check_preconditions(str(other), db_path=p.db, port=8000)
    with pytest.raises(data_move.MoveError, match="en attente"):
        data_move.switch(str(other), db_path=p.db)

    assert any("en attente" in m for m in problems)
    assert (pc.home / data_move.JOURNAL_NAME).read_bytes() == journal_bytes


def test_switch_resumes_after_a_crash_before_the_setting_is_written(pc, monkeypatch):  # noqa: F811
    p = prepare(pc)
    before = artifact_paths(p.db)
    real_save = settings.save

    def crash(updates):
        raise RuntimeError("coupure de courant")

    monkeypatch.setattr(settings, "save", crash)
    with pytest.raises(RuntimeError):
        data_move.switch(str(p.target), db_path=p.db)
    journal = json.loads((pc.home / data_move.JOURNAL_NAME).read_text(encoding="utf-8"))
    assert journal["status"] == "switching" and artifact_paths(p.db) != before        # base déjà réécrite, réglage pas encore
    monkeypatch.setattr(settings, "save", real_save)

    done = data_move.switch(str(p.target), db_path=p.db)

    assert done["status"] == "switched" and settings.load()["data_root"] == str(p.target)
    assert done["artifact_paths"] == journal["artifact_paths"]                         # les anciennes valeurs d'origine sont gardées
    data_move.rollback(p.db)
    assert artifact_paths(p.db) == before


# --- I6 : changer ou retirer la racine sans déplacer -------------------------------------------------------------

def test_use_root_sets_and_clears_the_setting_and_refuses_a_missing_folder(pc):  # noqa: F811
    folder = pc.tmp / "ailleurs"
    folder.mkdir()

    assert data_move.use_root(str(folder))["data_root"] == str(folder) and settings.load()["data_root"] == str(folder)
    assert data_move.use_root(None)["data_root"] is None and "data_root" not in settings.load()
    with pytest.raises(data_move.MoveError, match="n'existe pas"):
        data_move.use_root(str(pc.tmp / "absent"))


def test_use_root_is_refused_while_a_move_is_pending(pc):  # noqa: F811
    switched(pc)

    with pytest.raises(data_move.MoveError, match="en attente"):
        data_move.use_root(None)


def test_the_missing_disk_message_names_the_command_that_fixes_it(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "absent"))

    assert "patrick data use" in paths.data_root_problem()


def test_cli_data_use(pc):  # noqa: F811
    folder = pc.tmp / "ailleurs"
    folder.mkdir()

    on = CliRunner().invoke(cli_app, ["data", "use", str(folder)])
    off = CliRunner().invoke(cli_app, ["data", "use", "--none"])
    neither = CliRunner().invoke(cli_app, ["data", "use"])

    assert on.exit_code == 0 and off.exit_code == 0 and "data_root" not in settings.load()
    assert neither.exit_code == 1 and "Refusé" in neither.output


# --- I4 : Réglages, sauvegarde manuelle et mise à jour suivent la racine de données -------------------------------

def test_the_settings_page_reads_backups_on_the_data_root():
    folder = paths.backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "patrick_backup_20261022_010101.db").write_bytes(b"x")

    assert settings_routes.backups_info()["count"] == 1
    assert settings_routes.paths()["backups"] == str(folder)


def test_manual_and_pre_update_backups_log_in_the_logs_folder(monkeypatch, tmp_path):
    spawned: list[list[str]] = []
    monkeypatch.setattr(runtime, "spawn_detached", lambda args, **kw: spawned.append(args))
    settings_routes.spawn_backup()
    db = tmp_path / "patrick.db"
    db.write_bytes(b"")
    monkeypatch.setenv("PATRICK_DB_PATH", str(db))
    ran: list[list[str]] = []
    monkeypatch.setattr(runtime, "run_hidden", lambda args, **kw: ran.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    update._backup_database(tmp_path)

    expected = str(runtime.log_dir() / "backup.log")
    for args in (spawned[0], ran[0]):
        assert args[args.index("--log-file") + 1] == expected
