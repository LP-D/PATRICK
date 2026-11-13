"""Tableau de bord du résultat réel (`tracking/live_board.py`, page `/reel`)."""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from test_fund_selection import World

from patrick.tracking import db as trackdb
from patrick.tracking import live_board
from patrick.webapp import analysis_routes
from patrick.webapp.app import app

TODAY = dt.date(2026, 3, 2)
DAYS = [d.isoformat() for d in (dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(40)) if d.weekday() < 5]


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _live(conn, trial_id: int, rows: list[tuple]) -> None:
    """`rows` : (jour, classe annoncée, hausse réalisée ou None, P(hausse))."""
    conn.executemany("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba, p_up) VALUES (?, ?, 'live', ?, ?, 0.6, ?)",
                     [(trial_id, day, y_true, y_pred, p_up) for day, y_pred, y_true, p_up in rows])
    conn.commit()


def test_wilson_interval_brackets_the_rate_and_handles_nothing():
    low, high = live_board.wilson(60, 100)
    assert 0.49 < low < 0.6 < high < 0.70 and live_board.wilson(0, 0) is None


def test_the_board_sets_every_score_next_to_the_always_up_strategy(conn, world):
    """40 jugements : toujours « baisse » annoncée dans un marché qui monte 3 fois sur 4. 25 % de bonnes directions, 75 % pour « toujours
    hausse » : l'apport des modèles est de -50 points."""
    tid = world.cell("AAPL", 1, live=None)
    _live(conn, tid, [(day, 0, 1.0 if i % 4 else 0.0, 0.4) for i, day in enumerate(DAYS + [f"2026-02-{d:02d}" for d in range(16, 28)])][:40])

    board = live_board.board(conn, TODAY)

    total = board["total"]
    assert total["n"] == 40 and total["rate"] == 0.25 and total["up_rate"] == 0.75 and total["pred_up_rate"] == 0.0
    assert total["edge"] == pytest.approx(-0.5) and total["ci_low"] < 0.25 < total["ci_high"]
    assert board["n_champions"] == 1 and board["n_models_judged"] == 1
    assert [r["key"] for r in board["by_class"]] == ["equities_us"] and [r["key"] for r in board["by_horizon"]] == [1]
    assert sum(r["n"] for r in board["by_week"]) == 40 and board["by_week"][0]["key"] == "2026-01-05"     # lundi de la première semaine


def test_a_signal_not_yet_judged_is_not_counted_and_small_groups_are_hidden(conn, world):
    tid = world.cell("AAPL", 1, live=None)
    _live(conn, tid, [(DAYS[0], 3, 1.0, 0.7), (DAYS[1], 3, None, 0.7)])

    board = live_board.board(conn, TODAY)

    assert board["total"]["n"] == 1 and board["by_class"] == [] and len(board["by_week"]) == 1


def test_the_re_centred_threshold_is_learned_on_past_weeks_only(conn, world):
    """P(hausse) toujours 0,45 (donc « baisse ») dans un marché qui monte toujours : le seuil recalé sur le passé annonce des hausses."""
    days = [d.isoformat() for d in (dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(420)) if d.weekday() < 5][:260]
    tid = world.cell("AAPL", 1, live=None)
    _live(conn, tid, [(day, 0, 1.0, 0.45) for day in days])

    bias = live_board.board(conn, TODAY)["bias"]

    assert bias["n"] == 260 - 200 and bias["rate"] == 0.0 and bias["shadow_rate"] == 1.0 and bias["gain"] == 1.0
    conn.execute("UPDATE prediction SET p_up = NULL")
    conn.commit()
    assert live_board.board(conn, TODAY)["bias"] is None                      # sans P(hausse), rien à recaler


def test_the_combined_view_averages_the_latest_signal_of_each_horizon(conn, world):
    a1, a5, a10 = (world.cell("AAPL", h, live=None) for h in (1, 5, 10))
    solo = world.cell("MC.PA", 1, live=None)
    old = world.cell("TTE.PA", 1, live=None), world.cell("TTE.PA", 5, live=None)
    _live(conn, a1, [("2026-02-26", 0, None, 0.2), ("2026-02-27", 3, None, 0.8)])        # seul le dernier signal compte
    _live(conn, a5, [("2026-02-27", 3, None, 0.7)])
    _live(conn, a10, [("2026-02-27", 0, None, 0.3)])
    _live(conn, solo, [("2026-02-27", 3, None, 0.9)])                                    # un seul horizon : pas un avis d'ensemble
    for tid in old:
        _live(conn, tid, [("2026-01-05", 3, None, 0.9)])                                # trop vieux

    (view,) = live_board.board(conn, TODAY)["consensus"]

    assert view["target"] == "AAPL" and view["direction"] == "UP" and view["score"] == pytest.approx(0.6)
    assert view["n_up"] == 2 and view["n_horizons"] == 3 and view["horizons"] == [1, 5, 10] and view["last"] == "2026-02-27"


def test_the_page_renders_empty_and_with_results_and_is_in_the_navigation(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    analysis_routes._forget("live_board")
    client = TestClient(app)

    empty = client.get("/reel")
    assert empty.status_code == 200 and "Aucune prédiction réelle jugée." in empty.text and 'href="/reel"' in empty.text

    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    tid = World(conn, monkeypatch).cell("AAPL", 1, live=None)
    _live(conn, tid, [(day, 3, 1.0 if i % 3 else 0.0, 0.6) for i, day in enumerate(DAYS)])
    conn.close()
    analysis_routes._forget("live_board")

    page = client.get("/reel")
    assert page.status_code == 200 and "Stratégie sans modèle" in page.text and "Semaine après semaine" in page.text
    assert "Actions US" in page.text and "2026-01-05" in page.text
    assert " – " in page.text                                        # l'intervalle ne se coupe pas sur deux lignes
    assert client.get("/reel", headers={"Accept-Language": "en"}).status_code == 200
