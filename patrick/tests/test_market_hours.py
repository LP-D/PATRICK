"""Marché ouvert (vert) ou fermé (rouge) dans la bulle de /predictions : horaires par classe d'actifs en heure locale de la place
(heure d'été comprise), week-ends, et jours fériés détectés par l'absence de barre du jour. Plus la dernière valeur de l'actif."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from page_support import FullPageClient as TestClient

from patrick import predict as predict_module
from patrick.data import session_calendar as sc
from patrick.tracking import db
from patrick.webapp.app import _market_view, app


def utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC)


@pytest.mark.parametrize("asset_class, now, expected", [
    ("equities_us", "2026-10-14T15:00", True),         # mercredi, séance de New York en cours (EDT : 13:30-20:00 UTC)
    ("equities_us", "2026-10-14T13:00", False),        # avant l'ouverture
    ("equities_us", "2026-10-14T21:00", False),        # après la clôture
    ("equities_us", "2026-10-17T15:00", False),        # samedi
    ("equities_us", "2026-12-09T14:15", False),        # hiver (EST) : l'ouverture glisse à 14:30 UTC
    ("equities_us", "2026-12-09T14:45", True),
    ("equities_europe", "2026-10-14T08:00", True),     # Paris en heure d'été : 07:00-15:30 UTC
    ("equities_europe", "2026-10-14T16:00", False),
    ("equities_europe", "2026-10-18T10:00", False),    # dimanche
    ("equities_asia_pacific", "2026-10-14T03:00", True),
    ("equities_asia_pacific", "2026-10-14T12:00", False),
    ("volatility_index", "2026-10-14T20:10", True),    # le VIX cote jusqu'à 16:15 New York
    ("crypto", "2026-10-17T03:00", True),              # 24 h/24, week-end compris
    ("fx", "2026-10-16T20:00", True),                  # vendredi avant 17 h New York
    ("fx", "2026-10-16T22:30", False),
    ("fx", "2026-10-17T12:00", False),                 # samedi
    ("futures", "2026-10-17T12:00", False),
    ("futures", "2026-10-18T22:30", True),             # réouverture du dimanche soir
    ("futures", "2026-10-14T21:30", False),            # pause quotidienne 17 h - 18 h New York
    ("macro", "2026-10-14T12:00", None),               # série FRED : pas de séance
    ("other", "2026-10-14T12:00", None),
])
def test_market_is_open_follows_each_class_local_hours(asset_class, now, expected):
    assert sc.market_is_open(asset_class, utc(now)) is expected


def test_a_public_holiday_is_detected_when_no_bar_of_the_day_exists_after_the_open():
    wednesday_afternoon = utc("2026-10-14T16:00")
    refreshed_after_open = utc("2026-10-14T15:30")
    assert sc.market_open_now("equities_us", wednesday_afternoon, date(2026, 10, 14), refreshed_after_open) is True
    assert sc.market_open_now("equities_us", wednesday_afternoon, date(2026, 10, 13), refreshed_after_open) is False   # férié
    # actualisation faite avant l'ouverture : on ne peut rien conclure, l'horaire fait foi
    assert sc.market_open_now("equities_us", wednesday_afternoon, date(2026, 10, 13), utc("2026-10-14T12:00")) is True
    # le week-end reste fermé, barre ou pas
    assert sc.market_open_now("equities_us", utc("2026-10-17T15:00"), date(2026, 10, 16), utc("2026-10-17T14:30")) is False


def test_market_view_carries_the_open_state_and_the_last_value():
    last = {"session_date": "2026-10-14", "value": 4188.5, "bar_final": False,
            "updated_at": "2026-10-14T15:30:00+00:00"}
    view = _market_view("futures", date(2026, 10, 14), utc("2026-10-14T16:00"), False, 4190.8, 1, last)
    assert view["open_now"] is True
    assert view["last_value"]["price"] == "4188.5" and view["last_value"]["date"] == "2026-10-14"
    assert view["last_value"]["final"] is False
    closed = _market_view("futures", date(2026, 10, 14), utc("2026-10-17T12:00"), True)
    assert closed["open_now"] is False and closed["last_value"] is None


def test_the_last_value_never_goes_back_to_an_older_session(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_asset_last_value(conn, "GC=F", "2026-10-14", 4188.5, False, "2026-10-14T15:00:00+00:00")
    db.upsert_asset_last_value(conn, "GC=F", "2026-10-13", 4140.0, True, "2026-10-14T15:05:00+00:00")   # séance plus ancienne
    assert db.asset_last_values(conn, ["GC=F"])["GC=F"]["session_date"] == "2026-10-14"
    db.upsert_asset_last_value(conn, "GC=F", "2026-10-14", 4190.8, True, "2026-10-14T21:00:00+00:00")   # même séance : le plus récent
    got = db.asset_last_values(conn, ["GC=F", "^GSPC"])
    assert got["GC=F"]["value"] == 4190.8 and got["GC=F"]["bar_final"] is True and "^GSPC" not in got


class _FakeStore:
    def __init__(self, date_max):
        self.date_max = date_max

    def series_observation(self, symbol):
        return {"date_max": self.date_max} if self.date_max else None


def test_the_last_value_uses_the_real_last_observation_not_the_forward_filled_tail(tmp_path):
    """Série forward-fillée : l'or est figé à 4113.6 du 07 au 13 ; la source dit que sa dernière observation réelle est le 07."""
    conn = db.connect(str(tmp_path / "p.db"))
    idx = pd.bdate_range("2026-10-05", "2026-10-13")
    series = pd.Series([4156.8, 4187.1, 4113.6, 4113.6, 4113.6, 4113.6, 4113.6], index=idx)
    predict_module._record_last_value(conn, "GC=F", series, "futures", _FakeStore("2026-10-07"), "GC=F")
    got = db.asset_last_values(conn, ["GC=F"])["GC=F"]
    assert (got["session_date"], got["value"]) == ("2026-10-07", 4113.6)
    # sans index de séries : dernière barre de la série
    predict_module._record_last_value(conn, "XYZ", series, "futures", _FakeStore(None), "XYZ")
    assert db.asset_last_values(conn, ["XYZ"])["XYZ"]["session_date"] == "2026-10-13"


