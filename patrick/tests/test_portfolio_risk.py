"""Risque et simulation de portefeuille (`patrick/analysis/portfolio_risk.py`) : VaR/ES, contributions, crises, marche avant sans fuite, écarts."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from patrick.analysis import portfolio_risk as pr
from patrick.tracking import db as trackdb
from patrick.wealth import ledger


def _prices(n=900, seed=3, start="2019-01-01", drifts=(0.0004, 0.0003, 0.0002, 0.0001), vols=(0.012, 0.01, 0.008, 0.005)):
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 1, n)
    idx = pd.bdate_range(start, periods=n)
    out = {}
    for i, (d, v) in enumerate(zip(drifts, vols, strict=True)):
        eps = rng.normal(0, 1, n)
        r = d + v * (0.5 * common + math.sqrt(0.75) * eps) if i < 2 else d + v * eps
        out[f"A{i}"] = pd.Series(100 * np.cumprod(1 + r), index=idx)
    return out


def _provider(series):
    return lambda s: series.get(s)


def _holdings(weights: dict[str, float], cash: float = 0.0, dat: float = 0.0, total: float = 10_000.0):
    rows = [{"symbol": s, "value": w * total, "weight": w, "is_term_deposit": False} for s, w in weights.items()]
    if dat:
        rows.append({"symbol": "DAT:x", "value": dat * total, "weight": dat, "is_term_deposit": True})
    return {"source": "real", "total": total, "cash": cash * total, "rows": rows, "accounts": []}


def test_var_es_orders_and_horizon_scaling():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0004, 0.01, 4000)
    v = pr.var_es(r, 0.95)
    assert v["es_hist"] >= v["hist"] > 0 and v["es_gauss"] >= v["gauss"] > 0
    assert abs(v["hist"] - v["gauss"]) < 0.002 and abs(v["cf"] - v["gauss"]) < 0.002            # échantillon gaussien : les trois s'accordent
    v10 = pr.var_es(r, 0.95, horizon=10)
    assert v10["hist"] == pytest.approx(v["hist"] * math.sqrt(10))
    assert pr.var_es(r[:10])["hist"] is None
    assert pr.var_es(r, 0.99)["hist"] > v["hist"]


def test_cornish_fisher_sees_fat_left_tail_that_gaussian_misses():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0005, 0.007, 5000)
    r[rng.choice(5000, 60, replace=False)] -= 0.05                                                   # krachs rares
    v = pr.var_es(r, 0.99)
    assert v["skew"] < 0 and v["kurt"] > 1
    assert v["cf"] > v["gauss"] and v["es_hist"] > v["es_gauss"]


def test_kupiec_accepts_a_calibrated_var_and_rejects_a_too_small_one():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.01, 3000)
    good = pr.kupiec(r, pr.var_es(r, 0.95)["hist"], 0.95)
    assert good["p"] > 0.05 and good["breaches"] == pytest.approx(good["expected"], rel=0.1)
    bad = pr.kupiec(r, 0.005, 0.95)
    assert bad["p"] < 0.001
    assert pr.kupiec(r[:50], 0.01)["p"] is None


def test_risk_contributions_sum_to_portfolio_volatility_and_to_one():
    cov = pd.DataFrame([[0.0004, 0.0001, 0.0], [0.0001, 0.0009, 0.0], [0.0, 0.0, 0.0001]], index=list("abc"), columns=list("abc"))
    w = {"a": 0.5, "b": 0.3, "c": 0.2}
    rows = pr.risk_contributions(w, cov)
    wv = np.array([0.5, 0.3, 0.2])
    vol = math.sqrt(wv @ cov.to_numpy() @ wv * pr.TRADING_DAYS)
    assert sum(r["contribution"] for r in rows) == pytest.approx(vol) and sum(r["share"] for r in rows) == pytest.approx(1.0)
    eq = pd.DataFrame(np.diag([0.0004, 0.0004]), index=["x", "y"], columns=["x", "y"])
    assert [r["share"] for r in pr.risk_contributions({"x": 0.5, "y": 0.5}, eq)] == pytest.approx([0.5, 0.5])
    assert pr.risk_contributions({"x": 0.0, "y": 0.0}, eq) == []


def test_stress_window_uses_only_assets_listed_over_the_whole_window():
    idx = pd.bdate_range("2019-06-03", "2020-12-31")
    full = pd.Series(np.where(idx < pd.Timestamp("2020-03-23"), 100.0, 60.0), index=idx)
    late = pd.Series(50.0, index=pd.bdate_range("2020-10-01", "2020-12-31"))
    out = {w["key"]: w for w in pr.stress_windows({"F": full, "L": late}, {"F": 0.6, "L": 0.2})}
    covid = out["covid"]
    assert covid["sufficient"] and covid["return_risky"] == pytest.approx(-0.40) and covid["coverage"] == pytest.approx(0.75)
    assert covid["return_total"] == pytest.approx(-0.40 * 0.8)
    assert out["gfc"]["sufficient"] is False and out["gfc"]["return_risky"] is None            # avant le début de l'historique


def test_risk_report_is_finite_json_and_consistent():
    series = _prices()
    rep = pr.risk_report(_holdings({"A0": 0.3, "A1": 0.2, "A2": 0.2}, cash=0.2, dat=0.1), _provider(series), lookback=500)
    assert rep["available"] and rep["covered_weight"] == pytest.approx(0.7) and rep["risky_share"] == pytest.approx(0.7)
    text = json.dumps(rep, allow_nan=False)                                                          # aucune valeur non finie
    assert "NaN" not in text
    assert sum(c["share"] for c in rep["contributions"]) == pytest.approx(1.0)
    assert len(rep["dates"]) == len(rep["equity"]) == len(rep["drawdown"]) and min(rep["drawdown"]) <= 0
    assert rep["n_days"] == 500 and rep["volatility"] == pytest.approx(sum(c["contribution"] for c in rep["contributions"]))
    assert [r["level"] for r in rep["var"]] == [0.95, 0.95, 0.99, 0.99] and rep["var"][0]["kupiec"] is not None and rep["var"][1]["kupiec"] is None
    assert len(rep["correlation"]["values"]) == 3 and all(abs(rep["correlation"]["values"][i][i] - 1) < 1e-9 for i in range(3))
    assert {s["shock"] for s in rep["shocks"]} == set(pr.SHOCKS) and rep["shocks"][0]["loss_total"] == pytest.approx(-0.10 * 0.7)


def test_risk_report_reports_missing_and_short_assets_instead_of_dropping_them_silently():
    series = _prices()
    series["SHORT"] = series["A0"].iloc[-30:]
    rep = pr.risk_report(_holdings({"A0": 0.4, "A1": 0.3, "SHORT": 0.1, "NODATA": 0.1}), _provider(series))
    reasons = {e["symbol"]: e["reason"] for e in rep["excluded"]}
    assert reasons == {"SHORT": "short_history", "NODATA": "no_data"} and rep["covered_weight"] == pytest.approx(0.7)
    empty = pr.risk_report(_holdings({}), _provider(series))
    assert empty["available"] is False


def test_backtest_has_no_lookahead_and_attribution_matches_gross_return():
    series = _prices()
    df = pr.returns_frame(series)
    base = pr.backtest_method(df, "hrp", lookback=252, rebalance_days=21, cost_bps=10)
    altered = df.copy()
    altered.iloc[-100:] = altered.iloc[-100:] * 3 - 0.01                                             # le futur lointain change
    other = pr.backtest_method(altered, "hrp", lookback=252, rebalance_days=21, cost_bps=10)
    cut = len(df) - 252 - 100
    assert np.allclose(base["net"][:cut], other["net"][:cut]) and not np.allclose(base["net"][cut:], other["net"][cut:])
    assert base["contrib"].sum() == pytest.approx(np.nansum(base["gross"]))
    assert base["turnover"][0] == pytest.approx(1.0)


def test_backtest_costs_reduce_return_and_zero_cost_equals_gross():
    df = pr.returns_frame(_prices())
    free = pr.backtest_method(df, "inv_vol", cost_bps=0.0)
    paid = pr.backtest_method(df, "inv_vol", cost_bps=50.0)
    assert np.allclose(free["net"], free["gross"]) and paid["equity"][-1] < free["equity"][-1]
    assert np.nansum(paid["gross"] - paid["net"]) == pytest.approx(0.005 * paid["turnover"].sum())


def test_target_weights_are_long_only_and_sum_to_one():
    df = pr.returns_frame(_prices()).iloc[-300:]
    for m in pr.METHODS:
        w = pr.target_weights(m, df, {"A0": 0.5, "A1": 0.2, "A2": 0.2, "A3": 0.1})
        assert w.sum() == pytest.approx(1.0) and (w >= 0).all() and list(w.index) == list(df.columns), m
    inv = pr.target_weights("inv_vol", df)
    assert inv["A3"] > inv["A0"]                                                                     # la moins volatile pèse le plus
    with pytest.raises(ValueError):
        pr.target_weights("magic", df)


def test_backtest_output_and_guards():
    series = _prices()
    out = pr.backtest(_holdings({"A0": 0.3, "A1": 0.3, "A2": 0.2, "A3": 0.2}), _provider(series), n_boot=40)
    assert out["available"] and [m["method"] for m in out["methods"]] == list(pr.METHODS)
    json.dumps(out, allow_nan=False)
    m = out["methods"][0]
    assert len(m["equity"]) == len(out["dates"]) and m["sharpe_ci"]["lo"] <= m["sharpe_ci"]["point"] <= m["sharpe_ci"]["hi"]
    assert {a["symbol"] for a in m["attribution"]} == set(out["assets"])
    assert sum(m["last_weights"].values()) == pytest.approx(1.0)
    one = pr.backtest(_holdings({"A0": 1.0}), _provider(series))
    assert one["available"] is False and one["reason"] == "need_two_assets"
    short = pr.backtest(_holdings({"A0": 0.5, "A1": 0.5}), _provider({k: v.iloc[-200:] for k, v in series.items()}))
    assert short["available"] is False and short["reason"] == "short_common_window"


def test_rebalance_gaps_are_arithmetic_and_flag_the_band():
    series = _prices()
    h = _holdings({"A0": 0.5, "A1": 0.2, "A2": 0.1, "A3": 0.1}, cash=0.1)
    out = pr.rebalance_gaps(h, _provider(series), method="equal", tolerance=0.05, cost_bps=20)
    assert out["available"] and sum(r["gap"] for r in out["rows"]) == pytest.approx(0.0, abs=1e-9)
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["A0"]["target"] == pytest.approx(0.225) and by["A0"]["gap"] == pytest.approx(-0.275) and by["A0"]["outside_band"]
    assert by["A3"]["gap"] == pytest.approx(0.125) and by["A3"]["amount"] == pytest.approx(0.125 * 10_000)
    assert out["cost_estimate"] == pytest.approx(out["turnover_amount"] * 0.002) and out["n_outside"] == 3 and not by["A1"]["outside_band"]
    assert out["rows"][0]["symbol"] == "A0"                                             # tri par écart décroissant
    tight = pr.rebalance_gaps(_holdings({"A0": 0.25, "A1": 0.25, "A2": 0.25, "A3": 0.25}), _provider(series), "equal", tolerance=0.02)
    assert tight["n_outside"] == 0 and tight["turnover_amount"] == pytest.approx(0.0, abs=1e-6)


def test_resolve_holdings_consolidates_real_accounts_and_keeps_cash_and_term_deposits(tmp_path):
    conn = trackdb.connect(str(tmp_path / "w.db"))
    series = _prices()
    price = float(series["A0"].iloc[-1])
    real = ledger.create_account(conn, "PEA test", "PEA", "real")
    ledger.add_movement(conn, real, {"ts": "2026-01-05", "kind": "deposit", "amount": 10_000})
    ledger.add_movement(conn, real, {"ts": "2026-01-06", "kind": "buy", "symbol": "A0", "quantity": 20, "price": price})
    ledger.add_movement(conn, real, {"ts": "2026-01-07", "kind": "term_deposit", "amount": 1_000, "rate": 0.03, "maturity": "2027-01-07"})
    fic = ledger.create_account(conn, "Fictif", "CTO", "fictive")
    ledger.add_movement(conn, fic, {"ts": "2026-01-05", "kind": "deposit", "amount": 5_000})
    h = pr.resolve_holdings(conn, _provider(series), "real")
    assert {r["symbol"] for r in h["rows"]} >= {"A0"} and sum(r["weight"] for r in h["rows"]) + h["cash"] / h["total"] == pytest.approx(1.0)
    assert any(r["is_term_deposit"] for r in h["rows"]) and set(pr.risky_weights(h)) == {"A0"}
    assert pr.resolve_holdings(conn, _provider(series), "fictive")["total"] == pytest.approx(5_000)
    assert pr.resolve_holdings(conn, _provider(series), real)["source"] == real and len(h["accounts"]) == 2
    assert pr.resolve_holdings(conn, _provider(series), "acc_unknown")["rows"] == []
    assert h["warnings"] == []


def test_negative_cash_does_not_produce_weights_above_one(tmp_path):
    conn = trackdb.connect(str(tmp_path / "w.db"))
    series = _prices()
    acc = ledger.create_account(conn, "Incomplet", "CTO", "real")
    ledger.add_movement(conn, acc, {"ts": "2026-01-05", "kind": "deposit", "amount": 1_000})
    ledger.add_movement(conn, acc, {"ts": "2026-01-06", "kind": "buy", "symbol": "A0", "quantity": 100, "price": float(series["A0"].iloc[-1])})
    h = pr.resolve_holdings(conn, _provider(series), "real")
    assert h["cash"] < 0 and h["warnings"] == ["negative_cash"]
    assert sum(r["weight"] for r in h["rows"]) == pytest.approx(1.0) and pr.risk_report(h, _provider(series))["warnings"] == ["negative_cash"]
