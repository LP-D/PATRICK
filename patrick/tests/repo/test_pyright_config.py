"""Le cliquet de types (B22, `patrick/pyrightconfig.json`) ne liste que des fichiers qui existent : un fichier renommé ou supprimé
sortirait silencieusement de la vérification."""
from __future__ import annotations

import json
from pathlib import Path

PATRICK = Path(__file__).resolve().parents[2]


def _config() -> dict:
    text = (PATRICK / "pyrightconfig.json").read_text(encoding="utf-8")
    return json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))


def test_every_listed_file_exists_and_the_mode_is_standard():
    cfg = _config()
    missing = [f for f in cfg["include"] if not (PATRICK / f).is_file()]
    assert missing == []
    assert cfg["typeCheckingMode"] == "standard" and len(cfg["include"]) >= 200
    assert len(set(cfg["include"])) == len(cfg["include"])
