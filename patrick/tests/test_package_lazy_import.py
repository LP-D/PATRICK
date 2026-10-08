"""`import patrick` doit rester léger : le lanceur de bureau l'importe à chaque démarrage et ne doit pas charger
pandas (≈ 1,7 s) avant d'afficher son écran de démarrage. Les ré-exports de `patrick.phase9` restent disponibles."""
from __future__ import annotations

import subprocess
import sys


def _run(code: str) -> str:
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
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
