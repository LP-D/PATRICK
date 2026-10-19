"""`import patrick` doit rester léger : le lanceur de bureau l'importe à chaque démarrage et ne doit pas charger
pandas (≈ 1,7 s) avant d'afficher son écran de démarrage. Les ré-exports de `patrick.phase9` restent disponibles."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(code: str) -> str:
    # Dossier du projet (celui qui contient `patrick/__init__.py`), jamais le dossier de lancement de pytest : en CI c'est la racine du dépôt,
    # où le dossier `patrick/` (sans __init__) masque le vrai paquet, vu par le sous-processus comme un espace de noms (« unknown location »).
    project_dir = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=project_dir)
    # Le message d'erreur du sous-processus fait partie de l'échec : sans lui, la CI n'affichait que « code de sortie 1 ».
    assert proc.returncode == 0, f"code de sortie {proc.returncode}\n--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
    return proc.stdout.strip()


def test_import_patrick_does_not_load_pandas():
    assert _run("import sys, patrick; print('pandas' in sys.modules)") == "False"


def test_desktop_package_stays_light():
    code = ("import sys, patrick.desktop.prefs, patrick.desktop.runtime, patrick.desktop.launcher; "
            "print('pandas' in sys.modules)")
    assert _run(code) == "False"


def test_phase9_reexports_still_work():
    code = ("import patrick; from patrick import DecisionJournal, take_snapshot; "
            "import patrick.phase9 as p; print(patrick.DecisionJournal is p.DecisionJournal)")
    assert _run(code) == "True"


def test_unknown_attribute_raises():
    code = "import patrick\ntry:\n    patrick.nope\nexcept AttributeError as e:\n    print('ok')"
    assert _run(code) == "ok"
