"""Fonds réels (ADR 0026) : le PEA et le CTO fictifs, 5 000 €, 1 € par ordre, tous les signaux. Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from test_fund_selection import World

from patrick.fund import autopilot, envelopes, real_funds, service, store

TODAY = dt.date(2026, 1, 16)
UP, DOWN = 3, 0
SIGNALS = [("2026-01-14", UP, 0.6), ("2026-01-15", UP, 0.6)]


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _auc(conn, trial_id: int, value: float) -> None:
    conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, 'holdout', 'AUC_dir', ?)", (trial_id, value))
    conn.commit()


def test_setup_creates_the_pea_and_the_cto_with_their_envelope_fees_and_pilot(conn):
    rows = real_funds.setup(conn, today=TODAY)

    assert [(r["kind"], r["name"], r["created"]) for r in rows] == [("PEA", "PEA Tous signaux", True), ("CTO", "CTO Tous signaux", True)]
    pea, cto = (store.get_strategy(conn, r["strategy_id"]) for r in rows)
    for fund, wrapper in ((pea, "PEA"), (cto, "CTO")):
        assert fund["wrapper"] == wrapper and fund["category"] == "real" and fund["fee_flat"] == 1.0
        assert fund["initial_capital"] == 5_000 and fund["base_currency"] == "EUR"
    pea_pilot = store.get_autopilot(conn, pea["strategy_id"])
    assert pea_pilot["enabled"] is True
    assert (pea_pilot["settings"]["tier"], pea_pilot["settings"]["allow_short"], pea_pilot["settings"]["min_position"]) == ("auc", False, 200.0)
    assert pea_pilot["settings"]["groups"] == list(envelopes.PEA_GROUPS) and pea_pilot["settings"]["horizons"] is None
    cto_pilot = store.get_autopilot(conn, cto["strategy_id"])["settings"]
    assert (cto_pilot["tier"], cto_pilot["allow_short"], cto_pilot["groups"], cto_pilot["horizons"]) == ("auc", False, None, None)   # pas de vente à découvert


def test_setup_reuses_the_funds_it_already_made_and_never_duplicates(conn):
    first = real_funds.setup(conn, today=TODAY)
    second = real_funds.setup(conn, today=TODAY)

    assert [r["created"] for r in second] == [False, False]
    assert [r["strategy_id"] for r in second] == [r["strategy_id"] for r in first]
    assert len(store.list_strategies(conn)) == 2


def test_setup_can_make_a_single_fund_and_dry_run_writes_nothing(conn, monkeypatch):
    world = World(conn, monkeypatch)
    _auc(conn, world.cell("MC.PA", 1, live=SIGNALS), 0.6)
    _auc(conn, world.cell("AAPL", 1, live=SIGNALS), 0.6)

    preview = real_funds.setup(conn, today=TODAY, dry_run=True)
    only_cto = real_funds.setup(conn, today=TODAY, only=["CTO"])

    assert [(r["kind"], r["strategy_id"]) for r in preview] == [("PEA", None), ("CTO", None)]
    assert [r["candidates"] for r in preview] == [1, 2]                  # le PEA ne cherche que des actions européennes
    assert [r["kind"] for r in only_cto] == ["CTO"] and [s["name"] for s in store.list_strategies(conn)] == ["CTO Tous signaux"]


def test_setup_validates_everything_before_writing_anything(conn):
    for kwargs, message in (({"capital": 200_000}, "plafond"), ({"capital": 0}, "capital"), ({"fee_flat": -1}, "frais"),
                            ({"only": ["LIVRET"]}, "inconnu"), ({"tier": "folle"}, "tier"), ({"min_position": -3}, "min_position")):
        with pytest.raises(store.FundError, match=message):
            real_funds.setup(conn, today=TODAY, **kwargs)
        assert store.list_strategies(conn) == []


def test_setup_refuses_to_take_over_a_quant_fund_of_the_same_name(conn):
    traded = store.create_strategy(conn, "PEA Tous signaux", "PEA", 100_000, "2026-01-05")
    store.insert_order(conn, {"strategy_id": traded, "position_id": "pos_0000000001", "ts": "2026-01-07", "action": "open",
                              "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 1.0, "price": 700.0,
                              "price_source": "market", "currency": "EUR", "fx_rate": 1.0, "fees": 1.0, "fees_source": "estimated",
                              "fee_seed": 7, "spec": {}, "note": None})           # un fonds qui a tradé ne change plus de catégorie

    with pytest.raises(store.FundError, match="existe déjà"):
        real_funds.setup(conn, today=TODAY)
    assert [s["category"] for s in store.list_strategies(conn)] == ["quant"]


def test_a_quant_fund_named_like_the_old_every_signal_fund_is_left_alone(conn):
    """Seul un ancien fonds reproductible « Systematic CTO / PEA » est renommé (ADR 0029) : un fonds quant de ce nom garde son nom et sa catégorie."""
    quant = store.create_strategy(conn, "Systematic PEA", "PEA", 100_000, "2026-01-05")

    rows = real_funds.setup(conn, today=TODAY, only=["PEA"])

    assert rows[0]["name"] == "PEA Tous signaux" and rows[0]["strategy_id"] != quant
    assert (store.get_strategy(conn, quant)["name"], store.get_strategy(conn, quant)["category"]) == ("Systematic PEA", "quant")


def test_setup_counts_the_selected_models_as_trials_like_the_other_funds(conn, monkeypatch):
    """Choisir ces modèles pour un fonds est un usage de plus des mêmes données (ADR 0010) : un essai de plus par cellule retenue."""
    world = World(conn, monkeypatch)
    _auc(conn, world.cell("MC.PA", 1, live=SIGNALS), 0.6)

    real_funds.setup(conn, today=TODAY, only=["PEA"])

    rows = conn.execute("SELECT target, horizon, source, n_trials, detail FROM trial_registry WHERE detail LIKE 'fund_selection:%'").fetchall()
    assert rows == [("MC.PA", 1, "simulation", 1, "fund_selection:PEA Tous signaux")]


def test_a_cycle_trades_the_signals_of_the_pea_with_one_euro_per_order(conn, monkeypatch):
    world = World(conn, monkeypatch)
    for target, auc in (("MC.PA", 0.62), ("TTE.PA", 0.55), ("AAPL", 0.70)):
        _auc(conn, world.cell(target, 1, live=[("2026-01-14", UP, 0.6), ("2026-01-15", UP, 0.6)], dm_p=0.2, bh=(False, 0.5)), auc)
    day0 = dt.date(2026, 1, 15)                                               # le signal du 15 s'exécute le 16 : deux cycles, comme au quotidien
    pea = real_funds.setup(conn, today=day0, only=["PEA"], min_position=1_000)[0]["strategy_id"]
    autopilot.run(conn, pea, day0)

    report = autopilot.run(conn, pea, TODAY)

    orders = store.list_orders(conn, pea)
    assert report["selected"] == 2 and report["placed"] >= 1 and orders
    assert {o["symbol"] for o in orders} <= {"MC.PA", "TTE.PA"}                # AAPL (hors UE) n'entre jamais dans un PEA
    assert all(o["fees"] == 1.0 and o["side"] == "long" and o["instrument_kind"] == "equity" and o["currency"] == "EUR" for o in orders)
    snap = service.strategy_snapshot(conn, store.get_strategy(conn, pea), TODAY)
    assert snap["kpis"]["fees"] == pytest.approx(len(orders))                  # 1 € par ordre, ni plus ni moins
    assert not snap["violations"]


def test_the_pea_refuses_what_the_envelope_forbids_even_by_hand(conn):
    pea = real_funds.setup(conn, today=TODAY, only=["PEA"])[0]["strategy_id"]

    quote = service.quote(conn, {"strategy_id": pea, "instrument_kind": "equity", "symbol": "AAPL", "side": "long", "quantity": 1,
                                 "date": "2026-01-07"}, TODAY)
    cfd = service.quote(conn, {"strategy_id": pea, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long", "quantity": 1,
                               "date": "2026-01-07"}, TODAY)

    assert not quote["ok"] and any("euro" in m for m in quote["blocking"])
    assert not cfd["ok"] and any("PEA" in m for m in cfd["blocking"])
