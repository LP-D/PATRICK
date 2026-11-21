"""Laboratoire de stratégies général (`patrick/strategylab/`, `/strategies`) : indicateurs, règles, moteur de backtest (délai d'exécution, frais,
sélection, sorties de risque, paire, événements), métriques, robustesse, modèles, étude complète, historique et routes."""
from __future__ import annotations

import io
import json
import math
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.strategylab import (
    backtest,
    data,
    events,
    indicators,
    jobs,
    metrics,
    robustness,
    rules,
    service,
    templates,
)
from patrick.tracking import db
from patrick.webapp.app import app


# ------------------------------------------------------------------ cours synthétiques
def _ohlc(seed: int, drift=0.0003, vol=0.012, start="2004-01-01", end="2024-12-31") -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, len(idx))))
    opn = np.concatenate([[100.0], close[:-1]]) * (1 + rng.normal(0, 0.002, len(idx)))
    return pd.DataFrame({"open": opn, "high": np.maximum(opn, close) * 1.003, "low": np.minimum(opn, close) * 0.997, "close": close, "volume": 1e6}, index=idx)


def _line(values, start="2020-01-01", tail=30) -> pd.DataFrame:
    """Cours imposé séance par séance (ouverture = clôture précédente), prolongé de `tail` séances au dernier cours (un marché a au moins 30 séances)."""
    close = np.concatenate([np.asarray(values, dtype=float), np.full(tail, float(values[-1]))])
    idx = pd.bdate_range(start, periods=len(close))
    opn = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": opn, "high": np.maximum(opn, close), "low": np.minimum(opn, close), "close": close, "volume": np.nan}, index=idx)


def _market(frames: dict, traded: list[str], aux: list[str] | None = None, pair=False) -> indicators.Market:
    m, missing, _ = data.build_market(traded, aux or [], data.PriceBook(frames, allow_yahoo=False), pair=pair)
    assert not missing
    return m


ZERO = backtest.Costs(commission=0, min_fee=0, fixed=0, slippage=0, borrow=0, cash_rate=0, financing_spread=0)


# ------------------------------------------------------------------ indicateurs et règles
def test_indicators_are_causal_and_exact():
    px = _line(list(range(100, 160)))
    m = _market({"A": px}, ["A"])
    sma = indicators.compute(m, {"ind": "sma", "n": 5})["A"]
    assert math.isnan(sma.iloc[3]) and sma.iloc[4] == pytest.approx(102.0)
    high = indicators.compute(m, {"ind": "high", "n": 3})["A"]
    assert high.iloc[5] == pytest.approx(px["high"].iloc[2:5].max())        # la séance du jour est exclue du canal
    ret = indicators.compute(m, {"ind": "ret", "n": 2})["A"]
    assert ret.iloc[10] == pytest.approx(110 / 108 - 1)
    rsi = indicators.compute(m, {"ind": "rsi", "n": 14})["A"]
    assert rsi.dropna().iloc[-1] == pytest.approx(100.0)                     # que des hausses
    shifted = indicators.compute(m, {"ind": "price", "shift": 2, "mult": 2})["A"]
    assert shifted.iloc[5] == pytest.approx(2 * px["close"].iloc[3])
    with pytest.raises(indicators.IndicatorError):
        indicators.compute(m, {"ind": "sma", "n": 1})


def test_calendar_and_event_indicators():
    px = _ohlc(1, start="2024-01-01", end="2024-03-29")
    m = _market({"A": px}, ["A"])
    dom = indicators.compute(m, {"ind": "dom"})["A"]
    dte = indicators.compute(m, {"ind": "dte"})["A"]
    assert dom.loc["2024-02-01"] == 1 and dte.loc["2024-01-31"] == 0 and dte.loc["2024-01-30"] == 1
    m.events = {"A": [pd.Timestamp("2024-02-15")]}
    ev = indicators.compute(m, {"ind": "event"})["A"]
    assert ev.loc["2024-02-15"] == 0 and ev.loc["2024-02-13"] == -2 and ev.loc["2024-02-19"] == 2


