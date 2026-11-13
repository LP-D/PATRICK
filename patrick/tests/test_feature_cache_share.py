"""Cache de variables à deux étages : le cache LOCAL reste le seul que les runs lisent en continu ; une RÉSERVE PARTAGÉE (dossier d'un
Google Drive vu par les deux PC) ne sert qu'aux défauts de cache, et on n'y AJOUTE que du neuf.

Pourquoi pas la racine du cache directement sur le Drive : chaque lecture y met à jour la date du fichier (`os.utime`, base de
l'éviction), l'éviction y supprime des fichiers (la corbeille de Google les garde 30 jours, dans le quota), un Drive débranché
bloquerait PATRICK, et chaque défaut de cache serait un téléchargement. Les fichiers (`<empreinte>.parquet`) sont nommés par
l'empreinte de leur contenu : deux PC qui calculent la même chose produisent le même fichier."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from patrick import feature_cache_share as share
from patrick import paths, settings
from patrick.cli import app
from patrick.features import pool_cache


def _df(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({"a": range(n), "b": [float(i) for i in range(n)]})


def _key(char: str = "a") -> str:
    return (char * 64)[:64]


def _shared(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "drive" / "feature_cache"
    folder.mkdir(parents=True)
    monkeypatch.setenv(paths.ENV_FEATURE_CACHE_SHARED, str(folder))
    return folder


def _shared_file(shared: Path, key: str) -> Path:
    return shared / key[:2] / f"{key}.parquet"


# --- dossier partagé ---------------------------------------------------------------------------------------------------------

def test_the_shared_reserve_is_off_until_it_is_configured_and_present(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_FEATURE_CACHE_SHARED, raising=False)
    assert paths.feature_cache_shared_dir() is None

    folder = tmp_path / "drive" / "feature_cache"
    settings.save({paths.KEY_FEATURE_CACHE_SHARED: str(folder)})
    assert paths.feature_cache_shared_dir() is None                      # réglé mais absent (Drive débranché) : jamais d'exception

    folder.mkdir(parents=True)
    assert paths.feature_cache_shared_dir() == folder


def test_the_environment_variable_overrides_the_setting(tmp_path, monkeypatch):
    settings.save({paths.KEY_FEATURE_CACHE_SHARED: str(tmp_path / "reglage")})
    other = _shared(tmp_path, monkeypatch)
    assert paths.feature_cache_shared_dir() == other


# --- lecture et écriture à deux étages ---------------------------------------------------------------------------------------

def test_a_local_miss_is_filled_from_the_shared_reserve(tmp_path, monkeypatch):
    shared = _shared(tmp_path, monkeypatch)
    key = _key()
    target = _shared_file(shared, key)
    target.parent.mkdir(parents=True)
    _df().to_parquet(target)
    assert not pool_cache._path(key).exists()

    frame = pool_cache.load(key)

    assert frame is not None and list(frame["a"]) == [0, 1, 2, 3, 4]
    assert pool_cache._path(key).exists()                                # copié en local : le prochain défaut ne retélécharge pas


def test_reading_from_the_shared_reserve_never_touches_the_shared_file(tmp_path, monkeypatch):
    """Une date modifiée à chaque lecture ferait renvoyer le fichier par Google Drive."""
    shared = _shared(tmp_path, monkeypatch)
    key = _key()
    target = _shared_file(shared, key)
    target.parent.mkdir(parents=True)
    _df().to_parquet(target)
    os.utime(target, ns=(10**18, 10**18))

    pool_cache.load(key)
    pool_cache.load(key)

    assert target.stat().st_mtime_ns == 10**18


def test_saving_also_publishes_to_the_shared_reserve(tmp_path, monkeypatch):
    shared = _shared(tmp_path, monkeypatch)
    key = _key("b")

    pool_cache.save(key, _df())

    assert pool_cache._path(key).exists()
    assert _shared_file(shared, key).read_bytes() == pool_cache._path(key).read_bytes()


def test_a_broken_file_in_the_shared_reserve_is_discarded_and_published_again(tmp_path, monkeypatch):
    shared = _shared(tmp_path, monkeypatch)
    key = _key("i")
    target = _shared_file(shared, key)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"pas du parquet")                                # envoi interrompu côté Drive

    assert pool_cache.load(key) is None                                  # lu comme un défaut de cache, jamais d'exception
    assert not target.exists() and not pool_cache._path(key).exists()    # le fichier cassé est retiré des deux étages

    pool_cache.save(key, _df())                                          # le calcul suivant le republie
    assert target.exists() and pd.read_parquet(target).shape == (5, 2)


def test_a_miss_in_both_tiers_is_still_a_miss(tmp_path, monkeypatch):
    _shared(tmp_path, monkeypatch)
    assert pool_cache.load(_key("c")) is None


def test_saving_works_without_any_shared_reserve(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_FEATURE_CACHE_SHARED, raising=False)
    pool_cache.save(_key("d"), _df())
    assert pool_cache._path(_key("d")).exists()


def test_a_failing_shared_reserve_never_breaks_a_run(tmp_path, monkeypatch):
    """Drive figé ou `Errno 22` : le cache local suffit, l'erreur ne remonte jamais."""
    _shared(tmp_path, monkeypatch)

    def broken(*args, **kwargs):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(share.shutil, "copyfile", broken)
    key = _key("e")

    pool_cache.save(key, _df())
    assert pool_cache._path(key).exists()
    assert pool_cache.load(_key("f")) is None


