# ruff: noqa: DTZ001, DTZ005 -- heures locales voulues : la file se règle à l'heure murale du PC
"""File retenue jusqu'à une heure donnée (FO26 du 25/11)."""
from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from patrick.system import queue_hold


def test_the_queue_is_held_until_the_chosen_time_then_released():
    queue_hold.set_hold(dt.datetime(2026, 11, 25, 23, 0))
    assert queue_hold.held(dt.datetime(2026, 11, 25, 22, 59)) and not queue_hold.held(dt.datetime(2026, 11, 25, 23, 0))
    queue_hold.set_hold(None)
    assert queue_hold.hold_until() is None and not queue_hold.held()


def test_the_route_sets_and_clears_the_hold():
    client = TestClient(__import__("patrick.webapp.app", fromlist=["app"]).app)
    future = (dt.datetime.now() + dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    assert client.post("/api/queue/hold", json={"until": future}).json()["until"] == future
    assert client.post("/api/queue/hold", json={"until": "demain"}).status_code == 400
    assert client.post("/api/queue/hold", json={"until": None}).json()["until"] is None
