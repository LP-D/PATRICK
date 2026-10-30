"""Shared pytest fixtures/helpers across `patrick/tests/`."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.tracking import db as trackdb


def shutdown_loky_workers() -> None:
    """Ferme le pool de processus loky que joblib garde ouvert entre deux `Parallel` (s'il existe). Sans cela, les
    workers d'un test survivent à la session -- et à un pytest interrompu -- et fatiguent la suite suivante."""
    try:
        from joblib.externals.loky import reusable_executor
    except ImportError:
        return
    executor = getattr(reusable_executor, "_executor", None)
    if executor is not None:
        executor.shutdown(wait=True, kill_workers=True)


def pytest_sessionfinish(session, exitstatus):
    shutdown_loky_workers()

# Relative, not absolute: `data/ingest.py` requires >= 20 years of history
# (`min_history = today - 20*365.25 days`). An absolute date drifts under
# that threshold as real time passes -- 30 years back keeps a decade of
# margin regardless of when the suite runs. Shared here (was duplicated in
# `test_data_quality.py` and `test_audit_degradation.py`, both hitting the
# same drift once their absolute `2015-01-01`/`2018-01-01` fixtures aged
# past the 20-year threshold -- see KNOWN_ISSUES.md).
OLD_ENOUGH_START = (pd.Timestamp.today() - pd.Timedelta(days=30 * 365.25)).strftime("%Y-%m-%d")


@pytest.fixture
def conn(tmp_path):
    """SQLite connection on a fresh, isolated `patrick.db` under `tmp_path`
    (was duplicated identically in `test_selection_cache.py` and
    `test_vol_model_cache.py`)."""
    return trackdb.connect(str(tmp_path / "patrick.db"))


@pytest.fixture(autouse=True)
def _isolated_feature_pool_cache(tmp_path, monkeypatch):
    """The on-disk feature pool cache (`patrick/features/pool_cache.py`) is
    per test: two tests building the same synthetic pool must never serve
    each other a cached frame (a call-counting test would then see zero
    calls)."""
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(tmp_path / "feature_cache"))


@pytest.fixture(autouse=True)
def _isolated_local_cache(tmp_path, monkeypatch):
    """The local download cache (`patrick/cache_manager.py`, `~/.patrick/cache`) is per test: `ingest()` and the
    downloaders write there, so a test's synthetic frame for a REAL symbol (e.g. `MC.PA`) would otherwise sit in the
    user's cache and be served to a real run for the next 30 days."""
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "local_cache"))


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path_factory, monkeypatch):
    """The data root (`patrick/paths.py`: store, models, backups, archive, reports) is per test: nothing a test writes may
    land in the machine's real data folder. A test that wants an unconfigured PC removes `PATRICK_DATA_ROOT`. Created next
    to `tmp_path`, not inside it: some tests inspect `tmp_path` as an empty folder."""
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path_factory.mktemp("data_root")))


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path_factory, monkeypatch):
    """La base active (`paths.db_path()` : `~/.patrick/patrick.db`, 13 Go sur le poste de Léon) est par test. Un test de page qui n'avait pas posé
    `PATRICK_DB_PATH` ouvrait la VRAIE base : ~12 s par rendu mesurés le 30/10 (une demi-douzaine de tests de pages, soit plus d'une minute de la
    suite), et rien n'empêchait un test d'y écrire. Un test qui pose son propre chemin le remplace ; créée à côté de `tmp_path`, pas dedans."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path_factory.mktemp("db") / "patrick.db"))


@pytest.fixture(autouse=True)
def _isolated_machine_settings(tmp_path, monkeypatch):
    """Machine settings and shell-level worker overrides must not affect tests.

    Overrides can send work to subprocesses, which call-counting tests in the
    current process cannot observe.
    """
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.delenv("PATRICK_PARAMETRIC_JOBS", raising=False)
    monkeypatch.delenv("PATRICK_SCAN_JOBS", raising=False)
    # La reprise automatique (`run_manager.recover_interrupted_runs`, appelée par `/api/run-state`) relance un worker quand la file n'est pas
    # vide : un test qui lit l'état d'une file ne doit pas faire démarrer un vrai processus. Les tests de la reprise retirent cette variable.
    monkeypatch.setenv("PATRICK_NO_AUTO_WORKER", "1")
    monkeypatch.setenv("PATRICK_INSTRUMENT_LOOKUP", "0")             # un affichage n'apprend jamais un nom par le réseau (webapp/instruments.py)


class FakeScheduledTask:
    """Remplace la tâche Windows `PATRICK-Sync` : un test ne doit JAMAIS créer ni supprimer la vraie tâche de la machine."""

    def __init__(self) -> None:
        self.registered = False
        self.calls: list[str] = []

    def register(self, minutes: int = 60) -> str:
        self.registered = True
        self.calls.append("register")
        return "commande factice"

    def unregister(self) -> bool:
        was, self.registered = self.registered, False
        self.calls.append("unregister")
        return was

    def status(self) -> dict:
        return {"supported": True, "registered": self.registered, "next_run": None}


@pytest.fixture(autouse=True)
def _testclient_host(monkeypatch):
    """Le `TestClient` de Starlette envoie `Host: testserver` : on l'autorise comme hôte local (comme le ferait un
    reverse proxy déclaré dans PATRICK_EXTRA_HOSTS). Les tests de la garde le retirent pour vérifier le refus."""
    monkeypatch.setenv("PATRICK_EXTRA_HOSTS", "testserver")


@pytest.fixture(autouse=True)
def fake_task(monkeypatch):
    from patrick import sync

    fake = FakeScheduledTask()
    monkeypatch.setattr(sync, "register_task", fake.register)
    monkeypatch.setattr(sync, "unregister_task", fake.unregister)
    monkeypatch.setattr(sync, "task_status", fake.status)
    return fake
