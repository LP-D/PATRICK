"""Frise des dernières nuits (VI10 du 26/11)."""
from __future__ import annotations

from patrick.system import night_history

LOG = """2026-11-23 23:00:03 ===== passage de nuit (fin : hibernate, inactivite requise : 10 min)
2026-11-23 23:00:10 == mise a jour : python -m patrick.desktop update
\x00   termine (code 0) en 12 s
predictions : 3 000 lignes de sortie
2026-11-24 00:00:00 == predictions utiles aux fonds et pilote automatique : python daily_predict.py
2026-11-24 03:00:00    termine (code 1) en 10 800 s
2026-11-24 03:23:33 == synchronisation : python -m patrick.cli sync auto
2026-11-24 03:30:48    termine (code 1) en 434 s
2026-11-24 23:00:03 ===== passage de nuit (fin : hibernate, inactivite requise : 10 min)
2026-11-24 23:00:10 == mise a jour : python -m patrick.desktop update
2026-11-24 23:00:20    termine (code 0) en 10 s
"""


def test_nights_and_their_steps_are_read_from_the_useful_lines_only(tmp_path):
    (tmp_path / "nightly.log").write_text(LOG, encoding="utf-8")
    nights = night_history.history(tmp_path)
    assert [n["started"][:10] for n in nights] == ["2026-11-23", "2026-11-24"]
    first = nights[0]["steps"]
    assert [s["name"] for s in first] == ["mise a jour", "predictions utiles aux fonds et pilote automatique", "synchronisation"]
    assert first[1]["hours"] == 3.0 and first[1]["offset_h"] > 0.9 and first[2]["failed"] is True
    assert nights[0]["total_h"] > 4.4


def test_no_log_gives_an_empty_history_and_the_fragment_says_so(tmp_path):
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app
    assert night_history.history(tmp_path) == []
    assert TestClient(app).get("/fragments/night-history").status_code == 200
