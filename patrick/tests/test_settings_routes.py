"""Page Réglages et API `/api/app/*` : réglages, dossier partagé, relance, protection contre les requêtes venues
d'autres sites. Les actions système (processus détachés, explorateur, raccourcis) sont remplacées."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick import sync
from patrick.desktop import launcher, prefs, runtime, share, update
from patrick.webapp import i18n, nav_registry, settings_routes
from patrick.webapp.app import app

TEMPLATES = Path(nav_registry.__file__).resolve().parent / "templates"
STATIC = Path(nav_registry.__file__).resolve().parent / "static"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "pc" / ".patrick" / "settings.json"))
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


@pytest.fixture
def calls(monkeypatch):
    """Remplace tout ce qui toucherait le système, et enregistre les appels."""
    recorded: dict[str, list] = {"relaunch": [], "backup": [], "open": [], "shortcuts": []}
    monkeypatch.setattr(settings_routes, "spawn_relaunch", lambda **kw: recorded["relaunch"].append(kw))
    monkeypatch.setattr(settings_routes, "spawn_backup", lambda: recorded["backup"].append(True))
    monkeypatch.setattr(settings_routes, "open_in_explorer", lambda path: recorded["open"].append(path))
    monkeypatch.setattr(settings_routes.shortcuts, "create", lambda: recorded["shortcuts"].append(True) or 0)
    monkeypatch.setattr(runtime, "worker_running", lambda: False)
    return recorded


@pytest.fixture
def client(calls):
    return TestClient(app, base_url="http://127.0.0.1:8000")


def folder_in(tmp_path: Path, name: str = "PATRICK") -> str:
    return str(tmp_path / name)


# --- page -----------------------------------------------------------------------------------------------------------

def test_page_renders_in_both_languages(client):
    fr = client.get("/reglages")
    assert fr.status_code == 200 and "Partage entre PC" in fr.text and "Mises à jour" in fr.text
    en = client.get("/reglages", cookies={i18n.LANG_COOKIE: "en"})
    assert "Sharing between PCs" in en.text and "Updates" in en.text


def test_settings_button_is_in_the_topbar_of_every_page_and_in_the_palette(client):
    html = client.get("/").text
    assert 'href="/reglages"' in html and 'id="nav-settings"' in html
    palette = json.loads(re.search(r'<script id="cmdk-data"[^>]*>(.*?)</script>', html, re.DOTALL).group(1))
    assert any(item["url"] == "/reglages" for item in palette)


def test_settings_page_is_registered_in_the_navigation_registry():
    assert "/reglages" in nav_registry.registered_routes()
    on_settings = {u["url"]: u["active"] for u in nav_registry.utility_links("/reglages")}
    on_home = {u["url"]: u["active"] for u in nav_registry.utility_links("/")}
    assert on_settings["/reglages"] is True and on_home["/reglages"] is False


def test_every_string_used_by_the_page_exists_in_both_languages():
    html = (TEMPLATES / "reglages.html").read_text(encoding="utf-8")
    keys = set(re.findall(r"t\('([a-z0-9_]+)'", html))
    assert keys, "aucune clé trouvée : le motif est périmé"
    for key in keys:
        assert key in i18n.STRINGS, key
        assert i18n.STRINGS[key]["fr"] and i18n.STRINGS[key]["en"], key


def test_every_string_used_by_the_script_is_exported_to_javascript():
    script = (STATIC / "reglages.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'tr\("([a-z0-9_]+)"', script))
    exported = i18n.js_strings("fr")
    for key in keys:
        assert key in exported, key


# --- protection -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("headers", [
    {"origin": "http://evil.example"},
    {"origin": "null"},
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site"},
    {"host": "evil.example"},
    {"host": "127.0.0.1.evil.example:8000"},
])
def test_requests_from_other_sites_are_refused(client, headers):
    assert client.get("/api/app/overview", headers=headers).status_code == 403
    assert client.post("/api/app/prefs", json={"auto_update": False}, headers=headers).status_code == 403
    assert client.post("/api/app/share/apply", json={"folder": None}, headers=headers).status_code == 403
    assert prefs.get_bool("auto_update") is True and not prefs.setup_done()


def test_same_origin_requests_pass(client):
    ok = {"origin": "http://127.0.0.1:8000", "sec-fetch-site": "same-origin"}
    assert client.get("/api/app/overview", headers=ok).status_code == 200
    assert client.get("/api/app/overview", headers={"host": "localhost:8000"}).status_code == 200


def test_post_body_must_be_a_json_object(client):
    assert client.post("/api/app/prefs", content="n'importe quoi").status_code == 400
    assert client.post("/api/app/prefs", json=[1, 2]).status_code == 400


# --- vue d'ensemble et préférences --------------------------------------------------------------------------------

def test_overview_describes_this_pc(client, tmp_path):
    body = client.get("/api/app/overview").json()
    assert body["share"]["folder"] is None and body["prefs"]["port"] == 8000
    assert body["backups"] == {"count": 0, "latest": None}
    assert body["boot_id"] == settings_routes.BOOT_ID
    assert body["paths"]["data"] == str(share.data_dir())


def test_overview_counts_backups(client):
    folder = runtime.data_dir() / "backups"
    folder.mkdir(parents=True)
    (folder / "patrick_backup_20261007_233000.db").write_bytes(b"x")
    (folder / "autre.txt").write_text("x")
    assert client.get("/api/app/overview").json()["backups"]["count"] == 1


def test_prefs_roundtrip_and_validation(client):
    assert client.post("/api/app/prefs", json={"sync_on_close": False, "port": 8123}).json()["port"] == 8123
    assert prefs.get_bool("sync_on_close") is False
    bad = client.post("/api/app/prefs", json={"port": 22})
    assert bad.status_code == 400 and "port" in bad.json()["error"].lower()
    assert client.post("/api/app/prefs", json={"inconnu": True}).status_code == 400


# --- dossier partagé ------------------------------------------------------------------------------------------------

def test_inspect_apply_and_clear_the_shared_folder(client, tmp_path):
    folder = folder_in(tmp_path)
    info = client.post("/api/app/share/inspect", json={"folder": folder}).json()
    assert info["creatable"] is True and info["default_wealth_reference"] is True

    done = client.post("/api/app/share/apply", json={"folder": folder, "wealth_reference": True, "schedule": True})
    assert done.status_code == 200 and sync.configured_folder() == folder and Path(folder).is_dir()
    assert done.json()["task"]["registered"] is True
    assert client.get("/api/app/overview").json()["share"]["wealth_reference"] is True

    cleared = client.post("/api/app/share/apply", json={"folder": None})
    assert cleared.status_code == 200 and sync.configured_folder() is None
    assert cleared.json()["task"]["registered"] is False


def test_apply_refuses_a_bad_folder_with_a_message(client):
    out = client.post("/api/app/share/apply", json={"folder": str(share.data_dir())})
    assert out.status_code == 400 and "différent" in out.json()["error"]
    assert sync.configured_folder() is None


def test_status_without_folder_and_with_an_unreadable_one(client, tmp_path):
    assert client.get("/api/app/share/status").json() == {"folder": None}
    client.post("/api/app/share/apply", json={"folder": folder_in(tmp_path)})
    (tmp_path / "PATRICK" / "manifest.json").write_text("pas du json", encoding="utf-8")
    assert "illisible" in client.get("/api/app/share/status").json()["error"]


def test_status_of_an_empty_share(client, tmp_path):
    client.post("/api/app/share/apply", json={"folder": folder_in(tmp_path)})
    from patrick.tracking import db as trackdb

    trackdb.connect().close()
    body = client.get("/api/app/share/status").json()
    assert body["remote"] is None and body["need_push"] is True and body["local_runs"] == 0


def test_suggestions_endpoint(client, tmp_path, monkeypatch):
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    monkeypatch.setenv("OneDrive", str(onedrive))
    kinds = [s["kind"] for s in client.get("/api/app/share/suggestions").json()["suggestions"]]
    assert "onedrive" in kinds


def test_browse_returns_the_folder_picked_in_the_dialog(client, monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return type("P", (), {"stdout": 'bruit\n{"folder": "C:\\\\Choisi"}\n', "returncode": 0})()

    monkeypatch.setattr(runtime, "run_hidden", fake_run)
    out = client.post("/api/app/share/browse", json={"initial": "C:\\Départ"}).json()
    assert out == {"folder": "C:\\Choisi"} and "pick-folder" in seen["args"] and "C:\\Départ" in seen["args"]
    monkeypatch.setattr(runtime, "run_hidden", lambda args, **kw: type("P", (), {"stdout": "", "returncode": 1})())
    assert client.post("/api/app/share/browse", json={}).json() == {"folder": None}


# --- relance : synchroniser / mettre à jour ------------------------------------------------------------------------

def test_sync_now_needs_a_folder_then_launches_the_helper(client, calls, tmp_path):
    assert client.post("/api/app/sync-now").status_code == 400
    client.post("/api/app/share/apply", json={"folder": folder_in(tmp_path)})
    assert client.post("/api/app/sync-now").json() == {"ok": True}
    assert calls["relaunch"] == [{"do_sync": True}]


def test_sync_now_and_update_are_refused_while_a_training_runs(client, calls, tmp_path, monkeypatch):
    client.post("/api/app/share/apply", json={"folder": folder_in(tmp_path)})
    monkeypatch.setattr(runtime, "worker_running", lambda: True)
    assert client.post("/api/app/sync-now").status_code == 409
    assert client.post("/api/app/update/apply").status_code == 409
    assert calls["relaunch"] == []


def test_update_check_and_apply(client, calls, monkeypatch):
    monkeypatch.setattr(update, "check", lambda *a, **k: {"state": "available", "behind": 2, "news": ["a", "b"]})
    assert client.post("/api/app/update/check").json()["behind"] == 2
    assert client.post("/api/app/update/apply").json() == {"ok": True}
    assert calls["relaunch"] == [{"do_update": True}]


def test_relaunch_state_exposes_progress_and_the_boot_id(client):
    assert client.get("/api/app/relaunch").json() == {"boot_id": settings_routes.BOOT_ID}
    launcher._write_json(launcher.RELAUNCH_STATE, {"state": "running", "message": "Synchronisation…", "steps": []})
    body = client.get("/api/app/relaunch").json()
    assert body["state"] == "running" and body["message"] == "Synchronisation…"
    assert client.get("/api/app/boot").json() == {"boot_id": settings_routes.BOOT_ID}


def test_spawn_relaunch_targets_this_server(monkeypatch):
    captured = {}
    monkeypatch.setattr(runtime, "spawn_detached", lambda args, **kw: captured.update(args=args, kw=kw))
    settings_routes.spawn_relaunch(do_sync=True, do_update=True)
    args = captured["args"]
    assert args[1:4] == ["-m", "patrick.desktop", "relaunch"] and "--sync" in args and "--update" in args
    assert args[args.index("--server-pid") + 1] == str(__import__("os").getpid())


# --- divers ---------------------------------------------------------------------------------------------------------

def test_open_only_known_existing_folders(client, calls, tmp_path):
    assert client.post("/api/app/open", json={"what": "C:\\Windows"}).status_code == 400
    assert client.post("/api/app/open", json={"what": "shared"}).status_code == 404          # pas de dossier partagé
    client.post("/api/app/share/apply", json={"folder": folder_in(tmp_path)})
    assert client.post("/api/app/open", json={"what": "shared"}).status_code == 200
    assert client.post("/api/app/open", json={"what": "logs"}).status_code == 200
    assert calls["open"] == [tmp_path / "PATRICK", runtime.log_dir()]


def test_backup_now_requires_a_database(client, calls):
    assert client.post("/api/app/backup-now").status_code == 400
    Path(settings_routes._db_path()).write_bytes(b"x")
    assert client.post("/api/app/backup-now").json() == {"ok": True} and calls["backup"] == [True]


def test_shortcuts_endpoint(client, calls):
    assert client.post("/api/app/shortcuts").json() == {"ok": True} and calls["shortcuts"] == [True]
