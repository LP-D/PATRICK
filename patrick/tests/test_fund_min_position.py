"""Fonds, pilote automatique : taille minimale d'une position et filtre d'éligibilité du PEA dans le plan (ADR 0026). Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_selection import World

from patrick.fund import autopilot, store

TODAY = dt.date(2026, 1, 16)
SIGNALS = [("2026-01-14", 3, 0.6), ("2026-01-15", 3, 0.6)]
# (devise, prix, dérive) : de quoi faire des cellules françaises, allemandes, suisses et suédoises cotées
EXTRA = {"SAP.DE": ("EUR", 120.0, 0.1), "OR.PA": ("EUR", 400.0, 0.3), "BNP.PA": ("EUR", 60.0, 0.1), "NESN.SW": ("CHF", 100.0, 0.1),
         "VOLV-B.ST": ("SEK", 250.0, 0.2)}


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)
    for symbol, row in EXTRA.items():
        monkeypatch.setitem(fs.FAKE, symbol, row)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _fund(conn, wrapper="CTO", capital=5_000, **settings) -> str:
    sid = store.create_strategy(conn, "Réel", wrapper, capital, "2026-01-05", category="real", fee_flat=1.0)
    autopilot.configure(conn, sid, {"tier": "large", "allow_short": False, **settings})
    return sid


def _cells(world, *targets, horizon=3):
    for target in targets:
        world.cell(target, horizon, live=SIGNALS)


def test_min_position_is_a_validated_optional_setting():
    assert autopilot.Settings.from_dict({}).min_position is None
    assert autopilot.Settings.from_dict({"min_position": "200"}).min_position == 200.0
    assert autopilot.Settings.from_dict(autopilot.Settings.from_dict({"min_position": 150}).to_dict()).min_position == 150.0
    for bad in (0, -5, "x", True):
        with pytest.raises(store.FundError, match="min_position"):
            autopilot.Settings.from_dict({"min_position": bad})


def test_without_a_minimum_every_model_is_funded_however_small(conn, world):
    _cells(world, "MC.PA", "TTE.PA", "OR.PA", "BNP.PA", "SAP.DE")
    sid = _fund(conn, "PEA")

    plan = autopilot.preview(conn, sid, TODAY)

    assert len(plan["selected"]) == 5 and min(m["notional"] for m in plan["selected"]) < 1_000       # 5 000 € sur 5 modèles : l'un d'eux est sous 1 000 €


def test_the_minimum_keeps_the_best_ranked_models_that_the_budget_can_fund(conn, world):
    for target, dm_p in (("MC.PA", 0.001), ("TTE.PA", 0.002), ("OR.PA", 0.003), ("BNP.PA", 0.004), ("SAP.DE", 0.005)):
        world.cell(target, 3, live=SIGNALS, dm_p=dm_p)
    sid = _fund(conn, "PEA", min_position=1_000)               # 5 000 € de budget : au plus 5 positions de 1 000 €, et les poids ne sont pas égaux

    plan = autopilot.preview(conn, sid, TODAY)

    rank = ["MC.PA", "TTE.PA", "OR.PA", "BNP.PA", "SAP.DE"]
    kept = [m["target"] for m in plan["selected"]]
    dropped = [e["target"] for e in plan["excluded"] if e["code"] == "min_size"]
    assert 1 <= len(kept) <= 5 and all(m["notional"] >= 1_000 - 0.01 for m in plan["selected"])
    assert kept == rank[:len(kept)]                                    # les premiers de la sélection, jamais les derniers
    assert set(dropped) == set(rank[len(kept):])                       # tous les autres sont écartés, avec le motif
    assert sum(m["notional"] for m in plan["selected"]) == pytest.approx(5_000, abs=0.05)         # le budget est redistribué sur les modèles gardés


def test_a_tight_minimum_caps_the_number_of_positions_arithmetically(conn, world):
    for target, dm_p in (("MC.PA", 0.001), ("TTE.PA", 0.002), ("OR.PA", 0.003), ("BNP.PA", 0.004)):
        world.cell(target, 3, live=SIGNALS, dm_p=dm_p)
    sid = _fund(conn, "PEA", min_position=2_400)               # 5 000 // 2 400 = 2 positions au plus

    plan = autopilot.preview(conn, sid, TODAY)

    assert len(plan["selected"]) <= 2 and plan["selected"][0]["target"] == "MC.PA"
    reasons = [e for e in plan["excluded"] if e["code"] == "min_size"]
    assert len(reasons) >= 2 and all("2400" in e["detail"] or "2 400" in e["detail"] or "poids" in e["detail"] for e in reasons)
    assert {s["label"] for s in plan["excluded_summary"]} >= {autopilot.LABELS["min_size"]}


def test_a_budget_below_the_minimum_still_funds_one_position(conn, world):
    _cells(world, "MC.PA", "TTE.PA")
    sid = _fund(conn, "PEA", capital=150, min_position=200)

    plan = autopilot.preview(conn, sid, TODAY)

    assert len(plan["selected"]) == 1 and plan["selected"][0]["notional"] == pytest.approx(150, abs=0.01)


def test_the_minimum_applies_to_cfd_funds_too(conn, world):
    _cells(world, "^GSPC", "CL=F", "MC.PA")
    sid = _fund(conn, "CTO", allow_short=True, min_position=2_000)

    plan = autopilot.preview(conn, sid, TODAY)

    assert len(plan["selected"]) <= 2 and sum(1 for e in plan["excluded"] if e["code"] == "min_size") >= 1
    assert all(m["notional"] >= 2_000 - 0.01 for m in plan["selected"])


def test_a_pea_only_takes_euro_shares_of_the_eu_and_says_why_for_the_rest(conn, world):
    _cells(world, "MC.PA", "SAP.DE", "AAPL", "VOD.L", "NESN.SW", "VOLV-B.ST", "^GSPC", "CL=F")
    sid = _fund(conn, "PEA")

    plan = autopilot.preview(conn, sid, TODAY)

    assert sorted(m["target"] for m in plan["selected"]) == ["MC.PA", "SAP.DE"]
    assert all(m["instrument"]["kind"] == "equity" and m["allow_short"] is False for m in plan["selected"])
    codes = {e["target"]: e["code"] for e in plan["excluded"]}
    assert codes == {"AAPL": "pea_zone", "VOD.L": "pea_zone", "NESN.SW": "pea_zone", "VOLV-B.ST": "pea_devise", "^GSPC": "pea", "CL=F": "pea"}
    assert all(code in autopilot.LABELS for code in codes.values())
    assert "AAPL" not in {c[0] for c in fs.CALLS}                 # une exclusion se juge avant de télécharger une cotation


def test_a_cto_keeps_the_whole_universe(conn, world):
    _cells(world, "MC.PA", "AAPL", "VOD.L", "^GSPC", "CL=F")
    sid = _fund(conn, "CTO")

    plan = autopilot.preview(conn, sid, TODAY)

    assert {m["target"] for m in plan["selected"]} == {"MC.PA", "AAPL", "VOD.L", "^GSPC", "CL=F"}