def test_nothing_is_published_once_the_shared_reserve_reaches_its_ceiling(tmp_path, monkeypatch):
    shared = _shared(tmp_path, monkeypatch)
    (shared / "zz").mkdir()
    (shared / "zz" / "deja.parquet").write_bytes(b"x" * 5000)
    settings.save({share.KEY_MAX_GB: 0.000001})                          # plafond d'environ 1 000 octets
    key = _key("g")

    pool_cache.save(key, _df())

    assert pool_cache._path(key).exists() and not _shared_file(shared, key).exists()


def test_a_file_already_shared_is_not_copied_again(tmp_path, monkeypatch):
    shared = _shared(tmp_path, monkeypatch)
    key = _key("h")
    pool_cache.save(key, _df())
    published = _shared_file(shared, key)
    os.utime(published, ns=(10**18, 10**18))

    pool_cache.save(key, _df())

    assert published.stat().st_mtime_ns == 10**18


# --- amorçage ----------------------------------------------------------------------------------------------------------------

def _local_files(root: Path, n: int, size: int = 1000) -> list[Path]:
    out = []
    for i in range(n):
        key = f"{i:02x}" + "0" * 62
        path = root / key[:2] / f"{key}.parquet"
        path.parent.mkdir(parents=True)
        path.write_bytes(bytes([i]) * size)
        os.utime(path, (1_000_000 + i, 1_000_000 + i))                   # le fichier i est plus récent que le fichier i-1
        out.append(path)
    return out


def test_seeding_copies_the_most_recent_files_first_up_to_the_ceiling_then_resumes(tmp_path):
    local, shared = tmp_path / "local", tmp_path / "drive"
    files = _local_files(local, 5)

    first = share.seed(local, shared, max_bytes=3000, min_free_bytes=0)

    assert first["copied_files"] == 3 and first["stopped"] == "plafond"
    assert sorted(p.name for p in shared.rglob("*.parquet")) == sorted(f.name for f in files[2:])      # les trois plus récents

    second = share.seed(local, shared, max_bytes=5000, min_free_bytes=0)

    assert second["copied_files"] == 2 and second["stopped"] is None     # reprise : les trois premiers ne sont pas recopiés
    assert len(list(shared.rglob("*.parquet"))) == 5


def test_a_dry_run_copies_nothing(tmp_path):
    local, shared = tmp_path / "local", tmp_path / "drive"
    _local_files(local, 4)

    result = share.seed(local, shared, max_bytes=10**6, min_free_bytes=0, dry_run=True)

    assert result["copied_files"] == 4 and result["dry_run"] is True
    assert not shared.exists() or not list(shared.rglob("*.parquet"))


