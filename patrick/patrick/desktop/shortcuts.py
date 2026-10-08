"""Raccourcis Windows : icône PATRICK sur le bureau, dossier « PATRICK » dans le menu Démarrer."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from patrick.desktop import runtime

# Les dossiers « Bureau » et « Programmes » sont demandés à Windows (ils peuvent être redirigés vers OneDrive).
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$items = $env:PATRICK_SHORTCUTS | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
if ($env:PATRICK_SHORTCUTS_ROOT) {   # tests : jamais le vrai bureau
    $desktop = Join-Path $env:PATRICK_SHORTCUTS_ROOT 'Desktop'
    $start = Join-Path $env:PATRICK_SHORTCUTS_ROOT 'Programs\PATRICK'
} else {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $start = Join-Path ([Environment]::GetFolderPath('Programs')) 'PATRICK'
}
foreach ($i in $items) {
    $dir = if ($i.where -eq 'desktop') { $desktop } else { $start }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $s = $shell.CreateShortcut((Join-Path $dir $i.name))
    $s.TargetPath = $i.target
    $s.Arguments = $i.arguments
    $s.WorkingDirectory = $i.workdir
    if ($i.icon) { $s.IconLocation = "$($i.icon),0" }
    $s.Description = $i.description
    $s.WindowStyle = $i.window
    $s.Save()
}
Write-Output "$desktop|$start"
"""


def icon_path() -> Path | None:
    icon = runtime.repo_root() / "app" / "patrick.ico"
    return icon if icon.exists() else None


def plan(*, pythonw: Path, python: Path, workdir: Path, icon: Path | None) -> list[dict]:
    """Les raccourcis à créer (données pures, testables). `where` : `desktop` ou `start` (menu Démarrer)."""
    base = {"workdir": str(workdir), "icon": str(icon) if icon else ""}
    return [
        {**base, "where": "desktop", "name": "PATRICK.lnk", "target": str(pythonw),
         "arguments": "-m patrick.desktop launch", "description": "Ouvre PATRICK", "window": 7},
        {**base, "where": "start", "name": "PATRICK.lnk", "target": str(pythonw),
         "arguments": "-m patrick.desktop launch", "description": "Ouvre PATRICK", "window": 7},
        {**base, "where": "start", "name": "Mettre à jour PATRICK.lnk", "target": str(python),
         "arguments": "-m patrick.desktop update --pause", "description": "Sauvegarde puis met à jour PATRICK",
         "window": 1},
        {**base, "where": "start", "name": "Arrêter PATRICK.lnk", "target": str(pythonw),
         "arguments": "-m patrick.desktop stop", "description": "Arrête le serveur PATRICK", "window": 7},
    ]


def create() -> int:
    """Crée (ou recrée) les raccourcis. Peut être relancé sans risque. Renvoie 0 si tout est créé."""
    if os.name != "nt":
        print("Les raccourcis ne sont gérés que sous Windows.")
        return 1
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    items = plan(pythonw=pythonw if pythonw.exists() else exe, python=exe, workdir=runtime.project_dir(),
                 icon=icon_path())
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:
        f.write(_SCRIPT)
        script = f.name
    try:
        proc = runtime.run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                                  timeout=60, env={"PATRICK_SHORTCUTS": json.dumps(items)})
    finally:
        Path(script).unlink(missing_ok=True)
    if proc.returncode != 0:
        print(f"Raccourcis non créés : {(proc.stderr or proc.stdout).strip()}")
        return 1
    desktop, _, start = proc.stdout.strip().partition("|")
    print(f"Raccourcis créés sur le bureau ({desktop}) et dans le menu Démarrer ({start}).")
    return 0
