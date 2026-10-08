"""Mise à jour de la version installée depuis GitHub (branche `main`), avec sauvegarde de la base avant et retour
en arrière si l'installation des composants échoue.

Règles de sécurité : on ne touche qu'à un dépôt PROPRE (aucune modification locale suivie) qui est sur `main`
et dont la version locale est un ancêtre de `origin/main` (avance rapide uniquement, jamais de fusion ni
d'écrasement); on ne met jamais à jour pendant un entraînement.
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from patrick.desktop import runtime

BRANCH = "main"
STATE_NAME = "update_state.json"
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "10"}

Progress = Callable[[str], None]


def state_path() -> Path:
    return runtime.data_dir() / STATE_NAME


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(**fields) -> None:
    data = {**load_state(), **fields}
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Git:
    def __init__(self, repo: Path):
        self.repo = repo
        self.exe = shutil.which("git")

    def __call__(self, *args: str, timeout: float = 30):
        return runtime.run_hidden([self.exe or "git", "-C", str(self.repo), *args], timeout=timeout, env=_GIT_ENV)

    def out(self, *args: str, timeout: float = 30) -> str:
        proc = self(*args, timeout=timeout)
        return proc.stdout.strip() if proc.returncode == 0 else ""


def describe(repo: Path | None = None) -> dict:
    """Version installée (lecture seule, sans réseau) : `{"commit", "branch", "date", "git"}`."""
    repo = repo or runtime.repo_root()
    git = _Git(repo)
    if not git.exe or not (repo / ".git").exists():
        return {"git": False, "commit": None, "branch": None, "date": None, "repo": str(repo)}
    return {"git": True, "repo": str(repo), "commit": git.out("rev-parse", "--short", "HEAD") or None,
            "branch": git.out("rev-parse", "--abbrev-ref", "HEAD") or None,
            "date": git.out("log", "-1", "--format=%cs") or None}


def check(repo: Path | None = None, *, fetch: bool = True) -> dict:
    """Y a-t-il une nouvelle version ? `{"state", "message", "behind", "news", ...}` avec `state` parmi :
    `uptodate`, `available`, `unavailable` (pas de git / hors ligne), `skipped` (dépôt de développement)."""
    repo = repo or runtime.repo_root()
    git = _Git(repo)
    if not git.exe or not (repo / ".git").exists():
        return {"state": "unavailable", "message": "git est introuvable : les mises à jour automatiques sont indisponibles."}
    branch = git.out("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        return {"state": "skipped", "message": f"Ce dossier est sur la branche « {branch} » (développement) : "
                                              f"pas de mise à jour automatique.", "branch": branch}
    if git.out("status", "--porcelain", "--untracked-files=no"):
        return {"state": "skipped", "message": "Des modifications locales sont présentes : mise à jour ignorée.",
                "branch": branch}
    if fetch:
        fetched = git("fetch", "-q", "origin", BRANCH, timeout=40)
        if fetched.returncode != 0:
            return {"state": "unavailable", "message": f"GitHub est injoignable (hors ligne ?) : "
                                                       f"{(fetched.stderr or fetched.stdout).strip()}",
                    "branch": branch}
    local, remote = git.out("rev-parse", "HEAD"), git.out("rev-parse", f"origin/{BRANCH}")
    if not local or not remote:
        return {"state": "unavailable", "message": "Version introuvable.", "branch": branch}
    if local == remote:
        return {"state": "uptodate", "message": "PATRICK est à jour.", "behind": 0, "local": local, "remote": remote,
                "branch": branch}
    if git("merge-base", "--is-ancestor", local, remote).returncode != 0:
        return {"state": "skipped", "message": "La version locale n'est pas un ancêtre de origin/main : "
                                              "mise à jour ignorée.", "local": local, "remote": remote,
                "branch": branch}
    behind = int(git.out("rev-list", "--count", f"HEAD..origin/{BRANCH}") or 0)
    news = git.out("log", "-n", "8", "--format=%s", f"HEAD..origin/{BRANCH}").splitlines()
    return {"state": "available", "message": f"{behind} nouveauté(s) disponible(s).", "behind": behind,
            "news": news, "local": local, "remote": remote, "branch": branch}


def _pip_install(project_dir: Path) -> tuple[int, str]:
    proc = runtime.run_hidden([runtime.console_python(), "-m", "pip", "install", "-q", "-e", ".[web]"],
                              cwd=project_dir, timeout=1200)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _backup_database(project_dir: Path) -> tuple[int, str]:
    from patrick.tracking import db as trackdb

    if not os.path.exists(trackdb.default_db_path()):
        return 0, "pas de base à sauvegarder"
    proc = runtime.run_hidden(
        [runtime.console_python(), str(project_dir / "scripts" / "backup_db.py"), "--log-file",
         str(runtime.data_dir() / "backups" / "backup.log")], cwd=project_dir, timeout=900)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def apply(*, repo: Path | None = None, progress: Progress | None = None,
          stop_server: Callable[[], object] | None = None,
          worker_running: Callable[[], bool] = runtime.worker_running,
          backup: Callable[[Path], tuple[int, str]] = _backup_database,
          pip_install: Callable[[Path], tuple[int, str]] = _pip_install) -> dict:
    """Met à jour si une nouvelle version existe. Renvoie `{"status", "message", "from", "to", "deps"}` avec `status`
    parmi `uptodate`, `updated`, `skipped`, `failed`. Ne lève jamais."""
    repo = repo or runtime.repo_root()
    say = progress or (lambda _text: None)
    info = check(repo)
    if info["state"] == "uptodate":
        _save_state(checked_at=_now(), available=False)
        return {"status": "uptodate", "message": info["message"]}
    if info["state"] != "available":
        return {"status": "skipped", "message": info["message"]}
    if worker_running():
        return {"status": "skipped", "message": "Mise à jour reportée : un entraînement est en cours."}

    git, project = _Git(repo), repo / "patrick"
    local, remote = info["local"], info["remote"]
    say("Mise à jour de PATRICK…")
    if stop_server:
        stop_server()
    code, detail = backup(project)
    if code != 0:
        return {"status": "skipped", "message": f"Mise à jour annulée : la sauvegarde de la base a échoué ({detail})."}
    merged = git("merge", "--ff-only", f"origin/{BRANCH}", timeout=60)
    if merged.returncode != 0:
        return {"status": "failed", "message": f"Mise à jour annulée : {(merged.stderr or merged.stdout).strip()}"}
    deps = bool(git.out("diff", "--name-only", local, remote, "--", "patrick/pyproject.toml"))
    if deps:
        say("Mise à jour des composants (quelques minutes)…")
        code, detail = pip_install(project)
        if code != 0:
            git("reset", "--hard", local, timeout=60)
            return {"status": "failed", "from": local, "message": "La mise à jour des composants a échoué : "
                                                                   f"PATRICK reste sur la version précédente. {detail[-300:]}"}
    _save_state(checked_at=_now(), available=False, last_update={"at": _now(), "from": local, "to": remote})
    return {"status": "updated", "from": local, "to": remote, "deps": deps,
            "message": f"Mis à jour : {local[:7]} -> {remote[:7]}" + (" (composants réinstallés)" if deps else "")}
