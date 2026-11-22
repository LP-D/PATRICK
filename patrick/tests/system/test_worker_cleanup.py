"""La suite ne laisse pas de workers loky derrière elle (audit externe du 2026-10-19, point 20).

Après un `Parallel(n_jobs>1)`, joblib garde un pool de processus ouvert pour le réutiliser ; sur un poste (ou un
runner) où la suite est interrompue ou enchaînée, ces processus survivent et fatiguent les tests suivants (voir
`KNOWN_ISSUES.md`). `conftest.shutdown_loky_workers` les ferme en fin de session.
"""
from __future__ import annotations

import os

import psutil
from conftest import shutdown_loky_workers
from joblib import Parallel, delayed


def _loky_workers() -> list[psutil.Process]:
    out = []
    for child in psutil.Process(os.getpid()).children(recursive=True):
        try:
            if "popen_loky" in " ".join(child.cmdline()):
                out.append(child)
        except psutil.Error:
            continue
    return out


def test_shutdown_closes_the_reusable_loky_pool():
    assert Parallel(n_jobs=2, backend="loky")(delayed(abs)(-i) for i in range(4)) == [0, 1, 2, 3]
    assert _loky_workers(), "prérequis : un pool loky doit exister"
    shutdown_loky_workers()
    _gone, alive = psutil.wait_procs(_loky_workers(), timeout=10)
    assert alive == []
    # sans pool ouvert : sans effet, sans erreur
    shutdown_loky_workers()
