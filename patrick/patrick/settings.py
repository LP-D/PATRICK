"""Réglages globaux de la machine (pas d'un run) : `~/.patrick/settings.json`
(`PATRICK_SETTINGS_PATH` pour l'isoler). Relu à CHAQUE appel : un worker déjà
lancé prend en compte un changement fait depuis l'interface sans redémarrage.

Volontairement hors `RunConfig` : ces réglages ne changent pas le résultat d'un
run (optimisations exactes), donc ni le `config_hash` ni l'identité des runs.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

KEY_PARAMETRIC_JOBS = "parametric_jobs"
KEY_SCAN_JOBS = "scan_jobs"


def settings_path() -> Path:
    return Path(os.environ.get("PATRICK_SETTINGS_PATH") or Path.home() / ".patrick" / "settings.json")


def load() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(updates: dict) -> dict:
    """Fusionne `updates` dans le fichier (écriture atomique)."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**load(), **updates}
    fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return data


def get_parametric_jobs() -> int:
    """Nombre de workers du pool paramétrique réglé depuis l'interface (1 = séquentiel)."""
    try:
        return max(1, int(load().get(KEY_PARAMETRIC_JOBS, 1)))
    except (TypeError, ValueError):
        return 1


def get_scan_jobs() -> int:
    """Workers de calcul des modèles (sélection SHAP + fits du scan) réglés depuis l'interface (1 = séquentiel)."""
    try:
        return max(1, int(load().get(KEY_SCAN_JOBS, 1)))
    except (TypeError, ValueError):
        return 1