def test_rules_combine_and_treat_missing_values_as_false():
    m = _market({"A": _line(list(range(100, 130)))}, ["A"])
    grp = {"all": [{"left": {"ind": "price"}, "op": ">", "right": {"ind": "sma", "n": 10}}, {"left": {"ind": "dom"}, "op": "<=", "right": {"value": 31}}]}
    out = rules.group(m, grp)["A"]
    assert not out.iloc[:9].any() and out.iloc[9:30].all() and not out.iloc[40:].any()     # cours plat ensuite : rejoint par sa moyenne
    cross = rules.group(m, {"all": [{"left": {"ind": "price"}, "op": "crosses_above", "right": {"value": 110.5}}]})["A"]
    assert cross.sum() == 1 and cross.idxmax() == m.index[11]
    between = rules.group(m, {"any": [{"left": {"ind": "price"}, "op": "between", "low": {"value": 105}, "high": {"value": 107}}]})["A"]
    assert between.sum() == 3
    with pytest.raises(rules.RuleError):
        rules.group(m, {"all": [{"left": {"ind": "price"}, "op": "~", "right": {"value": 1}}]})


# ------------------------------------------------------------------ moteur
def test_buy_and_hold_without_costs_follows_the_price_exactly():
    px = _ohlc(3)
    m = _market({"A": px}, ["A"])
    res = backtest.run(m, backtest.Strategy(rebalance="never"), ZERO, pd.Timestamp("2010-01-04"), pd.Timestamp("2020-12-31"), 10_000, lag=0)
    eq = res.daily["equity"]
    expected = 10_000 * px["close"].loc[eq.index] / px["close"].loc[eq.index[0]]
    assert np.allclose(eq.to_numpy(), expected.to_numpy(), rtol=1e-9)
    assert res.costs_total == 0 and len(res.trades) == 1 and res.trades[0]["reason"] == "fin de période"


def test_signal_is_executed_one_session_later_and_costs_are_charged():
    values = [100] * 5 + [110] * 3 + [121] * 3 + [121] * 5
    m = _market({"A": _line(values)}, ["A"])
    strat = backtest.Strategy(long_entry={"all": [{"left": {"ind": "price"}, "op": ">", "right": {"value": 105}}]}, rebalance="never")
    res = backtest.run(m, strat, ZERO, m.index[0], m.index[-1], 1000, lag=1)
    # signal vrai à la clôture de la séance 5 (110), achat à la clôture de la séance 6 (110) : seule la hausse 110 -> 121 est gagnée
    assert res.daily["equity"].iloc[-1] == pytest.approx(1100.0)
    assert res.trades[0]["entry"] == m.index[6].date().isoformat() and res.trades[0]["entry_price"] == pytest.approx(110)
    paid = backtest.Costs(commission=0.01, min_fee=0, fixed=2.0, slippage=0.0, borrow=0, cash_rate=0, financing_spread=0)
    res2 = backtest.run(m, strat, paid, m.index[0], m.index[-1], 1000, lag=1)
    assert res2.costs_total == pytest.approx(1000 * 0.01 + 2.0)
    assert res2.daily["equity"].iloc[-1] == pytest.approx(1000 * 1.1 - 12)        # frais prélevés sur les liquidités, position à 100 % de la valeur


