"""Disque plein pendant le passage de nuit (15/11/2026).

Le 15/11/2026, la tâche `Patrick-Nightly` a tourné avec D: pleine : 2 984 prédictions tentées, 2 985 échecs « [Errno 28] No space left on
device », une traceback par cible, aucune alerte. Le cache de variables avait atteint 315 Go pour un plafond de 150 Go : son éviction n'était
appelée qu'à la fin d'un entraînement. Ici, trois garanties :

1. avant la première prédiction puis toutes les N, l'espace libre du disque de la racine de données est mesuré ; sous le seuil, le cache de
   variables est évincé d'abord (jamais la base), puis, si cela ne suffit pas, la boucle s'arrête avec UN message clair ;
2. une erreur « disque plein » sur une prédiction arrête la boucle : toutes les suivantes échoueraient aussi ;
3. `daily_predict.py` ramène le cache de variables sous son plafond une fois par exécution.
"""
from __future__ import annotations

import errno
import importlib.util
import logging
import os
import sys
from pathlib import Path

import pytest

from patrick.core import paths, settings
from patrick.live import refresh as live_refresh
from patrick.live.refresh import PredictCandidate
from patrick.storage import cache_eviction
from patrick.tracking import db as trackdb

GB = 10**9
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "daily_predict.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("daily_predict_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


daily_predict = _load_script()


def _candidates(n: int) -> list[PredictCandidate]:
    return [PredictCandidate(target=f"T{i}", horizon=1, run_id=f"run_{i}", trial_id=i, artifact_path="x.joblib") for i in range(n)]


def _ok(run_id, db_path=None):
    return {"run_id": run_id, "y_pred": 1, "y_proba": 0.6, "n_outcomes_updated": 0}


def _errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# --- 2. Une erreur « disque plein » arrête la boucle ---------------------------------------------------------------------------

def _chained():
    try:
        raise OSError(errno.ENOSPC, "No space left on device")
    except OSError as cause:
        wrapped = RuntimeError("écriture du cache impossible")
        wrapped.__cause__ = cause
        return wrapped


@pytest.mark.parametrize("error", [
    OSError(errno.ENOSPC, "No space left on device"),
    _chained(),                                                                 # l'OSError est la cause d'une autre exception
    RuntimeError("[Errno 28] No space left on device"),                         # seul le texte survit (erreur re-levée par une bibliothèque)
], ids=["oserror", "chained", "text-only"])
def test_a_disk_full_error_stops_the_loop_after_the_first_failure(error, caplog):
    calls = []

    def predict(run_id, db_path=None):
        calls.append(run_id)
        raise error

    with caplog.at_level(logging.INFO, logger="patrick.live.refresh"):
        summary = live_refresh.run_daily_predictions(_candidates(5), predict_live_fn=predict)

    assert calls == ["run_0"]                                                   # pas 5 tentatives, ni 2 984
    assert len(summary.failures) == 1 and summary.aborted
    assert "disque" in summary.aborted.lower() and "4" in summary.aborted       # dit combien de prédictions n'ont pas été tentées
    errors = _errors(caplog)
    assert len(errors) == 1 and errors[0].exc_info is None                      # UN message, pas une traceback par cible


def test_another_os_error_does_not_stop_the_loop():
    calls = []

    def predict(run_id, db_path=None):
        calls.append(run_id)
        raise PermissionError(errno.EACCES, "Permission denied")

    summary = live_refresh.run_daily_predictions(_candidates(3), predict_live_fn=predict)

    assert calls == ["run_0", "run_1", "run_2"] and summary.aborted is None


def test_a_disk_full_error_is_not_noted_as_a_model_failure(tmp_path):
    """`live_failure` alimente le conseiller de relance (« entrées perdues ») : le disque n'est pas la faute du modèle."""
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()

    def predict(run_id, db_path=None):
        raise OSError(errno.ENOSPC, "No space left on device")

    live_refresh.run_daily_predictions(_candidates(2), predict_live_fn=predict, db_path=db_path, track_failures=True)

    conn = trackdb.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM live_failure").fetchone()[0] == 0
    finally:
        conn.close()


# --- 1. Espace libre mesuré avant et pendant la boucle -------------------------------------------------------------------------

def test_the_free_space_is_measured_on_the_data_root(monkeypatch):
    seen = []
    monkeypatch.setattr(live_refresh.shutil, "disk_usage", lambda p: seen.append(Path(p)) or type("U", (), {"free": 7 * GB})())

    assert live_refresh.data_root_free_bytes() == 7 * GB
    assert seen == [paths.data_root()]


def test_the_default_threshold_is_5_gb_and_is_a_setting():
    assert live_refresh.min_free_bytes() == 5 * GB
    settings.save({live_refresh.KEY_MIN_FREE_GB: 20})
    assert live_refresh.min_free_bytes() == 20 * GB
    settings.save({live_refresh.KEY_MIN_FREE_GB: "n'importe quoi"})
    assert live_refresh.min_free_bytes() == 5 * GB                              # un réglage illisible ne désactive pas le garde-fou


