"""Passage de nuit planifié : les deux scripts PowerShell sont syntaxiquement valides et l'installateur n'installe rien sans `-Install`."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
POWERSHELL = shutil.which("powershell")

pytestmark = pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell de Windows requis")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, check=False)


@pytest.mark.parametrize("name", ["nightly_run.ps1", "schtasks_nightly.ps1"])
def test_the_script_parses_without_any_syntax_error(name):
    command = ("$e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{SCRIPTS / name}', [ref]$t, [ref]$e); if ($e.Count) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}")

    result = _run("-Command", command)

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_installer_shows_its_plan_and_installs_nothing_without_install():
    result = _run("-File", str(SCRIPTS / "schtasks_nightly.ps1"), "-At", "03:15", "-End", "sleep", "-IdleMinutes", "20")

    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "Patrick-Nightly" in out and "03:15" in out and "-End sleep" in out and "-IdleMinutes 20" in out
    assert "Rien n'a ete installe" in out

    listed = _run("-Command", "(Get-ScheduledTask -TaskName 'Patrick-Nightly' -ErrorAction SilentlyContinue | Measure-Object).Count")
    assert listed.stdout.strip() in ("0", "1")                              # l'aperçu n'a rien créé (1 seulement si déjà installée avant)


def test_the_installer_refuses_an_unknown_end_action():
    result = _run("-File", str(SCRIPTS / "schtasks_nightly.ps1"), "-End", "reboot")

    assert result.returncode != 0


def test_the_night_runs_the_funds_first_then_backup_and_sync_then_the_other_predictions(tmp_path):
    """Les ~2 000 prédictions durent une douzaine d'heures : sauvegarde et synchro ne doivent pas attendre derrière."""
    log = tmp_path / "nightly.log"

    result = _run("-File", str(SCRIPTS / "nightly_run.ps1"), "-DryRun", "-End", "none", "-LogFile", str(log))

    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.split(" == ", 1)[1] for line in log.read_text(encoding="utf-8").splitlines() if " == " in line]
    assert [line.split(" :")[0] for line in lines] == [
        "reseau", "mise a jour", "actualites", "predictions utiles aux fonds et pilote automatique", "sauvegarde",
        "synchronisation", "autres predictions", "fin"]
    assert "--funds-only" in lines[3] and "--skip-funds" in lines[6]