def test_seeding_waits_for_free_space_then_goes_on(tmp_path):
    local, shared = tmp_path / "local", tmp_path / "drive"
    _local_files(local, 3)
    calls = {"n": 0}
    slept: list[float] = []

    def free_bytes(_path):
        calls["n"] += 1
        return 10 if calls["n"] <= 2 else 10**12                        # le cache du Drive se vide : la place revient

    result = share.seed(local, shared, max_bytes=10**6, min_free_bytes=1000, free_bytes=free_bytes,
                        sleep=slept.append, wait_max_s=3600)

    assert result["copied_files"] == 3 and result["stopped"] is None and len(slept) == 2


def test_seeding_stops_cleanly_when_the_space_never_comes_back(tmp_path):
    local, shared = tmp_path / "local", tmp_path / "drive"
    _local_files(local, 3)

    result = share.seed(local, shared, max_bytes=10**6, min_free_bytes=1000, free_bytes=lambda _p: 10,
                        sleep=lambda _s: None, wait_max_s=60)

    assert result["copied_files"] == 0 and result["stopped"] == "espace"
    assert not list(shared.rglob("*.parquet"))


def test_a_truncated_copy_is_replaced_on_the_next_seeding(tmp_path):
    local, shared = tmp_path / "local", tmp_path / "drive"
    (file,) = _local_files(local, 1)
    share.seed(local, shared, max_bytes=10**6, min_free_bytes=0)
    published = shared / file.parent.name / file.name
    published.write_bytes(b"coupe")

    share.seed(local, shared, max_bytes=10**6, min_free_bytes=0)

    assert published.read_bytes() == file.read_bytes()


# --- commande ----------------------------------------------------------------------------------------------------------------

def test_the_command_sets_the_reserve_and_seeds_it(tmp_path):
    local = paths.feature_cache_dir()
    _local_files(local, 3)
    shared = tmp_path / "drive" / "feature_cache"

    result = CliRunner().invoke(app, ["storage", "share-feature-cache", "--to", str(shared), "--max-gb", "1",
                                      "--min-free-gb", "0"])

    assert result.exit_code == 0, result.output
    assert settings.load()[paths.KEY_FEATURE_CACHE_SHARED] == str(shared)
    assert len(list(shared.rglob("*.parquet"))) == 3
    assert "3 fichier(s)" in result.output


def test_the_command_refuses_the_local_cache_folder_itself(tmp_path):
    local = paths.feature_cache_dir()
    local.mkdir(parents=True, exist_ok=True)

    result = CliRunner().invoke(app, ["storage", "share-feature-cache", "--to", str(local)])

    assert result.exit_code == 1 and "cache local" in result.output
    assert paths.KEY_FEATURE_CACHE_SHARED not in settings.load()


def test_the_command_can_switch_the_reserve_off_without_deleting_anything(tmp_path):
    local = paths.feature_cache_dir()
    _local_files(local, 2)
    shared = tmp_path / "drive" / "feature_cache"
    runner = CliRunner()
    assert runner.invoke(app, ["storage", "share-feature-cache", "--to", str(shared), "--min-free-gb", "0"]).exit_code == 0

    result = runner.invoke(app, ["storage", "share-feature-cache", "--off"])

    assert result.exit_code == 0 and paths.KEY_FEATURE_CACHE_SHARED not in settings.load()
    assert len(list(shared.rglob("*.parquet"))) == 2                    # le contenu du Drive n'est jamais supprimé


def test_the_data_move_tool_ignores_the_shared_reserve(tmp_path, monkeypatch):
    """La réserve partagée n'appartient pas à la racine de données de ce PC : `patrick data move` ne la déplace jamais."""
    from patrick import data_move

    shared = _shared(tmp_path, monkeypatch)
    assert data_move.component_path("feature_cache") != shared
