"""Page `/reglages` et API `/api/app/*` : tout ce qu'un utilisateur règle sans toucher à un fichier —
dossier partagé entre PC, mises à jour, fenêtre, sauvegardes.

SÉCURITÉ : ces routes modifient des réglages locaux et peuvent lancer des processus. Le serveur n'écoute que
sur 127.0.0.1, mais une page web quelconque ouverte dans le navigateur peut tout de même lui envoyer des
requêtes (CSRF, ou « DNS rebinding »). Chaque route passe donc par `_guard` : l'en-tête `Host` doit être local,
et `Origin` / `Sec-Fetch-Site` ne doivent pas désigner un autre site.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from patrick import sync
from patrick.desktop import launcher, prefs, runtime, share, shortcuts, update

BOOT_ID = uuid.uuid4().hex                      # change à chaque démarrage du serveur : la page sait qu'il a redémarré
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
OPEN_TARGETS = ("data", "logs", "backups", "shared", "install")


def _guard(request: Request) -> None:
    """Refuse toute requête qui ne vient pas de la page PATRICK locale."""
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    if hostname.lower() not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Hôte non autorisé.")
    origin = request.headers.get("origin")
    if origin and origin != "null" and urlparse(origin).netloc != host:
        raise HTTPException(status_code=403, detail="Requête d'un autre site refusée.")
    if origin == "null" or request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="Requête d'un autre site refusée.")


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Corps JSON attendu.")
    return body


def _backups_dir() -> Path:
    return runtime.data_dir() / "backups"


def backups_info() -> dict:
    folder = _backups_dir()
    files = sorted(folder.glob("patrick_backup_*.db"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    latest = datetime.fromtimestamp(files[-1].stat().st_mtime).strftime("%Y-%m-%d %H:%M") if files else None  # noqa: DTZ006
    return {"count": len(files), "latest": latest}


def paths() -> dict:
    return {"data": str(runtime.data_dir()), "logs": str(runtime.log_dir()), "backups": str(_backups_dir()),
            "install": str(runtime.repo_root()), "shared": sync.configured_folder()}


def spawn_relaunch(*, do_sync: bool = False, do_update: bool = False) -> None:
    """Lance l'assistant détaché qui arrête ce serveur, met à jour / synchronise, puis le relance."""
    args = [runtime.console_python(), "-m", "patrick.desktop", "relaunch", "--server-pid", str(os.getpid())]
    if do_sync:
        args.append("--sync")
    if do_update:
        args.append("--update")
    runtime.spawn_detached(args, cwd=runtime.project_dir(), log=runtime.log_dir() / "relaunch.log")


def spawn_backup() -> None:
    runtime.spawn_detached(
        [runtime.console_python(), str(runtime.project_dir() / "scripts" / "backup_db.py"), "--log-file",
         str(_backups_dir() / "backup.log")], cwd=runtime.project_dir())


def open_in_explorer(target: Path) -> None:
    if os.name == "nt":
        os.startfile(target)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])


