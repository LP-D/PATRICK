"""Résultat réel d'un modèle (`tracking/live_record.py`) et son usage par la sélection des fonds."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_selection import World

from patrick.fund import selection, store
from patrick.tracking import live_record

TODAY = dt.date(2026, 10, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _judge(conn, trial_id: int, n: int, hits: int) -> None:
    """`n` prédictions réelles jugées, toutes annoncées en hausse (classe 3), dont `hits` suivies d'une hausse (y_true binaire)."""
    days = [d.strftime("%Y-%m-%d") for d in fs.IDX[-(n + 40):-40]]
    conn.executemany("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba) VALUES (?, ?, 'live', ?, 3, 0.6)",
                     [(trial_id, day, 1.0 if i < hits else 0.0) for i, day in enumerate(days)])
    conn.commit()


def test_records_count_judged_live_predictions_on_the_binary_outcome(conn, world):
    good, bad, none = world.cell("AAPL", 1), world.cell("MC.PA", 1), world.cell("TTE.PA", 1)
    _judge(conn, good, 30, 20)
    _judge(conn, bad, 30, 6)

    assert live_record.records(conn, [good, bad, none]) == {good: (31 - 1, 20), bad: (30, 6)}      # le signal du jour, non jugé, ne compte pas


def test_failing_needs_enough_judgements_and_a_clear_gap_given_the_overlap():
    assert live_record.failing(40, 12, 1) is True
    assert live_record.failing(19, 2, 1) is False               # pas assez de jugements
    assert live_record.failing(40, 17, 1) is False              # 42 % : le bruit suffit
    assert live_record.failing(40, 12, 10) is False             # horizons de 10 jours : 4 jugements indépendants
    assert live_record.z_score(0, 0, 1) is None and live_record.z_score(100, 50, 5) == 0.0


def test_the_fund_selection_drops_a_model_clearly_wrong_in_live_use(conn, world):
    good, bad = world.cell("AAPL", 1), world.cell("MC.PA", 1)
    _judge(conn, good, 30, 20)
    _judge(conn, bad, 30, 6)

    chosen = selection.select_models(conn, selection.Policy(), TODAY)

    assert [m["trial_id"] for m in chosen["selected"]] == [good]
    (cell,) = [c for c in chosen["excluded_cells"] if c["code"] == "live"]
    assert cell["target"] == "MC.PA" and "6 bonne(s) direction(s) sur 30" in cell["detail"]
    relaxed = selection.select_models(conn, selection.Policy(live_gate=False), TODAY)
    assert {m["trial_id"] for m in relaxed["selected"]} == {good, bad}


def test_the_live_gate_is_a_boolean_setting_kept_in_the_policy():
    assert selection.Policy.from_dict({}).live_gate is True
    assert selection.Policy.from_dict({"live_gate": False}).to_dict()["live_gate"] is False
    with pytest.raises(store.FundError, match="live_gate"):
        selection.Policy.from_dict({"live_gate": "non"})
