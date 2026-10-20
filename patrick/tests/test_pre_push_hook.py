"""Garde de sortie `.githooks/pre-push` (audit externe du 2026-10-19, point 11).

Le garde d'entrée (`scripts/check_env_sync.sh`) ne suffit pas : l'incident du 2026-08-07 a montré qu'un conteneur
peut repartir d'un instantané ancien sans que rien ne le signale. On bloque aussi à la sortie : pas de suppression
de branche ou d'étiquette, pas de réécriture d'historique publié (push forcé), sauf sur les branches jetables
(`wip/`, `tmp/`, `golden-regen/`) ou en le demandant explicitement (`PATRICK_ALLOW_UNSAFE_PUSH=1`).

Chaque test pousse pour de vrai vers un dépôt distant jetable : on vérifie ce que git a laissé passer.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".githooks"


def _git(*args: str, cwd: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PATRICK_ALLOW_UNSAFE_PUSH"}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t", **(env_extra or {})})
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False)


@pytest.fixture
def repo(tmp_path):
    if not (HOOKS / "pre-push").exists():
        pytest.fail("`.githooks/pre-push` est absent")
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("config", "core.hooksPath", str(HOOKS), cwd=work)
    _commit(work, "a")
    assert _git("push", "-q", "origin", "main", cwd=work).returncode == 0     # premier push : branche neuve
    return work, remote


def _commit(work: Path, name: str) -> None:
    (work / f"{name}.txt").write_text(name, encoding="utf-8")
    _git("add", ".", cwd=work)
    assert _git("commit", "-q", "-m", name, cwd=work).returncode == 0


def _remote_branches(remote: Path) -> set[str]:
    out = _git("for-each-ref", "--format=%(refname)", cwd=remote).stdout
    return set(out.split())


def _rewrite_last_commit(work: Path) -> None:
    assert _git("commit", "-q", "--amend", "-m", "réécrit", cwd=work).returncode == 0


def test_a_normal_push_goes_through(repo):
    work, remote = repo
    _commit(work, "b")
    assert _git("push", "origin", "main", cwd=work).returncode == 0
    _git("checkout", "-q", "-b", "feature/x", cwd=work)
    assert _git("push", "origin", "feature/x", cwd=work).returncode == 0
    assert {"refs/heads/main", "refs/heads/feature/x"} <= _remote_branches(remote)


def test_rewriting_published_history_is_refused(repo):
    work, remote = repo
    before = _git("rev-parse", "main", cwd=remote).stdout
    _rewrite_last_commit(work)
    out = _git("push", "--force", "origin", "main", cwd=work)
    assert out.returncode != 0 and "réécriture" in out.stderr
    assert _git("rev-parse", "main", cwd=remote).stdout == before


def test_rewriting_is_allowed_on_disposable_branches(repo):
    work, _remote = repo
    _git("checkout", "-q", "-b", "wip/essai", cwd=work)
    _commit(work, "b")
    assert _git("push", "origin", "wip/essai", cwd=work).returncode == 0
    _rewrite_last_commit(work)
    assert _git("push", "--force", "origin", "wip/essai", cwd=work).returncode == 0


def test_deleting_a_branch_is_refused_except_disposable_ones(repo):
    work, remote = repo
    for name in ("feature/y", "golden-regen/essai"):
        _git("branch", name, cwd=work)
        assert _git("push", "-q", "origin", name, cwd=work).returncode == 0

    assert _git("push", "origin", "--delete", "main", cwd=work).returncode != 0
    assert _git("push", "origin", "--delete", "feature/y", cwd=work).returncode != 0
    assert {"refs/heads/main", "refs/heads/feature/y"} <= _remote_branches(remote)

    assert _git("push", "origin", "--delete", "golden-regen/essai", cwd=work).returncode == 0
    assert "refs/heads/golden-regen/essai" not in _remote_branches(remote)


def test_tags_can_be_created_but_neither_deleted_nor_moved(repo):
    work, remote = repo
    _git("tag", "v1", cwd=work)
    assert _git("push", "origin", "v1", cwd=work).returncode == 0
    assert _git("push", "origin", "--delete", "v1", cwd=work).returncode != 0
    _commit(work, "b")
    _git("tag", "-f", "v1", cwd=work)
    assert _git("push", "--force", "origin", "v1", cwd=work).returncode != 0
    assert "refs/tags/v1" in _remote_branches(remote)


def test_the_override_is_explicit_and_says_so(repo):
    work, _remote = repo
    _rewrite_last_commit(work)
    out = _git("push", "--force", "origin", "main", cwd=work, env_extra={"PATRICK_ALLOW_UNSAFE_PUSH": "1"})
    assert out.returncode == 0
    assert "PATRICK_ALLOW_UNSAFE_PUSH" in out.stderr