def test_execution_at_the_open_splits_the_session():
    values = [100, 100, 100, 100, 110, 110, 110]
    px = _line(values)
    px["open"] = [100, 100, 100, 100, 104, 108, 110] + [110] * 30
    m = _market({"A": px}, ["A"])
    strat = backtest.Strategy(long_entry={"all": [{"left": {"ind": "dom"}, "op": ">=", "right": {"value": 4}}]}, rebalance="never")
    res = backtest.run(m, strat, ZERO, m.index[0], m.index[-1], 1000, lag=1, at="open")
    # signal le 4e jour du mois (séance 3), achat à l'ouverture de la séance 4 à 104, clôture finale 110
    assert res.trades[0]["entry_price"] == pytest.approx(104)
    assert res.daily["equity"].iloc[-1] == pytest.approx(1000 * 110 / 104)
    with pytest.raises(backtest.BacktestError):
        backtest.run(m, strat, ZERO, m.index[0], m.index[-1], 1000, lag=0, at="open")


def test_stop_loss_exits_and_waits_for_a_fresh_signal():
    values = [100] * 3 + [100, 90, 85, 84, 83] + [100] * 5
    m = _market({"A": _line(values)}, ["A"])
    strat = backtest.Strategy(rebalance="never", risk={"stop_loss": 0.08})
    res = backtest.run(m, strat, ZERO, m.index[0], m.index[-1], 1000, lag=0)
    first = res.trades[0]
    assert first["reason"] == "stop" and first["exit"] == m.index[4].date().isoformat()
    assert len(res.trades) == 1                       # « toujours investi » ne lâche jamais : pas de ré-entrée après le stop


def test_selection_keeps_the_top_n_and_rotates():
    frames = {"UP": _line(np.linspace(100, 200, 300), tail=0), "FLAT": _line(np.full(300, 100.0), tail=0), "DOWN": _line(np.linspace(100, 50, 300), tail=0)}
    m = _market(frames, ["UP", "FLAT", "DOWN"])
    strat = backtest.Strategy(selection={"rank_by": {"ind": "ret", "n": 20}, "order": "desc", "top": 1, "bottom": 1}, decision="monthly", rebalance="monthly")
    res = backtest.run(m, strat, ZERO, m.index[30], m.index[-1], 1000, lag=1)
    w = res.weights.iloc[-1]
    assert w["UP"] > 0.4 and w["DOWN"] < -0.4 and abs(w["FLAT"]) < 1e-9
    assert res.daily["equity"].iloc[-1] > 1000


def test_pair_trades_the_ratio_and_events_place_the_window():
    a, b = _ohlc(5), _ohlc(6)
    m = _market({"A": a, "B": b}, ["A", "B"], pair=True)
    assert m.traded == ["A/B"]
    ratio = (a["close"] / b["close"])
    assert m.close["A/B"].iloc[10] == pytest.approx(100 * ratio.iloc[10] / ratio.iloc[0])
    m2 = _market({"A": _ohlc(7, start="2020-01-01", end="2020-12-31")}, ["A"])
    data.attach_events(m2, "dates", ["A"], dates_text="2020-03-16\n2020-06-15")
    strat = backtest.Strategy(long_entry={"all": [{"left": {"ind": "event"}, "op": "between", "low": {"value": -2}, "high": {"value": 1}}]}, rebalance="never")
    res = backtest.run(m2, strat, ZERO, m2.index[0], m2.index[-1], 1000, lag=0)
    assert len(res.trades) == 2 and all(t["days"] == 4 for t in res.trades)       # de J-2 à la clôture de J+2, où la condition devient fausse


def test_fixed_weights_and_inverse_vol_sizing():
    calm, wild = _ohlc(8, vol=0.005), _ohlc(9, vol=0.03)
    m = _market({"CALM": calm, "WILD": wild}, ["CALM", "WILD"])
    fixed = backtest.Strategy(rebalance="monthly", sizing={"method": "fixed", "weights": {"CALM": 60, "WILD": 40}})
    res = backtest.run(m, fixed, ZERO, pd.Timestamp("2010-01-04"), pd.Timestamp("2010-12-31"), 1000, lag=1)
    assert res.weights.iloc[1]["CALM"] == pytest.approx(0.6, abs=0.02)
    inv = backtest.Strategy(rebalance="monthly", sizing={"method": "inverse_vol", "n": 60, "allocation": "active"})
    res2 = backtest.run(m, inv, ZERO, pd.Timestamp("2010-01-04"), pd.Timestamp("2010-12-31"), 1000, lag=1)
    assert res2.weights.iloc[1]["CALM"] > 0.7


