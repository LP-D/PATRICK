"""Préférences de l'application de bureau : défauts, validation, écriture dans `settings.json`."""
from __future__ import annotations

import pytest

from patrick import settings
from patrick.desktop import prefs


def test_defaults_when_nothing_is_saved():
    assert prefs.all_prefs() == {"auto_update": True, "sync_on_start": True, "sync_on_close": True,
                                 "app_window": True, "port": 8000}
    assert prefs.setup_done() is False


def test_update_roundtrip_keeps_other_settings():
    settings.save({"parametric_jobs": 3})
    out = prefs.update({"auto_update": False, "port": 8123})
    assert out["auto_update"] is False and out["port"] == 8123 and out["sync_on_close"] is True
    assert settings.load()["parametric_jobs"] == 3          # fusion, pas écrasement


@pytest.mark.parametrize("changes", [{"auto_update": "yes"}, {"auto_update": 1}, {"port": 80}, {"port": 70000},
                                     {"port": "abc"}, {"port": True}, {"nope": True}])
def test_invalid_values_are_refused_without_writing_anything(changes):
    with pytest.raises(prefs.PrefError):
        prefs.update({"sync_on_close": False, **changes})
    assert prefs.get_bool("sync_on_close") is True          # rien n'a été écrit à moitié


def test_garbage_in_the_file_falls_back_to_defaults():
    settings.settings_path().write_text('{"auto_update": "peut-être", "port": "x"}', encoding="utf-8")
    assert prefs.get_bool("auto_update") is True
    assert prefs.get_port() == 8000


def test_mark_setup_done():
    prefs.mark_setup_done()
    assert prefs.setup_done() is True


def test_saving_none_removes_the_key():
    settings.save({"sync_folder": "X"})
    settings.save({"sync_folder": None})
    assert "sync_folder" not in settings.load()
