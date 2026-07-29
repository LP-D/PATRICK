"""Rapport d'audit, C4 -- garde-fou structurel : `patrick.tracking.holdout_diagnostic`
stocke le score holdout de TOUTE la grille SCAN (pas seulement le gagnant),
pour un diagnostic de généralisation (corrélation de rang test/holdout,
section E de l'audit). Ce diagnostic doit rester strictement en LECTURE SEULE
pour le rapport -- si le code de sélection, le leaderboard ou le tuning
pouvaient le lire, le holdout cesserait d'être une évaluation véritablement
hors échantillon (le classique "peeking" que la Phase 2.1 existe justement
pour éviter). Ce test échoue si un import de `holdout_diagnostic` apparaît
dans l'un de ces modules -- inspection statique de l'AST, pas une convention
de code review."""
from __future__ import annotations

import ast
from pathlib import Path

PATRICK_ROOT = Path(__file__).resolve().parent.parent / "patrick"

FORBIDDEN_TARGET = "holdout_diagnostic"

# Modules/paquets qui ne doivent JAMAIS importer holdout_diagnostic : ils
# décident (sélection de features, classement leaderboard, recherche
# d'hyperparamètres) -- le holdout ne doit influencer aucune décision.
GUARDED_PATHS = [
    PATRICK_ROOT / "selection",
    PATRICK_ROOT / "pipeline" / "leaderboard.py",
    PATRICK_ROOT / "tuning",
]


def _imported_module_names(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            for alias in node.names:
                names.add(alias.name)
    return names


def _collect_py_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.py"))


def test_holdout_diagnostic_module_exists_and_is_isolated():
    holdout_mod = PATRICK_ROOT / "tracking" / "holdout_diagnostic.py"
    assert holdout_mod.exists(), "patrick/tracking/holdout_diagnostic.py doit exister (C4)."

    offenders = []
    for guarded_path in GUARDED_PATHS:
        assert guarded_path.exists(), f"chemin surveillé introuvable : {guarded_path}"
        for py_file in _collect_py_files(guarded_path):
            imported = _imported_module_names(py_file)
            if any(FORBIDDEN_TARGET in name for name in imported):
                offenders.append(str(py_file.relative_to(PATRICK_ROOT.parent)))

    assert not offenders, (
        f"import de '{FORBIDDEN_TARGET}' détecté dans un module de sélection/leaderboard/"
        f"tuning -- interdit structurellement (cf. docstring de holdout_diagnostic.py) : "
        f"{offenders}"
    )


def test_holdout_diagnostic_read_functions_are_not_called_from_guarded_modules():
    """Contrôle complémentaire au précédent (qui bloque l'IMPORT) : vérifie
    aussi qu'aucun appel textuel à `write_holdout_diagnostic`/
    `read_holdout_diagnostic_for_run`/`spearman_test_vs_holdout` n'apparaît
    dans les modules surveillés -- redondant si le test d'import passe (on ne
    peut pas appeler une fonction d'un module non importé), mais protège
    contre un import indirect (ex. `import patrick.tracking as t; t.holdout_diagnostic...`)."""
    forbidden_calls = (
        "write_holdout_diagnostic", "read_holdout_diagnostic_for_run", "spearman_test_vs_holdout",
    )
    offenders = []
    for guarded_path in GUARDED_PATHS:
        for py_file in _collect_py_files(guarded_path):
            text = py_file.read_text()
            if any(call in text for call in forbidden_calls):
                offenders.append(str(py_file.relative_to(PATRICK_ROOT.parent)))
    assert not offenders, f"référence textuelle à une fonction holdout_diagnostic trouvée : {offenders}"
