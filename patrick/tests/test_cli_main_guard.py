"""`python -m patrick.cli` doit voir TOUTES les commandes.

La garde `if __name__ == "__main__": app()` s'exécute à l'endroit où elle est écrite : un `@xxx_app.command` placé après
elle n'est pas encore enregistré, et `python -m patrick.cli data status` répondait « No such command » (la tâche
planifiée des news lance `python -m patrick.cli news refresh`). Le point d'entrée `patrick` importe le module en entier
et ne montrait pas le défaut.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "patrick" / "cli.py"
PROJECT = CLI.parents[1]


def _is_main_guard(node: ast.stmt) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


def test_main_guard_is_the_last_statement():
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    guards = [i for i, node in enumerate(tree.body) if _is_main_guard(node)]
    assert guards == [len(tree.body) - 1], "la garde __main__ doit être la dernière instruction de cli.py"


def test_module_invocation_lists_commands_defined_late():
    env = {**os.environ, "PYTHONUTF8": "1"}
    for group, command in (("data", "status"), ("news", "refresh")):
        out = subprocess.run([sys.executable, "-m", "patrick.cli", group, "--help"], cwd=PROJECT, env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                             check=False)
        assert out.returncode == 0, out.stderr
        assert command in out.stdout, f"`python -m patrick.cli {group}` ne voit pas `{command}`"
