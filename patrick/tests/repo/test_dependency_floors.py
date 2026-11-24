"""Les dépendances de `patrick/pyproject.toml` doivent rester installables avec les versions figées de la suite lente.

La suite lente installe `pip install -c .github/constraints-py311.txt -e "./patrick[dev,web]"` et ne tourne qu'au push sur
main : une PR qui relève un plancher au-dessus de la version figée passe sa propre CI (suite rapide seule), puis casse main
et bloque `stable`. Constaté le 2026-11-24 (PR 94, Dependabot : `pydantic>=2.14.4` contre `pydantic==2.13.5` figé).
Ce test, dans la suite rapide, attrape le cas dès la PR.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "patrick" / "pyproject.toml"
CONSTRAINTS = ROOT / ".github" / "constraints-py311.txt"
COMPILED_EXTRAS = ("dev", "web")   # extras passés à `uv pip compile` (en-tête du fichier figé) et à l'installation de la suite lente


def _pins() -> dict[str, str]:
    pins = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[canonicalize_name(name.split("[", 1)[0])] = version.split(";", 1)[0].strip()
    return pins


def _compiled_requirements() -> list[Requirement]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    raw = list(project["dependencies"])
    for extra in COMPILED_EXTRAS:
        raw += project["optional-dependencies"][extra]
    return [Requirement(r) for r in raw]


REQUIREMENTS = _compiled_requirements()


def test_the_files_are_read():
    assert len(REQUIREMENTS) > 20
    assert len(_pins()) > 100


@pytest.mark.parametrize("req", REQUIREMENTS, ids=lambda r: r.name)
def test_a_dependency_is_pinned_at_a_version_its_specifier_accepts(req):
    pinned = _pins().get(canonicalize_name(req.name))
    assert pinned is not None, (
        f"{req.name} n'est pas dans {CONSTRAINTS.name} : régénérer le fichier figé (commande dans son en-tête)")
    assert req.specifier.contains(pinned, prereleases=True), (
        f"{req} refuse la version figée {req.name}=={pinned} : la suite lente ne pourra pas s'installer. "
        f"Garder le plancher à {pinned}, ou régénérer {CONSTRAINTS.name} avec `--upgrade-package {req.name}` dans la même PR")
