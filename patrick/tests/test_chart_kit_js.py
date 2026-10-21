"""Tests des fonctions pures du moteur de graphiques (`static/chart_kit.js`) : exécutés sous Node (`tests/js/chart_kit.test.js`),
ignorés si Node n'est pas installé (la suite Python ne dépend pas de Node)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_chart_kit_pure_functions_under_node():
    done = subprocess.run(["node", str(JS_DIR / "chart_kit.test.js")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
@pytest.mark.parametrize("name", ["chart_kit.js", "charts.js", "market.js", "asset_stats.js", "drift.js", "fonds.js", "wealth.js"])
def test_chart_scripts_parse(name):
    """Garde-fou de syntaxe : un script de graphique cassé ne laisserait aucune erreur côté Python."""
    path = Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "static" / name
    done = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
