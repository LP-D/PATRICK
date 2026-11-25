"""Assistant de lancement par objectif de temps (FO27 du 25/11)."""
from __future__ import annotations

from patrick.tracking import launch_advice


def test_the_deepest_profile_that_fits_is_recommended(monkeypatch):
    monkeypatch.setattr(launch_advice, "durations", lambda conn, target=None: {
        "quick": [5, 6, 7], "standard": [25, 30, 35], "deep": [120, 150, 180], "robust": [40]})
    out = launch_advice.advise(None, 32)
    assert [p["key"] for p in out["profiles"]] == ["quick", "standard", "deep"]           # « robust » : un seul run, écarté
    assert out["recommended"] == "standard" and launch_advice.advise(None, 4)["recommended"] is None


def test_minutes_between_two_timestamps():
    assert launch_advice._minutes("2026-11-25 10:00:00", "2026-11-25 10:30:00") == 30
    assert launch_advice._minutes(None, "2026-11-25") is None
