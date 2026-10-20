"""`scripts/git_facts.sh` : l'état git en faits bruts (audit externe du 2026-10-19, point 11).

Les comptes rendus d'un agent se vérifient contre des faits, pas contre un autre résumé : branche, commit, avance /
retard sur le distant, fichiers modifiés, mis de côté. Le script ne déduit rien : une ligne `clé=valeur` par fait.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git_facts.sh"
SH = shutil.which("sh") or shutil.which("bash")


def _git(*args: str, cwd: Path) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env, check=True)
    return out.stdout.strip()


def _facts(cwd: Path) -> dict[str, str]:
    out = subprocess.run([SH, str(SCRIPT)], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True)
    return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)


@pytest.mark.skipif(SH is None, reason="pas de shell POSIX")
def test_it_prints_the_raw_state_of_a_repository(tmp_path):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=work)
    (work / "a.txt").write_text("a", encoding="utf-8")
    _git("add", ".", cwd=work)
    _git("commit", "-q", "-m", "premier", cwd=work)
    _git("push", "-q", "-u", "origin", "main", cwd=work)
    pushed = _git("rev-parse", "HEAD", cwd=work)

    (work / "b.txt").write_text("b", encoding="utf-8")
    _git("add", ".", cwd=work)
    _git("commit", "-q", "-m", "second, pas poussé", cwd=work)
    (work / "a.txt").write_text("a modifié", encoding="utf-8")        # fichier suivi modifié
    (work / "nouveau.txt").write_text("n", encoding="utf-8")         # fichier non suivi

    facts = _facts(work)
    assert facts["branch"] == "main"
    assert facts["head"] == _git("rev-parse", "HEAD", cwd=work) != pushed
    assert facts["upstream"] == "origin/main"
    assert (facts["ahead"], facts["behind"]) == ("1", "0")
    assert facts["remote_head"] == pushed                           # lu sur le distant, pas déduit
    assert facts["dirty_tracked"] == "1" and facts["untracked"] == "1"
    assert facts["last_commit"].endswith("second, pas poussé")


@pytest.mark.skipif(SH is None, reason="pas de shell POSIX")
def test_it_says_so_when_there_is_no_remote(tmp_path):
    _git("init", "-q", "-b", "main", str(tmp_path), cwd=tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "seul", cwd=tmp_path)
    facts = _facts(tmp_path)
    assert facts["upstream"] == "none" and facts["remote_head"] == "unreachable"
    assert facts["ahead"] == facts["behind"] == "unknown"