# ------------------------------------------------------------------ métriques et robustesse
def test_metrics_match_hand_computation():
    idx = pd.bdate_range("2020-01-01", periods=253)
    eq = pd.Series(100 * 1.0004 ** np.arange(253), index=idx)
    eq.iloc[100:110] = eq.iloc[99] * 0.9
    ret = eq.pct_change().fillna(0.0)
    core = metrics.core(ret, eq)
    assert core["max_dd"] == pytest.approx(-0.1, abs=1e-9)
    years = (idx[-1] - idx[0]).days / 365.25
    assert core["cagr"] == pytest.approx((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)
    dd = metrics.drawdown_periods(eq, top=1)
    assert dd[0]["depth"] == pytest.approx(-0.1) and dd[0]["recovered"]
    stats = metrics.trade_stats([{"return": 0.1, "pnl": 100, "side": 1, "days": 5}, {"return": -0.05, "pnl": -50, "side": 1, "days": 3}])
    assert stats["win_rate"] == 0.5 and stats["profit_factor"] == pytest.approx(2.0)


def test_random_timing_does_not_reward_luckless_signals_and_spots_real_timing():
    px = _ohlc(11)
    m = _market({"A": px}, ["A"])
    r = m.returns()["A"]
    weights = pd.DataFrame({"A": (np.random.default_rng(1).random(len(r)) > 0.5).astype(float)}, index=r.index)
    noise = robustness.random_timing(weights, m.returns(), n=200)
    assert noise["p_value"] > 0.05
    clairvoyant = pd.DataFrame({"A": (r.shift(-1) > 0).astype(float)}, index=r.index)        # connaît le lendemain : doit écraser le hasard
    perfect = robustness.random_timing(clairvoyant, m.returns(), n=200)
    assert perfect["p_value"] < 0.01


def test_cost_sensitivity_breakeven_and_walk_forward_use_only_the_past():
    idx = pd.bdate_range("2015-01-01", periods=1500)
    gross = pd.Series(0.0004, index=idx) + np.random.default_rng(2).normal(0, 0.0002, len(idx))
    cost = pd.Series(0.0001, index=idx)
    cs = robustness.cost_sensitivity(gross, cost, 0.0)
    assert 3.0 < cs["breakeven_sharpe"] < 5.0                  # 0,0004 de rendement brut quotidien mangé à 4 x 0,0001
    rng = np.random.default_rng(4)
    good_then_bad = pd.Series(np.where(idx.year < 2018, 0.001, -0.001), index=idx) + rng.normal(0, 0.001, len(idx))
    steady = pd.Series(0.0003, index=idx) + rng.normal(0, 0.001, len(idx))
    wf = robustness.walk_forward(pd.DataFrame({"a": good_then_bad, "b": steady}), ["a", "b"], min_train_years=2)
    assert wf["chosen"][0]["label"] == "a"                     # 2017 jugé sur 2015-2016 seulement : « a » paraissait meilleur
    assert any(c["label"] == "b" for c in wf["chosen"][2:])    # puis on bascule quand le passé le dit, jamais avant


def test_deflated_sharpe_penalises_many_trials():
    r = np.random.default_rng(5).normal(0.0004, 0.01, 2500)
    psr = robustness.psr(r)
    few = robustness.deflated(r, np.array([0.0, 0.01]))
    many = robustness.deflated(r, np.random.default_rng(6).normal(0.0, 0.02, 200))
    assert few["dsr"] > many["dsr"] and psr >= few["dsr"]


# ------------------------------------------------------------------ modèles et étude complète
def test_templates_resolve_validate_and_compile():
    with pytest.raises(templates.TemplateError):
        templates.resolve("sma_cross", {"fast": 200, "slow": 100})
    with pytest.raises(templates.TemplateError):
        templates.resolve("sma_cross", {"unknown": 1})
    built = templates.compile_template("rsi", {"trend": 0})
    assert built["long_entry"]["all"][0]["left"] == {"ind": "rsi", "n": 2} and len(built["long_entry"]["all"]) == 1
    assert {t["key"] for t in templates.catalog()} >= {"buy_hold", "sma_cross", "xs_momentum", "pairs", "event", "custom"}


def _book():
    frames = {s: _ohlc(i, drift=0.0001 * (i + 1)) for i, s in enumerate(["AAA", "BBB", "CCC", "^VIX"])}
    return data.PriceBook(frames, allow_yahoo=False)


def test_full_study_is_json_ready_and_deterministic():
    spec = {"symbols": ["AAA", "BBB", "CCC"], "start": "2008-01-01", "end": "2022-12-31", "oos_start": "2018-01-01", "template": "sma_cross",
            "params": {"fast": 40, "slow": 160}, "costs": {"commission": 0.1, "slippage": 5}, "robustness": {"grid": {"x": {"param": "fast", "min": 20, "max": 80, "steps": 3}}}}
    a = service.run(spec, _book())
    b = service.run(spec, _book())
    json.dumps(a, allow_nan=False)
    assert a["summary"] == b["summary"] and a["robustness"]["random"]["p_value"] == b["robustness"]["random"]["p_value"]
    assert a["verdict"]["state"] in ("robust", "fragile", "none") and len(a["robustness"]["grid"]["cells"]) == 3
    assert a["robustness"]["split"]["out_of_sample"]["years"] > 4 and a["summary"]["costs_total"] > 0
    assert a["series"]["benchmark"] and a["benchmark"]["label"].startswith("équipondéré")


def test_custom_rules_with_a_regime_filter_load_the_auxiliary_instrument():
    spec = {"symbols": ["AAA"], "start": "2010-01-01", "end": "2015-12-31", "template": "custom", "benchmark": "BBB",
            "rules": {"long_entry": {"all": [{"left": {"ind": "price", "symbol": "^VIX"}, "op": "<", "right": {"value": 1e9}}]}}}
    res = service.run(spec, _book())
    assert "^VIX" in res["aux"] and res["summary"]["time_invested"] > 0.95 and res["benchmark"]["label"] == "BBB"
    with pytest.raises(service.StudyError):
        service.normalise({"symbols": ["AAA"], "start": "2020-01-01", "end": "2010-01-01"})
    with pytest.raises(service.StudyError):
        service.normalise({"symbols": ["AAA"], "costs": {"commission": 50}})


# ------------------------------------------------------------------ historique des études
def test_runs_are_saved_listed_pinned_and_pruned(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(jobs, "KEEP_RUNS", 2)
    res = service.run({"symbols": ["AAA"], "start": "2015-01-01", "end": "2016-12-31", "template": "buy_hold"}, _book())
    first = jobs.save_run(res)
    jobs.update_run(first, pinned=True, name="Gardée")
    for _ in range(3):
        jobs.save_run(res)
    listed = jobs.list_runs()
    assert len(listed) == 3 and any(r["id"] == first and r["pinned"] and r["name"] == "Gardée" for r in listed)
    assert jobs.load_run(first)["spec"]["template"] == "buy_hold" and jobs.load_run("../x") is None
    jobs.delete_run(first)
    assert all(r["id"] != first for r in jobs.list_runs())


def test_only_one_study_runs_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path))
    res = service.run({"symbols": ["AAA"], "start": "2015-01-01", "end": "2016-12-31", "template": "buy_hold"}, _book())
    first = jobs.start(lambda progress: time.sleep(0.5) or res)
    assert jobs.start(lambda progress: res).id == first.id
    for _ in range(240):
        if jobs.get(first.id).status != "running":
            break
        time.sleep(0.25)
    assert jobs.get(first.id).status == "done" and jobs.load_run(jobs.get(first.id).run_id) is not None


