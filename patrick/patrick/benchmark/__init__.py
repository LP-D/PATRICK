"""Sprint 1 -- mesure et non-régression (aucune optimisation ici).

Instrumentation EXTERNE de `run_pipeline` (monkeypatch temporaire, restauré à
la sortie : `engine.py` n'est pas modifié), dataset synthétique reproductible,
capture des artefacts de non-régression, rapports `benchmark_reference.{json,md}`.

    python -m patrick.benchmark run                  # benchmark de référence
    python -m patrick.benchmark compare <dir_a> <dir_b>
"""
