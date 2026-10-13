"""Actualisation live quotidienne : l'app laissée ouverte doit prédire et juger chaque jour, pas seulement au lancement."""
from __future__ import annotations

from datetime import date

import pytest

from patrick import live_refresh


def test_refresh_is_due_at_launch_then_once_per_new_day():
    today = date(2026, 10, 13)
    assert live_refresh.refresh_due(None, today)                       # premier lancement
    assert not live_refresh.refresh_due(today, today)                  # déjà fait aujourd'hui
    assert live_refresh.refresh_due(date(2026, 10, 12), today)         # le jour a changé
    assert not live_refresh.refresh_due(date(2026, 10, 14), today)     # horloge qui recule : on ne refait rien


def test_loop_refreshes_once_per_day_and_survives_a_failed_refresh(monkeypatch):
    days = iter([date(2026, 10, 13), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)])
    calls: list[str | None] = []

    def fake_refresh(db_path=None):
        calls.append(db_path)
        if len(calls) == 2:
            raise RuntimeError("réseau coupé")   # un échec n'arrête pas la boucle

    waits = []
    monkeypatch.setattr(live_refresh, "utc_today", lambda: next(days))
    monkeypatch.setattr(live_refresh, "_refresh_once", fake_refresh)
    monkeypatch.setattr(live_refresh._stop, "wait", lambda timeout: waits.append(timeout) or len(waits) >= 4)

    live_refresh._refresh_loop("x.db")

    assert calls == ["x.db", "x.db", "x.db"]       # 13 (lancement), 14, 15 -- pas de doublon le 13
    assert waits == [live_refresh.REFRESH_CHECK_SECONDS] * 4
    assert live_refresh.refresh_status()["running"] is False


def test_progress_counts_the_signals_judged_and_the_ones_with_the_right_direction(monkeypatch, tmp_path):
    from patrick.tracking import db

    db_path = str(tmp_path / "p.db")
    db.connect(db_path).close()
    cand = live_refresh.PredictCandidate("^VIX", 5, "r1", 1, "a.joblib")
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: [cand, cand])
    details = iter([{"n_outcomes_updated": 3, "n_outcomes_right": 2}, {"n_outcomes_updated": 1, "n_outcomes_right": 0}])
    monkeypatch.setattr(live_refresh, "run_daily_predictions",
                        lambda candidates, db_path=None, on_item=None: [
                            on_item(live_refresh.PredictOutcome(c, True, detail=next(details))) for c in candidates])

    live_refresh._refresh_once(db_path)

    status = live_refresh.refresh_status()
    assert (status["done"], status["judged"], status["judged_right"]) == (2, 4, 2)


def test_page_says_what_the_latest_refresh_judged_and_how_many_were_right(tmp_path, monkeypatch):
    from page_support import FullPageClient as TestClient

    from patrick.tracking import db
    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    db.connect(str(tmp_path / "p.db")).close()
    live_refresh._state.update(running=False, total=5, done=5, failed=0, judged=4, judged_right=3,
                               finished_at="2026-10-13T08:00:00+00:00")
    assert "4 signal(aux) arrivé(s) à échéance, 3 dans le bon sens (75 %)" in TestClient(app).get("/predictions").text

    live_refresh._state.update(judged=0, judged_right=0)
    assert "Dernière évaluation : aucun signal" in TestClient(app).get("/predictions").text   # l'apostrophe est échappée en HTML


@pytest.fixture(autouse=True)
def _reset_state():
    snapshot = dict(live_refresh._state)
    yield
    live_refresh._state.clear()
    live_refresh._state.update(snapshot)