def _db_path() -> str:
    from patrick.tracking import db as trackdb

    return trackdb.default_db_path()


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n de l'application."""

    @app.get("/reglages")
    def settings_page(request: Request):
        return templates.TemplateResponse(request, "reglages.html", {**context(request), "windows": os.name == "nt"})

    @app.get("/api/app/boot")
    def boot(request: Request):
        _guard(request)
        return {"boot_id": BOOT_ID}

    @app.get("/api/app/overview")
    def overview(request: Request):
        _guard(request)
        return {
            "boot_id": BOOT_ID,
            "prefs": prefs.all_prefs(),
            "share": share.current(),
            "version": update.describe(),
            "update": update.load_state(),
            "paths": paths(),
            "backups": backups_info(),
            "last_launch": launcher.read_json(launcher.LAST_LAUNCH),
            "windows": os.name == "nt",
        }

    @app.post("/api/app/prefs")
    async def set_prefs(request: Request):
        _guard(request)
        try:
            return prefs.update(await _json(request))
        except prefs.PrefError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    # --- dossier partagé -------------------------------------------------------------------------------------------
    @app.get("/api/app/share/suggestions")
    async def share_suggestions(request: Request):
        _guard(request)
        return {"suggestions": await run_in_threadpool(share.suggest_folders)}

    @app.post("/api/app/share/inspect")
    async def share_inspect(request: Request):
        _guard(request)
        body = await _json(request)
        info = await run_in_threadpool(share.inspect_folder, str(body.get("folder") or ""))
        return {**info, "default_wealth_reference": share.default_wealth_reference(info)}

    @app.post("/api/app/share/browse")
    async def share_browse(request: Request):
        _guard(request)
        body = await _json(request)

        def pick() -> str | None:
            args = [runtime.console_python(), "-m", "patrick.desktop", "pick-folder"]
            if body.get("initial"):
                args += ["--initial", str(body["initial"])]
            proc = runtime.run_hidden(args, cwd=runtime.project_dir(), timeout=600)
            try:
                return json.loads(proc.stdout.strip().splitlines()[-1]).get("folder")
            except (ValueError, IndexError, AttributeError):
                return None

        return {"folder": await run_in_threadpool(pick)}

    @app.post("/api/app/share/apply")
    async def share_apply(request: Request):
        _guard(request)
        body = await _json(request)
        folder = body.get("folder") or None
        try:
            return await run_in_threadpool(
                lambda: share.apply(folder, wealth_reference=body.get("wealth_reference"),
                                    schedule=body.get("schedule")))
        except share.ShareError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/app/share/status")
    async def share_status(request: Request):
        _guard(request)
        folder = sync.configured_folder()
        if not folder:
            return {"folder": None}
        try:
            return await run_in_threadpool(sync.status, folder)
        except (sync.SyncError, OSError, ValueError, KeyError) as exc:
            return JSONResponse({"error": f"Dossier partagé illisible : {exc}"}, status_code=200)

    # --- relance / mise à jour -------------------------------------------------------------------------------------
    @app.post("/api/app/sync-now")
    async def sync_now(request: Request):
        _guard(request)
        if not sync.configured_folder():
            return JSONResponse({"error": "Aucun dossier partagé."}, status_code=400)
        if await run_in_threadpool(lambda: runtime.worker_running()):
            return JSONResponse({"error": "busy"}, status_code=409)
        spawn_relaunch(do_sync=True)
        return {"ok": True}

    @app.post("/api/app/update/check")
    async def update_check(request: Request):
        _guard(request)
        return await run_in_threadpool(update.check)

    @app.post("/api/app/update/apply")
    async def update_apply(request: Request):
        _guard(request)
        if await run_in_threadpool(lambda: runtime.worker_running()):
            return JSONResponse({"error": "busy"}, status_code=409)
        spawn_relaunch(do_update=True)
        return {"ok": True}

    @app.get("/api/app/relaunch")
    def relaunch_state(request: Request):
        _guard(request)
        return {"boot_id": BOOT_ID, **launcher.read_json(launcher.RELAUNCH_STATE)}

    # --- divers ----------------------------------------------------------------------------------------------------
    @app.post("/api/app/open")
    async def open_folder(request: Request):
        _guard(request)
        what = (await _json(request)).get("what")
        if what not in OPEN_TARGETS:
            raise HTTPException(status_code=400, detail="Dossier inconnu.")
        target = paths().get(what)
        if not target or not Path(target).is_dir():
            raise HTTPException(status_code=404, detail="Dossier introuvable.")
        open_in_explorer(Path(target))
        return {"ok": True}

    @app.post("/api/app/shortcuts")
    async def make_shortcuts(request: Request):
        _guard(request)
        code = await run_in_threadpool(shortcuts.create)
        return JSONResponse({"ok": code == 0}, status_code=200 if code == 0 else 500)

    @app.post("/api/app/backup-now")
    async def backup_now(request: Request):
        _guard(request)
        if not os.path.exists(_db_path()):
            return JSONResponse({"error": "Pas de base à sauvegarder."}, status_code=400)
        spawn_backup()
        return {"ok": True}
