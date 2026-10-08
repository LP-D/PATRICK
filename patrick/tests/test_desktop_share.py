"""Dossier partagé : contrôle d'un dossier candidat, détection d'un partage existant, enregistrement (assistant
de premier démarrage et page Réglages passent par `share.apply`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from patrick import settings, sync
from patrick.desktop import prefs, share


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    """Les réglages vivent dans `<pc>/.patrick` (comme `~/.patrick`) : les dossiers de partage des tests, eux,
    sont ailleurs sous `tmp_path`."""
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "pc" / ".patrick" / "settings.json"))


def _publish(folder: Path, *, runs: int = 5, personal: bool = False) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({
        "created_at": "2026-10-07T12:00:00+00:00", "runs": runs, "personal_included": personal,
        "files": {"patrick.db.gz": {"sha256": "abc", "size": 1}}}), encoding="utf-8")


def test_inspect_empty_existing_folder(tmp_path):
    info = share.inspect_folder(str(tmp_path))
    assert info["exists"] and info["writable"] and info["empty"] is True and info["has_share"] is False


def test_inspect_folder_with_a_share(tmp_path):
    _publish(tmp_path / "PATRICK", runs=158, personal=True)
    info = share.inspect_folder(str(tmp_path / "PATRICK"))
    assert info["has_share"] and info["runs"] == 158 and info["wealth_published"] is True
    assert share.default_wealth_reference(info) is False       # le partage a déjà un patrimoine : ce PC l'adopte


def test_first_pc_defaults_to_wealth_reference(tmp_path):
    assert share.default_wealth_reference(share.inspect_folder(str(tmp_path))) is True


def test_inspect_missing_folder_is_creatable_when_the_parent_exists(tmp_path):
    info = share.inspect_folder(str(tmp_path / "nouveau"))
    assert info["exists"] is False and info["creatable"] is True
    assert share.inspect_folder(str(tmp_path / "a" / "b"))["creatable"] is False


def test_inspect_ignores_relative_and_empty_paths():
    assert share.inspect_folder("")["exists"] is False
    assert share.inspect_folder("relatif/dossier")["exists"] is False


def test_validate_creates_the_last_level_and_normalises(tmp_path):
    out = share.validate_folder(str(tmp_path / "OneDrive" / ".." / "PATRICK"))
    assert Path(out) == tmp_path / "PATRICK" and Path(out).is_dir()


@pytest.mark.parametrize("bad", ["", "   ", "relatif"])
def test_validate_refuses_empty_and_relative(bad):
    with pytest.raises(share.ShareError):
        share.validate_folder(bad)


def test_validate_refuses_the_data_dir_and_its_subfolders():
    data = share.data_dir()
    with pytest.raises(share.ShareError):
        share.validate_folder(str(data))
    with pytest.raises(share.ShareError):
        share.validate_folder(str(data / "store"))


def test_validate_refuses_a_missing_parent(tmp_path):
    with pytest.raises(share.ShareError):
        share.validate_folder(str(tmp_path / "a" / "b" / "c"))


def test_find_existing_shares_scans_a_bounded_depth(tmp_path):
    _publish(tmp_path / "Documents" / "PERSO" / "PATRICK", runs=12)
    (tmp_path / "Photos").mkdir()
    found = share.find_existing_shares([str(tmp_path)])
    assert [Path(f["path"]) for f in found] == [tmp_path / "Documents" / "PERSO" / "PATRICK"]
    assert found[0]["runs"] == 12
    assert share.find_existing_shares([str(tmp_path)], max_depth=1) == []


def test_apply_folder_saves_everything_and_marks_setup_done(tmp_path, fake_task):
    out = share.apply(str(tmp_path / "PATRICK"), wealth_reference=True, schedule=True)
    assert out["folder"] == str(tmp_path / "PATRICK")
    assert sync.configured_folder() == out["folder"] and sync.is_wealth_reference() is True
    assert prefs.setup_done() is True
    assert fake_task.registered is True and out["task"]["registered"] is True


def test_apply_none_means_no_shared_folder_and_stops_the_task(tmp_path, fake_task):
    share.apply(str(tmp_path / "PATRICK"), schedule=True)
    out = share.apply(None)
    assert sync.configured_folder() is None and out["folder"] is None
    assert prefs.setup_done() is True and fake_task.registered is False


def test_changing_the_folder_forgets_the_previous_exchange_state(tmp_path):
    share.apply(str(tmp_path / "A"))
    sync.save_state(remote_sha="old", local_fp="old")
    share.apply(str(tmp_path / "A"))                              # même dossier : l'état est conservé
    assert sync.load_state()["remote_sha"] == "old"
    share.apply(str(tmp_path / "B"))                              # autre dossier : l'état ne vaut plus rien
    assert "remote_sha" not in sync.load_state() and "local_fp" not in sync.load_state()


def test_apply_reports_a_task_failure_without_losing_the_folder(tmp_path, monkeypatch):
    def boom(minutes: int = 60) -> str:
        raise sync.SyncError("schtasks : accès refusé")

    monkeypatch.setattr(sync, "register_task", boom)
    out = share.apply(str(tmp_path / "PATRICK"), schedule=True)
    assert sync.configured_folder() == out["folder"] and "accès refusé" in out["warnings"][0]


def test_apply_refuses_an_invalid_folder_and_changes_nothing(tmp_path):
    with pytest.raises(share.ShareError):
        share.apply(str(share.data_dir()))
    assert sync.configured_folder() is None and prefs.setup_done() is False


def test_apply_without_wealth_choice_keeps_the_previous_one(tmp_path):
    share.apply(str(tmp_path / "A"), wealth_reference=True)
    share.apply(str(tmp_path / "B"))
    assert sync.is_wealth_reference() is True


def test_suggestions_put_the_current_folder_first_then_existing_shares(tmp_path, monkeypatch):
    onedrive = tmp_path / "OneDrive - Perso"
    _publish(onedrive / "Docs" / "PATRICK", runs=3)
    monkeypatch.setenv("OneDrive", str(onedrive))
    monkeypatch.setattr(share.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    current = tmp_path / "ailleurs"
    share.apply(str(current))
    kinds = [(s["kind"], Path(s["path"])) for s in share.suggest_folders()]
    assert kinds[0] == ("current", current)
    assert ("existing", onedrive / "Docs" / "PATRICK") in kinds
    assert ("onedrive", onedrive / "PATRICK") in kinds


def test_settings_file_only_holds_known_keys_after_clearing(tmp_path):
    share.apply(str(tmp_path / "A"), wealth_reference=True)
    share.apply(None)
    assert "sync_folder" not in settings.load()
