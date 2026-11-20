"""Fonctions pures de `static/placements.js`, exécutées sous Node (ignorées si Node est absent)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_placements_pure_functions_under_node():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "placements.test.js")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_placements_script_parses():
    done = subprocess.run(["node", "--check", str(ROOT / "patrick" / "webapp" / "static" / "placements.js")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
