"""Configuration YAML lue en UTF-8 quel que soit l'encodage par défaut de Windows (CO9 du 25/11)."""
from __future__ import annotations

from patrick.config.schema import RunConfig


def _yaml(name: str) -> str:
    return f"name: {name}\nobjective:\n  target_symbol: ^GSPC\n"


def test_an_accented_utf8_yaml_keeps_its_accents(tmp_path):
    p = tmp_path / "run.yaml"
    p.write_text(_yaml("Méthode été"), encoding="utf-8")
    assert RunConfig.from_yaml(str(p)).name == "Méthode été"


def test_an_old_cp1252_yaml_is_still_readable(tmp_path):
    p = tmp_path / "run.yaml"
    p.write_bytes(_yaml("Méthode").encode("cp1252"))
    assert RunConfig.from_yaml(str(p)).name == "Méthode"
