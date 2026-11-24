"""Fonds de test combinés (ADR 0029) : ML/DL croisé avec l'agent RL et la volatilité avant de trader. Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import numpy as np
import pandas as pd
import pytest
from test_fund_selection import World
from typer.testing import CliRunner

from patrick.fund import autopilot, combo, store, systematic
from patrick.fund.combo import Inputs
from patrick.tracking import db as trackdb

TODAY = dt.date(2026, 1, 16)
DAY0 = dt.date(2026, 1, 15)                       # le signal du 15 s'exécute le 16 : deux cycles, comme au quotidien
UP, DOWN = 3, 0
SIGNALS = [("2026-01-14", UP, 0.6), ("2026-01-15", UP, 0.6)]


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def _auc(conn, trial_id: int, value: float = 0.6) -> int:
    conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, 'holdout', 'AUC_dir', ?)", (trial_id, value))
    conn.commit()
    return trial_id


def _world(conn, monkeypatch, *, vix=True) -> tuple[World, int, int | None]:
    world = World(conn, monkeypatch)
    mc = _auc(conn, world.cell("MC.PA", 1, live=SIGNALS, dm_p=0.2, bh=(False, 0.5)))
    vix_trial = world.cell("^VIX", 1, live=SIGNALS, dm_p=0.2, bh=(False, 0.5)) if vix else None   # lu (régime), jamais tradé : pas d'AUC
    return world, mc, vix_trial


def _cycle(conn, sid: str) -> dict:
    autopilot.run(conn, sid, DAY0)
    return autopilot.run(conn, sid, TODAY)


def _opened(conn, sid: str) -> dict[str, float]:
    return {o["symbol"]: o["quantity"] for o in store.list_orders(conn, sid) if o["action"] == "open"}


# --------------------------------------------------------------------------- réglages et validation

def test_settings_need_a_source_besides_the_ml_signal():
    assert combo.check_settings(None) is None
    assert combo.check_settings({"vol": True}) == {"rl": False, "vol": True, "cost_multiple": 1.0}
    for raw, message in (({"rl": False, "vol": False}, "au moins"), ({"rl": "oui"}, "booléens"), ({"vol": True, "cost_multiple": 11}, "cost_multiple"),
                         ("rl", "objet")):
        with pytest.raises(store.FundError, match=message):
            combo.check_settings(raw)


def test_a_rule_signal_is_normalised_and_the_cost_filter_needs_a_cost():
    plain = combo.check_signal({"mode": "combo"})
    assert (plain["rl"], plain["vol"], plain["regime"], plain["median_conviction"]) == (None, False, None, 0.1)
    full = combo.check_signal({"rl": {"job_id": "j1", "target": "MC.PA"}, "vol": True, "cost_rt": 0.002,
                               "regime": {"trial_id": 7, "role": "risk", "symbol": "^VIX"}, "persistence": 0.4, "median_conviction": 0.2})
    assert full["rl"] == {"job_id": "j1", "target": "MC.PA"} and full["regime"]["trial_id"] == 7 and full["cost_rt"] == 0.002
    for raw, message in (({"vol": True}, "cost_rt requis"), ({"rl": {"job_id": ""}}, "job_id"), ({"rl": "j1"}, "rl invalide"),
                         ({"regime": {"trial_id": 7, "role": "or"}}, "regime"), ({"regime": {"trial_id": True, "role": "risk"}}, "regime"),
                         ({"persistence": 1.0}, "persistence"), ({"cost_rt": 1.5, "vol": True}, "cost_rt"), ({"vol": "oui"}, "booléen")):
        with pytest.raises(store.FundError, match=message):
            combo.check_signal(raw)


def test_the_frozen_log_refuses_an_unreadable_entry():
    assert combo.check_log({"2026-01-05": [2, 0.5], "2026-01-06": [-1, None]}) == {"2026-01-05": [2, 0.5], "2026-01-06": [-1, None]}
    for raw in ({"2026-01-05": [3, None]}, {"2026-01-05": [True, None]}, {"2026-01-05": [1]}, ["2026-01-05"]):
        with pytest.raises(store.FundError, match="combo_log"):
            combo.check_log(raw)


# --------------------------------------------------------------------------- sources

@pytest.mark.parametrize("symbol, role", [
    ("^GSPC", ("equity", "risk")), ("MC.PA", ("equity", "risk")), ("BTC-USD", ("equity", "risk")), ("HG=F", ("equity", "risk")),
    ("GC=F", ("gold", "haven")), ("CL=F", ("oil", "risk")), ("ZN=F", ("rates", "vol_only")),
    ("EURUSD=X", None), ("^VIX", None), ("ZC=F", None)])
def test_each_asset_reads_the_volatility_index_of_its_class(symbol, role):
    assert combo.regime_role(symbol) == role


def test_the_forecast_volatility_never_reads_the_future():
    rng = np.random.default_rng(1)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 120))), index=pd.bdate_range("2025-01-01", periods=120))
    changed = close.copy()
    changed.iloc[100:] *= 1.5                                         # un krach... dans le futur

    for fn in (combo.ewma_vol, combo.ref_vol):
        before, after = fn(close), fn(changed)
        known = before.index < close.index[100]
        assert known.sum() > 30 and np.allclose(before[known], after[before.index[known]])
    assert combo.ewma_vol(close.iloc[:20]).empty                      # moins de 30 séances : pas de volatilité


def test_the_round_trip_cost_follows_the_instrument_the_fee_and_the_horizon():
    assert combo.round_trip_cost("equity", "MC.PA", 5_000, "EUR", 1.0, 1) == pytest.approx(2 / 5_000)    # forfait : 1 € à l'achat, 1 € à la vente
    eur, usd = (combo.round_trip_cost("equity", s, 50_000, c, None, 1) for s, c in (("MC.PA", "EUR"), ("AAPL", "USD")))
    assert 0 < eur < usd                                              # le change d'une action étrangère se paie
    one, five = (combo.round_trip_cost("cfd", "^GSPC", 50_000, "USD", None, h) for h in (1, 5))
    assert 0 < one < five                                             # le financement du CFD court pendant l'horizon


@pytest.mark.parametrize("direction, role, p, factor", [
    (1, "risk", 0.75, 0.5), (-1, "risk", 0.75, 1.0), (-1, "risk", 0.25, 0.5), (1, "risk", 1.0, 0.0),
    (1, "haven", 0.75, 1.0), (-1, "haven", 0.75, 0.5), (1, "vol_only", 0.75, 0.75), (-1, "vol_only", 0.25, 1.0),
    (1, None, 0.9, 1.0), (1, "risk", None, 1.0)])
def test_the_regime_cuts_risky_buys_when_volatility_is_expected_to_rise(direction, role, p, factor):
    assert combo.regime_factor(direction, role, p) == pytest.approx(factor)


# --------------------------------------------------------------------------- décision d'une séance

def test_the_raw_ml_signal_alone_opens_at_full_size():
    signal = combo.check_signal({})
    assert combo.decide(Inputs(0.8), signal, 1) == (2, None) and combo.decide(Inputs(0.3), signal, 1) == (-2, None)
    assert combo.decide(Inputs(0.5), signal, 1) == (0, None) and combo.decide(Inputs(float("nan")), signal, 1) == (0, None)


@pytest.mark.parametrize("p, rl, decision", [
    (0.8, 1.0, 2), (0.8, 0.0, 0), (0.8, 0.4, 0), (0.2, 0.0, -2), (0.2, 1.0, 0), (0.8, None, 2), (0.2, None, -2)])
def test_the_rl_agent_must_agree_or_there_is_no_position(p, rl, decision):
    """Un agent du moteur 2 achète ou reste à plat : à plat est son avis baissier. Sans avis (pas de position récente), le ML passe seul."""
    assert combo.decide(Inputs(p, rl_position=rl), combo.check_signal({"rl": {"job_id": "j"}}), 1) == (decision, None)


def test_the_volatility_sizes_the_trade_and_the_expected_gain_must_pay_the_round_trip():
    signal = combo.check_signal({"vol": True, "cost_rt": 0.002, "persistence": 0.5, "median_conviction": 0.2})
    # conviction 0,6 ; gain attendu = 0,6 × 0,8 × 2 % × √(1 × 2) ≈ 1,36 % ≥ 0,2 % ; taille = 0,6 / 0,4 × (1 % / 2 %) = 0,75
    assert combo.decide(Inputs(0.8, sigma=0.02, sigma_ref=0.01), signal, 1) == (2, 0.75)
    assert combo.decide(Inputs(0.8, sigma=0.02, sigma_ref=0.01), {**signal, "cost_rt": 0.05}, 1) == (1, 0.75)       # renouveler seulement
    assert combo.decide(Inputs(0.8, sigma=0.02, sigma_ref=0.01), {**signal, "cost_rt": 0.01, "cost_multiple": 2.0}, 1)[0] == 1
    assert combo.decide(Inputs(0.8), signal, 1) == (1, None)                                                       # pas de volatilité : pas d'ouverture
    assert combo.decide(Inputs(0.51, sigma=0.02, sigma_ref=0.04), signal, 20)[1] == combo.MIN_WEIGHT                # taille plancher


def test_the_regime_shrinks_the_size_of_a_risky_buy_but_not_of_a_sale():
    signal = combo.check_signal({"vol": True, "cost_rt": 0.002, "persistence": 0.5, "median_conviction": 0.2,
                                 "regime": {"trial_id": 1, "role": "risk", "symbol": "^VIX"}})
    assert combo.decide(Inputs(0.8, regime_p=0.75, sigma=0.02, sigma_ref=0.01), signal, 1) == (2, 0.375)
    assert combo.decide(Inputs(0.2, regime_p=0.75, sigma=0.02, sigma_ref=0.01), signal, 1) == (-2, 0.75)


def test_a_weak_signal_never_opens_but_renews_or_closes_and_the_weight_rides_on_the_opening():
    days = pd.bdate_range("2026-01-05", periods=5)
    values = pd.Series([1.0, 1.0, 1.0, -1.0, -1.0], index=days)
    strong = dict(zip(days, [False, True, False, False, True], strict=True))
    weights = dict(zip(days, [0.9, 0.5, 0.4, 0.3, 0.25], strict=True))

    events = systematic.decide_directional(values, True, 3, strong=strong, weights=weights)

    assert [(e["signal"], e["action"], e["side"], e.get("weight")) for e in events] == [
        ("2026-01-06", "open", "long", 0.5),          # le 5 : faible, rien ; le 6 : fort, ouverture au poids du jour
        ("2026-01-08", "close", "long", None),        # le 7 : faible de même sens, renouvelée ; le 8 : faible opposé, fermée sans rouvrir
        ("2026-01-09", "open", "short", 0.25), ("2026-01-14", "close", "short", None)]   # puis l'échéance (3 séances)
    assert all("weight" not in e for e in systematic.decide_directional(values, True, 3))      # hors mode combo : format inchangé


# --------------------------------------------------------------------------- fonds et pilote automatique

def test_setup_makes_four_lab_funds_with_the_same_selection_and_one_ingredient_each(conn):
    rows = combo.setup(conn, today=TODAY)

    assert [(r["variant"], r["name"], r["created"]) for r in rows] == [
        ("reference", "Combiné Référence", True), ("rl", "Combiné ML + RL", True), ("vol", "Combiné ML + volatilité", True),
        ("full", "Combiné ML + RL + volatilité", True)]
    settings = {}
    for r in rows:
        s = store.get_strategy(conn, r["strategy_id"])
        assert (s["category"], s["wrapper"], s["initial_capital"], s["fee_flat"]) == ("lab", "CTO", 10_000_000, None)
        settings[r["variant"]] = store.get_autopilot(conn, r["strategy_id"])["settings"]
    assert {k: v["combo"] for k, v in settings.items()} == {
        "reference": None, "rl": {"rl": True, "vol": False, "cost_multiple": 1.0}, "vol": {"rl": False, "vol": True, "cost_multiple": 1.0},
        "full": {"rl": True, "vol": True, "cost_multiple": 1.0}}
    assert len({(v["tier"], v["max_models"], v["allow_short"], tuple(v["horizons"])) for v in settings.values()}) == 1   # même sélection
    assert [r["created"] for r in combo.setup(conn, today=TODAY)] == [False] * 4
    with pytest.raises(store.FundError, match="inconnu"):
        combo.setup(conn, today=TODAY, only=["magie"])


def test_the_vol_fund_trades_a_smaller_size_than_the_reference_and_freezes_its_past(conn, monkeypatch):
    _, mc, vix = _world(conn, monkeypatch)
    rows = {r["variant"]: r["strategy_id"] for r in combo.setup(conn, today=DAY0, only=["reference", "vol"], cost_multiple=0.0)}

    _cycle(conn, rows["reference"])
    report = _cycle(conn, rows["vol"])

    (rule,) = systematic.list_rules(conn, rows["vol"])
    signal = rule["config"]["signal"]
    assert signal["mode"] == "combo" and signal["vol"] is True and signal["cost_rt"] > 0
    assert signal["regime"] == {"trial_id": vix, "role": "risk", "symbol": "^VIX"}       # MC.PA : action, régime du VIX
    log = rule["config"]["combo_log"]
    assert list(log) == ["2026-01-15"] and log["2026-01-15"][0] == 2                    # la séance du 15 est passée : figée
    weight = log["2026-01-15"][1]
    assert combo.MIN_WEIGHT <= weight < 1.0 and report["placed"] >= 1
    ref, vol = _opened(conn, rows["reference"])["MC.PA"], _opened(conn, rows["vol"])["MC.PA"]
    assert vol / ref == pytest.approx(weight, rel=0.01)

    conn.execute("UPDATE prediction SET y_pred = ? WHERE trial_id = ? AND ts = '2026-01-15'", (DOWN, mc))   # un signal « révisé »
    conn.commit()
    assert combo.decisions(conn, rule["config"])["2026-01-15"] == [2, weight]              # le passé du fonds ne bouge pas
    assert combo.decisions(conn, {**rule["config"], "combo_log": {}})["2026-01-15"][0] < 0


def test_the_cost_filter_keeps_the_vol_fund_out_when_the_expected_gain_does_not_pay_the_round_trip(conn, monkeypatch):
    _world(conn, monkeypatch)                                         # cours factices presque sans volatilité : le gain attendu est minuscule
    rows = {r["variant"]: r["strategy_id"] for r in combo.setup(conn, today=DAY0, only=["reference", "vol"])}

    _cycle(conn, rows["reference"])
    _cycle(conn, rows["vol"])

    assert _opened(conn, rows["reference"]) and not _opened(conn, rows["vol"])
    (rule,) = systematic.list_rules(conn, rows["vol"])
    assert rule["config"]["combo_log"]["2026-01-15"][0] == 1                            # même sens, mais pas d'ouverture


def test_the_rl_fund_follows_its_agent_and_without_an_opinion_the_ml_signal_goes_alone(conn, monkeypatch):
    _world(conn, monkeypatch, vix=False)
    monkeypatch.setattr(combo, "rl_candidates", lambda c: {"MC.PA": {"job_id": "job_mc", "target": "MC.PA", "excess": 0.1, "verdict": "beats"}})
    rows = {r["variant"]: r["strategy_id"] for r in combo.setup(conn, today=DAY0, only=["rl"])}
    sid = rows["rl"]

    autopilot.run(conn, sid, DAY0)
    (rule,) = systematic.list_rules(conn, sid)
    assert rule["config"]["signal"]["rl"] == {"job_id": "job_mc", "target": "MC.PA"}
    assert combo.rl_jobs_needed(conn) == ["job_mc"]
    conn.execute("INSERT INTO rl_live_position (job_id, ts, position) VALUES ('job_mc', '2026-01-15', 0.0)")   # l'agent reste à plat
    conn.commit()
    autopilot.run(conn, sid, TODAY)

    assert not _opened(conn, sid)                                     # désaccord : pas de position
    assert systematic.list_rules(conn, sid)[0]["config"]["combo_log"]["2026-01-15"] == [0, None]


def test_the_nightly_cycle_runs_the_rl_funds_last_and_only_vol_funds_read_the_volatility_index(conn, monkeypatch):
    _world(conn, monkeypatch)
    rows = {r["variant"]: r["strategy_id"] for r in combo.setup(conn, today=TODAY, only=["reference", "rl", "vol"])}
    seen = []
    monkeypatch.setattr(autopilot, "run", lambda c, sid, today=None: seen.append(sid) or {})

    autopilot.run_all(conn, TODAY, needs_rl=False)
    first = list(seen)
    autopilot.run_all(conn, TODAY, needs_rl=True)

    assert sorted(first) == sorted([rows["reference"], rows["vol"]]) and seen[len(first):] == [rows["rl"]]
    assert combo.auxiliary_cells(conn) == {("^VIX", 1)}
    autopilot.disable(conn, rows["vol"])
    assert combo.auxiliary_cells(conn) == set()


def test_a_new_rl_agent_or_regime_model_starts_a_new_rule_instead_of_rewriting_the_old_one():
    base = {"trial_id": 1, "allow_short": True, "instrument": {"kind": "cfd", "symbol": "^GSPC"}, "hold": {"mode": "horizon", "sessions": 1},
            "signal": combo.check_signal({"rl": {"job_id": "a"}})}
    other = {**base, "signal": combo.check_signal({"rl": {"job_id": "b"}})}
    direction = {**base, "signal": {"mode": "direction", "min_confidence": 0.0}}

    assert autopilot._signature(base) != autopilot._signature(other) != autopilot._signature(direction)
    assert autopilot._signature(base) == autopilot._signature({**base, "signal": combo.check_signal({"rl": {"job_id": "a"}})})


# --------------------------------------------------------------------------- commande

def test_the_combo_setup_command_previews_then_creates(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect()
    _world(conn, monkeypatch)
    conn.close()
    from patrick.cli import app

    runner = CliRunner()
    preview = runner.invoke(app, ["fund", "combo-setup", "--today", "2026-01-16"])
    made = runner.invoke(app, ["fund", "combo-setup", "--today", "2026-01-16", "--create", "--only", "vol", "--cost-multiple", "2"])
    refused = runner.invoke(app, ["fund", "combo-setup", "--only", "magie"])

    assert preview.exit_code == 0 and "Aperçu (rien n'est écrit)" in preview.output and "Combiné ML + RL + volatilité" in preview.output
    assert made.exit_code == 0 and "Combiné ML + volatilité" in made.output and "créé" in made.output
    assert refused.exit_code == 1 and "Refusé" in refused.output
    conn = trackdb.connect()
    try:
        (strategy,) = store.list_strategies(conn)
        assert store.get_autopilot(conn, strategy["strategy_id"])["settings"]["combo"]["cost_multiple"] == 2.0
    finally:
        conn.close()
