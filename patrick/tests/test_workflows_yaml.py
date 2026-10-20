"""Les workflows GitHub Actions doivent être du YAML valide avec un déclencheur et des jobs.

Un fichier invalide ne fait rien d'évident : GitHub l'exécute comme un « échec » sans aucun job (nom de l'exécution = chemin du
fichier). Constaté le 2026-10-20 sur `mutation.yml` (« : » dans une valeur non guillemetée). Ce test l'attrape avant le push.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))


def test_the_workflows_are_found():
    assert {p.name for p in WORKFLOWS} >= {"tests.yml", "golden-regen.yml", "validity.yml", "mutation.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_workflow_is_valid_yaml_with_a_trigger_and_jobs(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} n'est pas un dictionnaire YAML"
    assert True in data or "on" in data, f"{path.name} n'a pas de déclencheur (« on »)"   # YAML 1.1 lit `on` comme True
    jobs = data.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path.name} n'a pas de jobs"
    for name, job in jobs.items():
        assert "runs-on" in job and job.get("steps"), f"{path.name} : le job « {name} » n'a pas de runs-on ou d'étapes"