def _seed(tmp_path, monkeypatch, with_last_value):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^GSPC", 1, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2026-10-14T00:00:00"],
                       y_true=[None], y_pred=[3], y_proba=[0.71])
    db.set_live_signal_context(conn, trial_id, "2026-10-14T00:00:00", None, None, backfill=False, bar_final=False,
                               ref_price=7798.46)
    if with_last_value:
        db.upsert_asset_last_value(conn, "^GSPC", "2026-10-14", 7801.25, False, "2026-10-14T15:30:00+00:00")
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()


@pytest.mark.parametrize("now, label, css", [
    ("2026-10-14T15:45", "Ouvert", "status-ok"),         # mercredi, séance de New York en cours : vert
    ("2026-10-17T15:45", "Fermé", "status-error"),       # samedi : rouge
])
def test_page_shows_green_when_the_market_is_open_and_red_when_it_is_closed(tmp_path, monkeypatch, now, label, css):
    import patrick.webapp.app as webapp

    _seed(tmp_path, monkeypatch, with_last_value=True)
    monkeypatch.setattr(webapp, "utc_now", lambda: utc(now))
    html = TestClient(app).get("/predictions").text

    assert f'<span class="status-badge {css}">{label}</span>' in html
    assert "Actions US" in html
    assert "<strong>7801.25</strong> · cours en séance du 2026-10-14" in html      # la dernière valeur, sa séance
    assert "mis à jour le" in html and "pas encore enregistrée" not in html


def test_page_says_when_the_last_value_is_not_recorded_yet(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, with_last_value=False)
    html = TestClient(app).get("/predictions").text
    assert "pas encore enregistrée (après la prochaine actualisation)" in html
