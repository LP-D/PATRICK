"""Valeur de référence d'un signal live : la clôture de sa séance, ou un cours en séance (barre du jour encore partielle).
Mémorisée à l'instant du signal (migration 0032) et dite dans la bulle de /predictions avec le marché concerné."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from page_support import FullPageClient as TestClient

from patrick.data import session_calendar as sc
from patrick.tracking import db
from patrick.tracking import history as trackhistory
from patrick.webapp.app import _market_view, app


def _utc(day: str, hour: int, minute: int = 0) -> datetime:
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize("asset_class, now, final", [
    ("equities_us", _utc("2026-10-13", 19, 59), False),     # séance US en cours : la barre du jour est un cours en séance
    ("equities_us", _utc("2026-10-13", 20, 0), True),       # clôture passée : la barre est la clôture
    ("equities_europe", _utc("2026-10-13", 17, 0), True),
    ("equities_asia_pacific", _utc("2026-10-13", 9, 0), True),
    ("crypto", _utc("2026-10-13", 23, 59), False),           # journée UTC pas finie
    ("crypto", _utc("2026-10-14", 0, 0), True),
    ("equities_us", _utc("2026-10-14", 8, 0), True),         # séance de la veille
])
def test_bar_is_final_once_the_session_close_has_passed(asset_class, now, final):
    assert sc.bar_is_final(asset_class, date(2026, 10, 13), now) is final


def test_the_reference_of_a_signal_is_stored_when_it_is_written(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "s", "h", None, None, None)
    db.create_run(conn, "r", "^GSPC", 1, "s", "{}", "c", "g", 1)
    tid = db.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 5, "shap")
    db.mark_best_trial(conn, tid)
    db.finish_run(conn, "r", "done", n_trials=1)
    for ts, final, price in (("2026-10-12", True, 7807.24), ("2026-10-13", False, 7798.46), ("2026-10-09", None, None)):
        db.add_predictions(conn, tid, 0, "live", [ts], [None], [3])
        db.set_live_signal_context(conn, tid, ts, -0.01, 0.01, backfill=False, bar_final=final, ref_price=price)

    stored = {r[0]: r[1:] for r in conn.execute(
        "SELECT ts, live_bar_final, live_ref_price FROM prediction WHERE split = 'live'").fetchall()}
    assert stored == {"2026-10-12": (1, 7807.24), "2026-10-13": (0, 7798.46), "2026-10-09": (None, None)}
    latest = trackhistory.latest_predictions_by_target_and_horizon(conn, ["^GSPC"], [1])[("^GSPC", 1)]
    assert latest["ts"] == "2026-10-13" and latest["bar_final"] is False and latest["ref_price"] == 7798.46


def test_market_view_says_the_market_and_whether_it_is_open():
    running = _market_view("equities_us", date(2026, 10, 13), _utc("2026-10-13", 15), False)
    assert running["open_now"] is True and running["bar_final"] is False       # mardi 15 h UTC : New York est ouvert
    over = _market_view("equities_europe", date(2026, 10, 12), _utc("2026-10-13", 17), True)
    assert over["open_now"] is False and over["bar_final"] is True             # Paris a fermé à 15:30 UTC
    crypto = _market_view("crypto", date(2026, 10, 13), _utc("2026-10-13", 15), None)
    assert crypto["open_now"] is True and crypto["bar_final"] is None          # 24 h/24


def test_market_view_gives_the_starting_price_and_the_session_where_the_move_ends():
    friday = date(2026, 10, 9)
    us = _market_view("equities_us", friday, _utc("2026-10-10", 9), True, 7811.54003906, 1)
    assert us["price"] == "7811.54" and us["target"] == "2026-10-12"          # le week-end est sauté : lundi
    assert _market_view("equities_us", friday, _utc("2026-10-10", 9), True, 0.0123456789, 5)["target"] == "2026-10-16"
    assert _market_view("crypto", friday, _utc("2026-10-10", 9), True, 64000.0, 2)["target"] == "2026-10-11"  # 24 h/24
    assert _market_view("equities_us", friday, _utc("2026-10-10", 9), True)["price"] is None                # non enregistré


def _seed_signal(tmp_path, monkeypatch, bar_final, ref_price=None):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2024-06-01T00:00:00"],
                       y_true=[None], y_pred=[3], y_proba=[0.71])
    db.set_live_signal_context(conn, trial_id, "2024-06-01T00:00:00", None, None, backfill=False, bar_final=bar_final,
                               ref_price=ref_price)
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()


@pytest.mark.parametrize("bar_final, expected", [
    (True, "clôture du 2024-06-01"),
    (False, "cours en séance du 2024-06-01, pas la clôture"),
    (None, "non enregistrée (signal antérieur)"),
])
def test_page_says_which_value_the_predicted_move_starts_from(tmp_path, monkeypatch, bar_final, expected):
    _seed_signal(tmp_path, monkeypatch, bar_final)
    html = TestClient(app).get("/predictions").text

    assert "Volatilité US" in html and ("Ouvert" in html or "Fermé" in html)       # ^VIX : le marché et son état
    assert expected in html
    # 2024-06-01 est un samedi : 5 séances plus tard = vendredi 2024-06-07
    assert "Mouvement prédit : de cette valeur à la clôture du ≈ 2024-06-07 (5 séance(s) plus tard)." in html
    assert ("Le signal sera jugé par rapport à la clôture." in html) is (bar_final is False)
    assert "Confiance : probabilité que le modèle donne à ce mouvement" in html     # ce qu'est l'indice de confiance
    assert ("Cours de départ non enregistré." in html) is (bar_final is not None)    # connue sans cours : on le dit


def test_page_shows_the_starting_price_with_its_date(tmp_path, monkeypatch):
    _seed_signal(tmp_path, monkeypatch, False, ref_price=31.5234)
    html = TestClient(app).get("/predictions").text

    assert "<strong>31.5234</strong> ·" in html and "cours en séance du 2024-06-01, pas la clôture" in html
    assert "Cours de départ non enregistré." not in html
