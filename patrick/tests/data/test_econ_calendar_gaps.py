"""Décisions de banques centrales probablement manquées (CO25 du 25/11)."""
from __future__ import annotations

import datetime as dt

from patrick.data import econ_calendar


def test_a_gap_longer_than_the_meeting_cadence_is_reported(monkeypatch):
    days = ["2026-01-28", "2026-03-18", "2026-06-17", "2026-07-29"]          # avril-mai manquent (91 jours)
    monkeypatch.setattr(econ_calendar, "decisions", lambda conn: [{"date": d, "label": "Fed"} for d in days])
    gaps = econ_calendar.decision_gaps(None, today=dt.date(2026, 8, 20))
    assert gaps == [{"label": "Fed", "after": "2026-03-18", "before": "2026-06-17", "days": 91}]


def test_a_bank_silent_since_its_last_decision_is_reported_up_to_today(monkeypatch):
    monkeypatch.setattr(econ_calendar, "decisions", lambda conn: [{"date": "2026-06-04", "label": "BCE"}])
    (gap,) = econ_calendar.decision_gaps(None, today=dt.date(2026, 9, 1))
    assert gap["label"] == "BCE" and gap["before"] == "2026-09-01"
