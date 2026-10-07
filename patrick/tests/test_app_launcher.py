"""Lanceur « mode app » (scripts/app/*.ps1) : scripts lisibles par Windows PowerShell 5.1 (ASCII, syntaxe valide)
et branchés sur les commandes `patrick` qui existent vraiment (serve, sync auto --only pull|push)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "scripts" / "app"
SCRIPTS = ["PATRICK-app.ps1", "install-app.ps1"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_is_ascii_so_powershell_5_reads_it_without_bom(name):
    data = (APP_DIR / name).read_bytes()
    assert all(b < 128 for b in data), f"{name} contient des octets non ASCII (UTF-8 sans BOM mal lu par PS 5.1)"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell absent")
@pytest.mark.parametrize("name", SCRIPTS)
def test_script_parses_without_syntax_error(name):
    cmd = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
           f"'{APP_DIR / name}', [ref]$null, [ref]$e); if ($e.Count) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}")
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_launcher_uses_real_cli_commands():
    from typer.testing import CliRunner

    from patrick.cli import app

    source = (APP_DIR / "PATRICK-app.ps1").read_text(encoding="ascii")
    assert "'sync', 'auto', '--only', 'pull'" in source
    assert "'sync', 'auto', '--only', 'push'" in source
    assert "'serve', '--port'" in source
    runner = CliRunner()
    assert runner.invoke(app, ["sync", "auto", "--help"]).exit_code == 0
    assert runner.invoke(app, ["serve", "--help"]).exit_code == 0


def test_launcher_never_kills_the_process_tree():
    """Le worker d'un entrainement est un descendant independant du serveur : arreter le serveur « en arbre »
    (taskkill /T) le tuerait."""
    source = (APP_DIR / "PATRICK-app.ps1").read_text(encoding="ascii").lower()
    assert "taskkill" not in source
