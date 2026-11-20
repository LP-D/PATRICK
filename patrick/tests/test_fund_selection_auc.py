"""Fonds, niveau de sélection `auc` (ADR 0026) : tous les modèles dont l'AUC de direction du holdout dépasse le hasard, les testés en premier.
Aucun réseau."""
from __future__ import annotations

import datetime as dt

import pytest
from test_fund_selection import World

from patrick.fund import selection, store

TODAY = dt.date(2026, 10, 16)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _auc(conn, trial_id: int, value: float, split: str = "holdout") -> None:
    conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, ?, 'AUC_dir', ?)", (trial_id, split, value))
    conn.commit()


def _cell(conn, world, target: str, horizon: int, auc: float | None, **kw) -> int:
    trial_id = world.cell(target, horizon, **kw)
    if auc is not None:
        _auc(conn, trial_id, auc)
    return trial_id


def _codes(result) -> dict[str, int]:
    return {row["code"]: row["n"] for row in result["excluded"]}


def _select(conn, **kw):
    return selection.select_models(conn, selection.Policy(tier="auc", **kw), today=TODAY)


def test_the_auc_tier_is_a_known_tier_and_the_floor_is_validated():
    assert "auc" in selection.TIERS
    assert selection.Policy.from_dict({"tier": "auc", "auc_floor": 0.55}).auc_floor == 0.55
    assert selection.Policy.from_dict({}).auc_floor == 0.5
    for bad in (0.4, 1.0, "x", True, float("nan")):
        with pytest.raises(store.FundError, match="auc_floor"):
            selection.Policy.from_dict({"auc_floor": bad})


def test_the_tier_keeps_every_model_above_chance_and_explains_the_others(conn, world):
    _cell(conn, world, "UP1", 5, 0.62)
    _cell(conn, world, "UP2", 5, 0.51)
    _cell(conn, world, "EVEN", 5, 0.50)                      # le hasard n'est pas « au-dessus du hasard »
    _cell(conn, world, "BELOW", 5, 0.44)
    _cell(conn, world, "UNMEASURED", 5, None)                # pas d'AUC de direction : rattrapage des mesures pas encore passé

    out = _select(conn)

    assert sorted(m["target"] for m in out["selected"]) == ["UP1", "UP2"]
    assert _codes(out) == {"auc": 2, "no_auc": 1}
    why = {c["target"]: c["detail"] for c in out["excluded_cells"]}
    assert "0,500" in why["EVEN"] and "0,440" in why["BELOW"]


def test_it_needs_no_statistical_proof_but_flags_who_has_it(conn, world):
    _cell(conn, world, "TESTED", 5, 0.58, dm_p=0.01, bh=(True, 0.02))
    _cell(conn, world, "NO_DM", 5, 0.60, dm_p=None)                         # pas de test de Diebold-Mariano
    _cell(conn, world, "DM_WEAK", 5, 0.60, dm_p=0.30)
    _cell(conn, world, "BH_OUT", 5, 0.61, dm_p=0.01, bh=(False, 0.50))      # cible écartée par la correction pour tests multiples

    out = _select(conn)

    evidence = {m["target"]: m["evidence"] for m in out["selected"]}
    assert evidence == {"TESTED": "tested", "NO_DM": "auc", "DM_WEAK": "auc", "BH_OUT": "auc"}
    assert next(m for m in out["selected"] if m["target"] == "TESTED")["auc_dir"] == 0.58


def test_the_tested_models_come_first_even_with_a_lower_auc(conn, world):
    _cell(conn, world, "HIGH_AUC", 5, 0.70, dm_p=0.30)
    _cell(conn, world, "TESTED_B", 5, 0.53, dm_p=0.04)
    _cell(conn, world, "TESTED_A", 5, 0.52, dm_p=0.001)

    out = _select(conn)

    assert [m["target"] for m in out["selected"]] == ["TESTED_A", "TESTED_B", "HIGH_AUC"]


def test_a_higher_floor_keeps_fewer_models_and_the_cap_keeps_the_best_ranked(conn, world):
    _cell(conn, world, "A", 5, 0.52, dm_p=0.001)
    _cell(conn, world, "B", 5, 0.60, dm_p=0.20)
    _cell(conn, world, "C", 5, 0.58, dm_p=0.30)

    assert sorted(m["target"] for m in _select(conn, auc_floor=0.55)["selected"]) == ["B", "C"]
    capped = _select(conn, max_models=1)
    assert [m["target"] for m in capped["selected"]] == ["A"] and _codes(capped) == {"cap": 2}


def test_the_common_exclusions_still_apply(conn, world):
    _cell(conn, world, "STALE", 5, 0.60, live=("2026-09-01", 3, 0.6))
    _cell(conn, world, "NOLIVE", 5, 0.60, live=None)
    _cell(conn, world, "FINE", 5, 0.60)
    _cell(conn, world, "LEAK", 5, 0.60, f1=0.95)                          # score impossible : fuite de données probable

    out = _select(conn)

    assert [m["target"] for m in out["selected"]] == ["FINE"]
    assert _codes(out) == {"stale": 1, "no_live": 1, "suspect": 1}


def test_the_other_tiers_are_unchanged_and_carry_no_evidence(conn, world):
    _cell(conn, world, "BELOW", 5, 0.40, dm_p=0.01)

    large = selection.select_models(conn, selection.Policy(tier="large"), today=TODAY)
    strict = selection.select_models(conn, selection.Policy(tier="strict"), today=TODAY)

    assert [m["target"] for m in large["selected"]] == ["BELOW"] and large["selected"][0]["evidence"] is None
    assert strict["selected"][0]["evidence"] is None and strict["selected"][0]["auc_dir"] == 0.40
