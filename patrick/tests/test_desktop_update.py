"""Mise à jour depuis GitHub (`patrick.desktop.update`) sur de vrais dépôts git locaux : dépôt « GitHub » nu,
copie de l'auteur, copie installée. Aucun réseau."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from patrick.desktop import update

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git indisponible")

_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True,
                          env=_ENV).stdout.strip()


def commit(repo: Path, name: str, content: str, message: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


class World:
    def __init__(self, tmp_path: Path):
        self.remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True, env=_ENV)
        self.author = tmp_path / "author"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.author)], check=True, env=_ENV)
        git(self.author, "checkout", "-q", "-B", "main")
        commit(self.author, "patrick/pyproject.toml", "deps = 1\n", "initial")
        git(self.author, "push", "-q", "origin", "main")
        self.stable = tmp_path / "stable"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.stable)], check=True, env=_ENV)

    def publish(self, name: str, content: str, message: str) -> None:
        commit(self.author, name, content, message)
        git(self.author, "push", "-q", "origin", "main")


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def _apply(world, **kw):
    calls = {"pip": 0, "backup": 0, "stop": 0}

    def pip(_project):
        calls["pip"] += 1
        return 0, ""

    def backup(_project):
        calls["backup"] += 1
        return 0, ""

    def stop():
        calls["stop"] += 1

    options = {"repo": world.stable, "worker_running": lambda: False, "backup": backup, "pip_install": pip,
               "stop_server": stop}
    options.update(kw)
    return update.apply(**options), calls


def test_up_to_date_does_nothing(world):
    result, calls = _apply(world)
    assert result["status"] == "uptodate" and calls == {"pip": 0, "backup": 0, "stop": 0}


def test_check_reports_news_without_touching_the_checkout(world):
    world.publish("a.txt", "1", "feat: première nouveauté")
    world.publish("b.txt", "2", "fix: deuxième")
    before = git(world.stable, "rev-parse", "HEAD")
    info = update.check(world.stable)
    assert info["state"] == "available" and info["behind"] == 2
    assert info["news"] == ["fix: deuxième", "feat: première nouveauté"]
    assert git(world.stable, "rev-parse", "HEAD") == before


def test_update_backs_up_first_stops_the_server_and_fast_forwards(world):
    world.publish("a.txt", "1", "feat: x")
    result, calls = _apply(world)
    assert result["status"] == "updated" and result["deps"] is False
    assert calls == {"pip": 0, "backup": 1, "stop": 1}
    assert (world.stable / "a.txt").read_text(encoding="utf-8") == "1"
    assert update.load_state()["last_update"]["to"] == git(world.author, "rev-parse", "HEAD")


def test_components_are_reinstalled_only_when_pyproject_changed(world):
    world.publish("patrick/pyproject.toml", "deps = 2\n", "chore: nouvelle dépendance")
    result, calls = _apply(world)
    assert result["status"] == "updated" and result["deps"] is True and calls["pip"] == 1


def test_failed_pip_rolls_back_to_the_previous_version(world):
    before = git(world.stable, "rev-parse", "HEAD")
    world.publish("patrick/pyproject.toml", "deps = 2\n", "chore: nouvelle dépendance")
    result, _ = _apply(world, pip_install=lambda _p: (1, "boom"))
    assert result["status"] == "failed" and "version précédente" in result["message"]
    assert git(world.stable, "rev-parse", "HEAD") == before
    assert (world.stable / "patrick/pyproject.toml").read_text(encoding="utf-8") == "deps = 1\n"


def test_failed_backup_cancels_the_update(world):
    before = git(world.stable, "rev-parse", "HEAD")
    world.publish("a.txt", "1", "feat: x")
    result, _ = _apply(world, backup=lambda _p: (1, "disque plein"))
    assert result["status"] == "skipped" and "sauvegarde" in result["message"]
    assert git(world.stable, "rev-parse", "HEAD") == before


def test_update_is_postponed_while_a_training_runs(world):
    world.publish("a.txt", "1", "feat: x")
    result, calls = _apply(world, worker_running=lambda: True)
    assert result["status"] == "skipped" and "entraînement" in result["message"] and calls["backup"] == 0


def test_local_modifications_block_the_update(world):
    world.publish("a.txt", "1", "feat: x")
    (world.stable / "patrick/pyproject.toml").write_text("modifié à la main\n", encoding="utf-8")
    result, calls = _apply(world)
    assert result["status"] == "skipped" and "locales" in result["message"] and calls["backup"] == 0


def test_a_development_branch_is_never_updated(world):
    git(world.stable, "checkout", "-q", "-b", "feature/x")
    world.publish("a.txt", "1", "feat: x")
    result, _ = _apply(world)
    assert result["status"] == "skipped" and "feature/x" in result["message"]


def test_diverged_local_history_is_left_alone(world):
    commit(world.stable, "local.txt", "x", "local only")
    world.publish("a.txt", "1", "feat: x")
    result, _ = _apply(world)
    assert result["status"] == "skipped" and "ancêtre" in result["message"]


def test_unreachable_remote_is_reported_not_raised(world, tmp_path):
    shutil.move(str(world.remote), str(tmp_path / "gone.git"))
    info = update.check(world.stable)
    assert info["state"] == "unavailable"
    result, _ = _apply(world)
    assert result["status"] == "skipped"


def test_not_a_git_checkout(tmp_path):
    assert update.check(tmp_path)["state"] == "unavailable"
    assert update.describe(tmp_path)["git"] is False


def test_describe_reads_the_installed_version(world):
    info = update.describe(world.stable)
    assert info["git"] and info["branch"] == "main" and len(info["commit"]) >= 7
