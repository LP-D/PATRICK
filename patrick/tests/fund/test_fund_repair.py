"""Fonds, pilote automatique : positions orphelines d'une règle retirée dont le modèle a perdu ses signaux, et règles en double sur une même
cellule (constats du 2026-11-27 : 247 positions jamais refermées, 74 règles créées deux fois par deux cycles simultanés). Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_selection import World

from patrick.fund import autopilot, store, systematic

UP, DOWN = 3, 0
AAPL_SIGNALS = [("2026-01-12", UP, 0.6), ("2026-01-13", UP, 0.6), ("2026-01-15", DOWN, 0.6)]
DAY0, DAY1 = dt.date(2026, 1, 15), dt.date(2026, 1, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _orders(conn, sid):
    return [(o["ts"], o["action"], o["side"]) for o in store.list_orders(conn, sid)]


def _fund_with_an_open_short(conn, world):
    """AAPL h3 : la position courte s'ouvre le 16 (signal baissier du 15), échéance le 21."""
    tid = world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    autopilot.run(conn, sid, DAY1)
    assert _orders(conn, sid) == [("2026-01-16", "open", "short")]
    return sid, tid


def _prune_and_drop_out(conn, tid):
    """Le run du champion est élagué (duel perdu : ses prédictions disparaissent) et la cellule sort de la sélection."""
    conn.execute("DELETE FROM prediction WHERE trial_id = ?", (tid,))
    conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, 'holdout', 'F1_dir', 0.99)", (tid,))
    conn.commit()


def test_a_retired_rule_without_signals_still_closes_its_position(conn, world):
    sid, tid = _fund_with_an_open_short(conn, world)
    _prune_and_drop_out(conn, tid)

    retiring = autopilot.run(conn, sid, dt.date(2026, 1, 20))
    (rule,) = systematic.list_rules(conn, sid)
    assert retiring["retired"] == [rule["rule_id"]] and rule["config"]["retired_on"] == "2026-01-19"
    with pytest.raises(store.FundError):
        systematic.plan(conn, rule)                                         # plus aucun signal : le plan ne se calcule plus
    # échéance du dernier signal possible avant le retrait : 19 + 1 jour + 3 séances = le 23 ; rien n'échoue, la fermeture attend
    assert [(p["requested"], p["reason"]) for p in systematic.orphan_closes(conn, rule)] == [("2026-01-23", "orphan")]
    assert retiring["failed"] == [] and retiring["pending"] == 1 and _orders(conn, sid) == [("2026-01-16", "open", "short")]

    closing = autopilot.run(conn, sid, dt.date(2026, 1, 23))

    assert closing["orphans_closed"] == 1 and closing["failed"] == []
    assert _orders(conn, sid) == [("2026-01-16", "open", "short"), ("2026-01-23", "close", "short")]
    assert systematic.open_positions(conn, rule) == []
    assert autopilot.run(conn, sid, dt.date(2026, 1, 26))["placed"] == 0              # une fois fermée, plus rien


def test_an_active_rule_without_signals_is_still_an_error(conn, world):
    sid, tid = _fund_with_an_open_short(conn, world)
    conn.execute("DELETE FROM prediction WHERE trial_id = ?", (tid,))
    conn.commit()
    (rule,) = systematic.list_rules(conn, sid)
    with pytest.raises(store.FundError):
        systematic.apply(conn, rule["rule_id"], DAY1)


def _duplicate(conn, sid):
    (rule,) = systematic.list_rules(conn, sid)
    return systematic.create_rule(conn, sid, rule["name"], dict(rule["config"]))


def test_a_cycle_drops_a_duplicate_rule_and_the_orders_it_doubled(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    extra = _duplicate(conn, sid)                                          # comme deux cycles simultanés
    systematic.apply(conn, extra, DAY1)                                    # le double ouvre sa propre position
    assert len(store.list_orders(conn, sid)) == 1

    report = autopilot.run(conn, sid, DAY1)

    # la plus ancienne reste ; créées dans la même seconde, l'une ou l'autre peut l'être : le fonds finit pareil (une règle, une position)
    assert len(report["deduplicated"]) == 1 and report["deduplicated"][0]["orders"] in (0, 1)
    assert len(systematic.list_rules(conn, sid)) == 1
    assert _orders(conn, sid) == [("2026-01-16", "open", "short")]         # une seule position, celle de la règle gardée
    assert autopilot.run(conn, sid, DAY1)["deduplicated"] == []


def test_repair_previews_then_fixes_duplicates_and_orphans(conn, world):
    sid, tid = _fund_with_an_open_short(conn, world)
    extra = _duplicate(conn, sid)
    _prune_and_drop_out(conn, tid)
    (kept,) = [r for r in systematic.list_rules(conn, sid) if r["rule_id"] != extra]
    systematic.retire_rule(conn, kept["rule_id"], "2026-01-19")            # la règle gardée a été retirée comme dans la vraie base
    systematic.retire_rule(conn, extra, "2026-01-19")

    preview = autopilot.repair(conn, sid, dt.date(2026, 1, 23))

    assert preview["applied"] is False and preview["duplicates"] == []    # deux règles retirées ne sont pas des doublons actifs
    assert [(o["rule_id"], o["close_on"]) for o in preview["orphans"]] == [(kept["rule_id"], "2026-01-23")]
    assert _orders(conn, sid) == [("2026-01-16", "open", "short")]        # l'aperçu n'écrit rien

    fixed = autopilot.repair(conn, sid, dt.date(2026, 1, 23), apply=True)

    assert fixed["closed"] == 1 and fixed["refused"] == []
    assert _orders(conn, sid) == [("2026-01-16", "open", "short"), ("2026-01-23", "close", "short")]
    assert autopilot.repair(conn, sid, dt.date(2026, 1, 23))["orphans"] == []


def test_repair_drops_active_duplicates(conn, world):
    world.cell("AAPL", 3, live=AAPL_SIGNALS)
    sid = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")
    autopilot.configure(conn, sid, {})
    autopilot.run(conn, sid, DAY0)
    extra = _duplicate(conn, sid)
    systematic.apply(conn, extra, DAY1)

    preview = autopilot.repair(conn, sid, DAY1)
    assert len(preview["duplicates"]) == 1 and len(systematic.list_rules(conn, sid)) == 2       # l'aperçu n'écrit rien
    dropped = preview["duplicates"][0]["rule_id"]

    autopilot.repair(conn, sid, DAY1, apply=True)
    assert [r["rule_id"] for r in systematic.list_rules(conn, sid)] == [preview["duplicates"][0]["kept"]]
    assert len(store.list_orders(conn, sid)) == (1 if dropped != extra else 0)          # les ordres partent avec la règle supprimée
