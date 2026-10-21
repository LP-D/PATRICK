"""Hygiène du dépôt public (audit externe du 2026-10-19, points 10 et 11).

Le dépôt est public et le module patrimoine manipule des données personnelles : un `git add .` ne doit jamais
embarquer une base SQLite (`~/.patrick` mais aussi une copie de travail), un `.env`, la sortie d'un run ou l'état local
des outils d'agent. Ces tests exécutent git sur des fichiers réels : ils vérifient ce que git fait, pas le texte du
`.gitignore`.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


@pytest.fixture
def scratch_repo(tmp_path):
    """Dépôt jetable portant le `.gitignore` du vrai dépôt, avec des fichiers réels (git ne sait appliquer un motif
    de dossier qu'à un dossier qui existe)."""
    if not (REPO / ".gitignore").exists():
        pytest.skip("pas de .gitignore à la racine du dépôt")
    _git("init", "-q", cwd=tmp_path)
    shutil.copy(REPO / ".gitignore", tmp_path / ".gitignore")
    return tmp_path


def _touch(root: Path, *paths: str) -> None:
    for p in paths:
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text("x", encoding="utf-8")


@pytest.mark.parametrize("path", [
    ".env", "patrick/.env", ".env.local",
    "patrick.db", "patrick/data/copie.db", "patrick.db-wal", "patrick.db-shm", "export.sqlite3",
    "runs/mon_run/leaderboard.csv", "patrick/runs/mon_run/model.joblib",
    ".claude/settings.local.json", ".claude/worktrees/x/fichier.py", ".claude/launch.json",
])
def test_secrets_databases_runs_and_agent_state_are_never_added(scratch_repo, path):
    _touch(scratch_repo, path)
    assert _git("check-ignore", "-q", path, cwd=scratch_repo).returncode == 0, f"{path} serait ajouté par `git add .`"


@pytest.mark.parametrize("path", [
    ".claude/settings.json",                      # garde partagée : outils de planification soumis à approbation
    ".env.example",
    "patrick/patrick/tracking/db.py",
    "patrick/patrick/webapp/templates/runs.html",  # un fichier « runs », pas un dossier de sorties
    "docs/ops/application-bureau.md",
])
def test_versioned_files_stay_addable(scratch_repo, path):
    _touch(scratch_repo, path)
    assert _git("check-ignore", "-q", path, cwd=scratch_repo).returncode == 1, f"{path} ne doit pas être ignoré"


def test_no_committed_file_is_shadowed_by_an_ignore_rule():
    if not (REPO / ".git").exists():
        pytest.skip("pas un dépôt git")
    out = _git("ls-files", "-ci", "--exclude-standard", cwd=REPO)
    assert out.returncode == 0
    assert out.stdout.split() == [], "fichiers suivis mais que .gitignore masquerait"
