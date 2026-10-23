"""Garde-fou (spec 2026-10-21, §5) : `~/.patrick` n'est écrit en dur qu'à un seul endroit, `patrick/paths.py`.

Tout autre module passe par `patrick.paths` pour la base, les journaux, le magasin, les modèles, les caches, les sauvegardes, les
archives et les rapports. Sinon, déplacer la racine de données laisserait des écritures silencieuses sur l'ancien disque.
Les docstrings et commentaires, qui expliquent l'emplacement par défaut, ne comptent pas : seul le code construit un chemin."""
from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]                    # <projet>/patrick
SCANNED = [PACKAGE / "patrick", PACKAGE / "scripts"]
# Les seuls autres modules qui peuvent écrire `.patrick` : l'emplacement des RÉGLAGES de la machine (le dossier maison ne se
# déplace pas : `settings.json` y contient justement le réglage `data_root`).
ALLOWED = {"paths.py", "settings.py"}
_HOME_PATH = re.compile(r"~[/\\]\.patrick|[/\\]\.patrick\b|^\.patrick$")


def _code_strings(source: str):
    """Chaînes de caractères du code, sans les docstrings (module, classe, fonction)."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


_COMPONENTS = {"store", "models", "feature_cache", "cache", "backups", "archive", "reports"}


def _builds_a_component_from_the_settings_folder(source: str):
    """`runtime.data_dir() / "backups"` : un dossier de la racine de données bâti sur le dossier maison (qui ne se déplace pas)."""
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant)
                and node.right.value in _COMPONENTS and isinstance(node.left, ast.Call)):
            func = node.left.func
            if (isinstance(func, ast.Attribute) and func.attr == "data_dir") or (isinstance(func, ast.Name) and func.id == "data_dir"):
                yield node.lineno, node.right.value


def test_no_data_component_is_built_from_the_settings_folder():
    offenders = []
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if ".venv" in path.parts:
                continue
            for line, name in _builds_a_component_from_the_settings_folder(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(PACKAGE)}:{line}: data_dir() / {name!r} (utiliser patrick.paths)")
    assert not offenders, "dossiers de la racine de données bâtis sur le dossier maison :\n" + "\n".join(offenders)


def test_the_home_folder_is_written_only_in_paths_py():
    offenders = []
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if path.name in ALLOWED or ".venv" in path.parts:
                continue
            for line, text in _code_strings(path.read_text(encoding="utf-8")):
                if _HOME_PATH.search(text):
                    offenders.append(f"{path.relative_to(PACKAGE)}:{line}: {text[:70]!r}")
    assert not offenders, "chemins `.patrick` en dur hors de paths.py :\n" + "\n".join(offenders)