# ------------------------------------------------------------------ fichiers
def test_events_from_any_table_format():
    csv = b"Ticker;Date\nAAPL;31/01/2024\nmsft;2024-02-15\n;2024-03-01\n"
    ev = events.parse_events_any("ev.csv", csv)
    assert list(ev["symbol"]) == ["AAPL", "MSFT"] and ev.attrs["dropped"] == 1


# ------------------------------------------------------------------ routes
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    return TestClient(app)


def _price_file() -> bytes:
    frames = {s: _ohlc(20 + i, start="2012-01-01", end="2020-12-31") for i, s in enumerate(["AAA", "BBB"])}
    wide = pd.DataFrame({s: f["close"] for s, f in frames.items()})
    out = io.StringIO()
    wide.rename_axis("Date").reset_index().assign(Date=lambda d: d["Date"].dt.strftime("%d/%m/%Y")).to_csv(out, sep=";", decimal=",", index=False)
    return out.getvalue().encode()


def _wait(client, job_id):
    for _ in range(240):
        status = client.get(f"/api/strategies/jobs/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.25)
    raise AssertionError("l'étude ne se termine pas")


def test_page_catalog_and_compile(client):
    html = client.get("/strategies").text
    assert 'id="st-app"' in html and "strategies.js" in html and "st-i18n" in html
    cat = client.get("/api/strategies/catalog").json()
    assert "sma" in cat["indicators"] and any(t["key"] == "donchian" for t in cat["templates"]) and cat["cost_presets"]["none"]["commission"] == 0
    built = client.post("/api/strategies/compile", json={"template": "price_sma", "params": {"n": 150}}).json()
    assert built["long_entry"]["all"][0]["right"] == {"ind": "sma", "n": 150}
    assert client.post("/api/strategies/compile", json={"template": "nope"}).status_code == 400


def test_inspect_and_run_with_an_uploaded_file(client):
    files = {"prices_file": ("cours.csv", _price_file(), "text/csv")}
    ins = client.post("/api/strategies/inspect", files=files).json()
    assert {s["symbol"] for s in ins["symbols"]} == {"AAA", "BBB"}
    spec = {"symbols": ["AAA", "BBB"], "start": "2013-01-01", "end": "2020-12-31", "template": "xs_momentum", "params": {"top": 1, "n": 126, "skip": 0},
            "allow_yahoo": False}
    job = client.post("/api/strategies/run", data={"spec": json.dumps(spec)}, files={"prices_file": ("cours.csv", _price_file(), "text/csv")}).json()
    status = _wait(client, job["id"])
    assert status["status"] == "done", status
    detail = client.get(f"/api/strategies/runs/{status['run_id']}").json()
    assert detail["universe"][0]["source"] == "fichier" and detail["trade_stats"]["count"] > 0
    runs = client.get("/api/strategies/runs").json()
    assert runs[0]["id"] == status["run_id"]
    assert client.post(f"/api/strategies/runs/{status['run_id']}", json={"pinned": True}).json()["pinned"] is True
    assert client.delete(f"/api/strategies/runs/{status['run_id']}").json() == {"ok": True}


def test_run_rejects_bad_input_before_starting(client):
    bad = client.post("/api/strategies/run", data={"spec": "{not json"})
    assert bad.status_code == 400
    missing = client.post("/api/strategies/run", data={"spec": json.dumps({"symbols": ["AAA"], "template": "event", "events": {"source": "file"}})})
    assert missing.status_code == 400 and "fichier d'événements" in missing.json()["detail"]
    assert client.get("/api/strategies/jobs/inconnu").status_code == 404
    assert client.get("/api/strategies/runs/zzz").status_code == 404
