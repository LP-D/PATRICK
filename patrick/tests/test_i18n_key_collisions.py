"""Deux dictionnaires de traduction ne donnent jamais deux textes différents à la même clé : `STRINGS.update` garde le dernier en
silence, et l'autre page affiche alors le mauvais texte (la carte « Premier lancement » de la Synthèse portait le titre « Fraîcheur des
données » : `fr_title` existait dans `i18n_pages` et dans `i18n_legacy`)."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

from patrick import webapp

WEBAPP = Path(webapp.__file__).parent
MODULES = sorted(p.stem for p in WEBAPP.glob("i18n*.py")) + ["glossary_earnings"]


def _literal_dicts(module: str) -> list[tuple[str, dict[str, object]]]:
    """Les dictionnaires `*STRINGS` écrits en toutes lettres au niveau du module : `(nom, {clé: texte français})`."""
    tree = ast.parse((WEBAPP / f"{module}.py").read_text(encoding="utf-8"))
    values = vars(importlib.import_module(f"patrick.webapp.{module}"))
    out = []
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        if not (isinstance(target, ast.Name) and target.id.endswith("STRINGS") and isinstance(getattr(node, "value", None), ast.Dict)):
            continue
        texts: dict[str, object] = {}
        for key, value in zip(node.value.keys, node.value.values):
            if not isinstance(key, ast.Constant):
                continue
            try:
                literal = ast.literal_eval(value)                       # le texte écrit ICI, pas celui qui a gagné la fusion
            except ValueError:
                literal = values[target.id].get(key.value)              # valeur construite par `_s(...)`
            texts[key.value] = literal.get("fr") if isinstance(literal, dict) else literal
        out.append((f"{module}.{target.id}", texts))
    return out


def test_no_key_has_two_different_texts():
    seen: dict[str, dict[str, object]] = {}
    for module in MODULES:
        for name, texts in _literal_dicts(module):
            for key, text in texts.items():
                seen.setdefault(key, {})[name] = text
    conflicts = {key: where for key, where in seen.items() if len(set(map(str, where.values()))) > 1}
    assert conflicts == {}


def test_the_first_launch_card_has_its_own_title():
    from patrick.webapp.i18n import STRINGS

    assert STRINGS["first_run_title"]["fr"].startswith("Premier lancement")
    assert STRINGS["fr_title"]["fr"] == "Fraîcheur des données"
    assert "t('first_run_title')" in (WEBAPP / "templates" / "synthesis.html").read_text(encoding="utf-8")