def test_it_checks_before_the_first_prediction(monkeypatch, caplog):
    monkeypatch.setattr(cache_eviction, "evict_feature_cache", lambda *a, **k: {"removed_files": 0, "removed_bytes": 0})
    calls = []

    with caplog.at_level(logging.INFO, logger="patrick.live.refresh"):
        summary = live_refresh.run_daily_predictions(
            _candidates(3), predict_live_fn=lambda r, db_path=None: calls.append(r) or _ok(r), free_bytes_fn=lambda: 1 * GB)

    assert calls == [] and summary.outcomes == [] and summary.aborted             # rien n'est tenté sur un disque déjà plein


def test_it_evicts_the_feature_cache_first_and_carries_on_if_that_frees_enough(monkeypatch):
    free = {"value": 1 * GB}
    evictions = []

    def evict(*args, **kwargs):
        evictions.append((args, kwargs))
        free["value"] = 80 * GB                                                 # l'éviction a libéré de la place
        return {"removed_files": 40, "removed_bytes": 79 * GB}
    monkeypatch.setattr(cache_eviction, "evict_feature_cache", evict)
    calls = []

    summary = live_refresh.run_daily_predictions(
        _candidates(3), predict_live_fn=lambda r, db_path=None: calls.append(r) or _ok(r), free_bytes_fn=lambda: free["value"])

    assert len(evictions) == 1 and calls == ["run_0", "run_1", "run_2"] and summary.aborted is None


def test_it_stops_with_one_clear_message_when_eviction_is_not_enough(monkeypatch, caplog):
    monkeypatch.setattr(cache_eviction, "evict_feature_cache", lambda *a, **k: {"removed_files": 3, "removed_bytes": 2 * GB})
    calls = []

    with caplog.at_level(logging.INFO, logger="patrick.live.refresh"):
        summary = live_refresh.run_daily_predictions(
            _candidates(3), predict_live_fn=lambda r, db_path=None: calls.append(r) or _ok(r), free_bytes_fn=lambda: int(1.5 * GB))

    assert calls == [] and summary.aborted
    errors = _errors(caplog)
    assert len(errors) == 1 and errors[0].exc_info is None
    message = errors[0].getMessage()
    assert "1,5 Go" in message and "5,0 Go" in message and "3 fichiers" in message          # libre, seuil, ce que l'éviction a retiré
    assert str(paths.data_root()) in message                                              # où libérer de la place


def test_it_checks_again_every_n_predictions():
    free = {"value": 100 * GB}
    calls, measures = [], []

    def predict(run_id, db_path=None):
        calls.append(run_id)
        if len(calls) == 3:
            free["value"] = 1 * GB                                              # le disque se remplit pendant la nuit
        return _ok(run_id)

    def measure():
        measures.append(len(calls))
        return free["value"]

    summary = live_refresh.run_daily_predictions(_candidates(10), predict_live_fn=predict, free_bytes_fn=measure, check_every=3)

    assert measures == [0, 3, 3]                                                # avant la 1re, avant la 4e (3 déjà faites), puis après l'éviction
    assert len(calls) == 3 and summary.aborted and len(summary.successes) == 3


def test_a_measure_that_fails_never_blocks_the_predictions():
    """Racine de données absente, lecteur qui redémarre : la mesure peut échouer ; les prédictions, elles, diront leur propre erreur."""
    def broken():
        raise OSError("lecteur indisponible")

    calls = []
    summary = live_refresh.run_daily_predictions(
        _candidates(2), predict_live_fn=lambda r, db_path=None: calls.append(r) or _ok(r), free_bytes_fn=broken)

    assert calls == ["run_0", "run_1"] and summary.aborted is None


def test_the_guard_is_only_on_for_real_predictions_or_when_asked(monkeypatch):
    """Comme `track_failures` : un `predict_live_fn` injecté (tests) ne mesure jamais le vrai disque, sauf `free_bytes_fn` explicite."""
    monkeypatch.setattr(live_refresh, "data_root_free_bytes", lambda: pytest.fail("le disque réel ne doit pas être mesuré"))

    summary = live_refresh.run_daily_predictions(_candidates(2), predict_live_fn=_ok)

    assert summary.aborted is None and len(summary.successes) == 2


def test_the_eviction_touches_only_the_feature_cache_and_really_frees_space(tmp_path, monkeypatch):
    """Intégration avec la vraie éviction : plafond du réglage, vieux fichiers retirés, la base (caches de volatilité) jamais touchée."""
    cache = paths.feature_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    old = []
    for i in range(3):
        f = cache / f"pool_{i}.parquet"
        f.write_bytes(b"x" * 1000)
        os.utime(f, (1_000_000, 1_000_000))                                     # vieux : plus d'une heure sans lecture
        old.append(f)
    settings.save({cache_eviction.KEY_FEATURE_CACHE_MAX_GB: 0})                 # plafond nul : tout ce qui est évinçable part
    for name in ("evict_vol_cache", "prune_db_caches", "recompress_vol_cache"):
        monkeypatch.setattr(cache_eviction, name, lambda *a, **k: pytest.fail("la base ne se modifie pas pendant qu'un worker vit"))
    calls = []

    summary = live_refresh.run_daily_predictions(
        _candidates(2), predict_live_fn=lambda r, db_path=None: calls.append(r) or _ok(r),
        free_bytes_fn=lambda: 1 * GB if any(f.exists() for f in old) else 50 * GB)

    assert calls == ["run_0", "run_1"] and summary.aborted is None
    assert not any(f.exists() for f in old)                                     # évincés par la vraie fonction, au plafond du réglage


def test_trim_feature_cache_never_raises(monkeypatch):
    def boom(*a, **k):
        raise paths.DataRootUnavailable("D: absent")
    monkeypatch.setattr(cache_eviction, "evict_feature_cache", boom)

    assert live_refresh.trim_feature_cache() is None


# --- 3. Une éviction par exécution de `daily_predict.py`, et le code de sortie du disque plein -------------------------------

def _wire(tmp_path, monkeypatch, *, summary=None):
    mod = daily_predict
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    needed, other = mod.PredictCandidate("AAA", 1, "run_a", 1, "a.joblib"), mod.PredictCandidate("BBB", 5, "run_b", 2, "b.joblib")
    events: list = []
    monkeypatch.setattr(mod, "find_predictable_candidates", lambda conn: [other, needed])
    monkeypatch.setattr(mod, "split_for_funds", lambda candidates, db_path=None: ([needed], [other]))

    def fake_predictions(candidates, db_path=None, on_item=None):
        events.append(("predictions", [c.target for c in candidates]))
        return summary if summary is not None else mod.RunSummary()
    monkeypatch.setattr(mod, "run_daily_predictions", fake_predictions)
    monkeypatch.setattr(mod, "run_autopilots", lambda path=None: events.append("autopilot") or [])
    monkeypatch.setattr(mod, "remeasure_stale_drift", lambda *a, **k: events.append("drift") or {
        "measured": 0, "failed": 0, "skipped_fresh": 0, "deferred": 0})
    monkeypatch.setattr(mod, "refresh_pooled_signal", lambda path=None: events.append("pooled"))
    monkeypatch.setattr(mod, "write_weekly_report", lambda path=None: events.append("report"))
    monkeypatch.setattr(mod, "trim_feature_cache", lambda: events.append("trim"))
    return mod, db_path, events


def test_main_trims_the_feature_cache_once_after_everything_else(tmp_path, monkeypatch):
    mod, db_path, events = _wire(tmp_path, monkeypatch)

    assert mod.main(["--db-path", db_path]) == 0

    assert events == [("predictions", ["AAA"]), "autopilot", ("predictions", ["BBB"]), "drift", "pooled", "report", "trim"]


def test_funds_only_also_trims_the_cache(tmp_path, monkeypatch):
    mod, db_path, events = _wire(tmp_path, monkeypatch)

    assert mod.main(["--db-path", db_path, "--funds-only"]) == 0

    assert events == [("predictions", ["AAA"]), "autopilot", "trim"]


def test_dry_run_trims_nothing(tmp_path, monkeypatch):
    mod, db_path, events = _wire(tmp_path, monkeypatch)

    assert mod.main(["--db-path", db_path, "--dry-run"]) == 0

    assert events == []


def test_main_returns_the_disk_full_code_and_skips_what_follows(tmp_path, monkeypatch):
    """Disque plein : ni cycle du pilote automatique (il lirait des signaux périmés), ni second lot, ni dérive ; mais l'éviction est tentée."""
    mod = daily_predict
    stopped = mod.RunSummary(aborted="Disque presque plein : 1,0 Go libres sur D:\\PATRICK DATA.")
    mod, db_path, events = _wire(tmp_path, monkeypatch, summary=stopped)

    code = mod.main(["--db-path", db_path])

    assert code == mod.EXIT_DISK_FULL != 0
    assert events == [("predictions", ["AAA"]), "trim"]


def test_main_stops_before_the_second_batch_if_the_second_batch_fills_the_disk(tmp_path, monkeypatch):
    mod, db_path, events = _wire(tmp_path, monkeypatch)
    batches = iter([mod.RunSummary(), mod.RunSummary(aborted="Disque presque plein")])
    monkeypatch.setattr(mod, "run_daily_predictions", lambda candidates, db_path=None, on_item=None: (
        events.append(("predictions", [c.target for c in candidates])), next(batches))[1])

    code = mod.main(["--db-path", db_path])

    assert code == mod.EXIT_DISK_FULL
    assert events == [("predictions", ["AAA"]), "autopilot", ("predictions", ["BBB"]), "trim"]          # ni dérive, ni rapport
