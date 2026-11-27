"""Valuation, performance and risk of an account (or a set of accounts).

Prices come from a `PriceProvider` (a callable symbol -> pd.Series of
closes, or None). The web layer passes one that reads the local data lake
first and only then the network; tests pass a dict. A symbol without any
price keeps its last transaction price, and says so (`price_source`). A
bond is worth nominal x clean price + accrued interest; without quotes its
clean price follows the constant yield of the last trade (wealth/bonds.py).

Performance
-----------
- **TWR** (time-weighted): daily chain-linking, external flows (deposits,
  withdrawals) at the END of the day: r_t = (V_t - F_t) / V_{t-1} - 1.
  Valuation is at the close and a deposit is invested at (about) the
  close, so the flow earns nothing on its day; the start-of-day
  convention V_t / (V_{t-1} + F_t) - 1 credited it with the day's return
  and biased TWR (caught by test_twr_is_neutral_to_flows_while_xirr_is_not).
  Except for the lots bought that day: their P&L from the trade to the
  close (P_t, fees and accrued interest included) accrues on the capital
  AFTER the day's flows. With X_t = V_t - F_t - P_t (the old portfolio at
  the close), 1 + r_t = X_t / V_{t-1} x V_t / (X_t + F_t) -- the same as
  above when P_t = 0, but 25 EUR of fees to invest a 5 000 EUR deposit
  weigh on the 5 400 EUR invested that day (-0.5 %), not on the 400 EUR
  held the day before (-6 %).
  Neutral to the size and timing of flows -- the number to compare with an
  index.
- **XIRR** (money-weighted): the annual rate zeroing the net present value
  of the investor's flows (deposit = outflow, withdrawal = inflow, final
  value = inflow). Includes the timing of deposits.
- **Benchmark**: the index's own return over the same period AND a
  "same flows" replica -- every deposit/withdrawal invested in / taken out
  of the index on the same day. The replica's final value answers "what if
  everything had gone into the index", with no timing advantage either way.

Risk
----
Ex-ante volatility sqrt(w' S w) of the current holdings, S = Ledoit-Wolf
covariance of their daily returns (tracking/covariance.py). A term deposit
(DAT) has no price history: zero variance and zero covariance by
construction -- it dilutes risk, it is not dropped from the weights.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from patrick.core.clock import utc_today
from patrick.wealth import bonds
from patrick.wealth.ledger import (
    EXTERNAL_FLOW_KINDS,
    LedgerState,
    Position,
    apply_movement,
    replay,
)

PriceProvider = Callable[[str], "pd.Series | None"]
TRADING_DAYS = 252


def dict_price_provider(prices: dict[str, pd.Series]) -> PriceProvider:
    return lambda symbol: prices.get(symbol)


def term_deposit_value(principal: float, rate: float, start: str, maturity: str, on) -> float:
    """Simple interest pro rata temporis (365-day basis), frozen at maturity."""
    start_ts, mat_ts, on_ts = pd.Timestamp(start), pd.Timestamp(maturity), pd.Timestamp(on)
    days = (min(on_ts, mat_ts) - start_ts).days
    return principal * (1.0 + float(rate) * max(days, 0) / 365.0)


def _price_at(series: pd.Series | None, day: pd.Timestamp) -> float | None:
    if series is None or series.empty:
        return None
    s = series[series.index <= day]
    return float(s.iloc[-1]) if len(s) else None


def _quote(series: pd.Series | None, day, pos: Position) -> float | None:
    """Last close up to `day`, unless the position traded after it (a close
    missing on the trade day: DCAM.PA on 2026-11-26): the trade price is
    then the fresher information -- None, the caller uses it."""
    if series is None or series.empty:
        return None
    s = series[series.index <= day]
    if not len(s) or (pos.last_trade_ts and s.index[-1] < pd.Timestamp(pos.last_trade_ts)):
        return None
    return float(s.iloc[-1])


_YIELD_MEMO: dict[tuple, float | None] = {}


def _trade_yield(pos: Position) -> float | None:
    """Yield of a bond's last trade (memoised: one solve per trade, not per
    day of the valuation loop). None without a coupon."""
    key = (pos.rate, pos.maturity, pos.last_trade_ts, pos.last_trade_price)
    if key not in _YIELD_MEMO:
        try:
            _YIELD_MEMO[key] = bonds.yield_to_maturity(pos.rate, pos.maturity, pos.last_trade_ts,
                                                      pos.last_trade_price) if pos.rate is not None else None
        except bonds.BondError:
            _YIELD_MEMO[key] = None
    return _YIELD_MEMO[key]


def bond_quote(pos: Position, series: pd.Series | None, day) -> tuple[float, str]:
    """(clean price as a fraction of nominal, its source) of a bond on `day`."""
    px = _quote(series, day, pos)
    if px is not None:
        return bonds.quote_as_fraction(px), "cotation"
    if pd.Timestamp(day) >= pd.Timestamp(pos.maturity):
        return 1.0, "remboursé au pair"
    y = _trade_yield(pos)
    if y is None:
        return pos.last_trade_price or 0.0, "prix de transaction"
    trade_day = pd.Timestamp(pos.last_trade_ts)
    return bonds.clean_price(pos.rate, pos.maturity, max(pd.Timestamp(day), trade_day), y), "rendement constant"


def position_value(pos: Position, series: pd.Series | None, day) -> dict:
    """{"value", "price", "source", "accrued", "ytm"} of an open position on
    `day`: term deposit at simple interest, bond at clean price + accrued
    interest, anything else at the close (last trade price failing that)."""
    if pos.is_term_deposit:
        value = term_deposit_value(pos.cost, pos.rate or 0.0, pos.start, pos.maturity, day)
        return {"value": value, "price": value, "source": f"DAT {pos.rate:.2%} \u2192 {pos.maturity}",
                "accrued": None, "ytm": None}
    if pos.is_bond:
        price, source = bond_quote(pos, series, day)
        accrued = bonds.accrued_interest(pos.quantity, pos.rate, pos.maturity, day)
        ytm = None
        if pos.rate is not None and pd.Timestamp(day) < pd.Timestamp(pos.maturity):
            try:
                ytm = bonds.yield_to_maturity(pos.rate, pos.maturity, day, price)
            except bonds.BondError:
                ytm = None
        return {"value": pos.quantity * price + accrued, "price": price, "source": source, "accrued": accrued,
                "ytm": ytm}
    px = _quote(series, day, pos)
    price, source = (px, "cotation") if px is not None else (pos.last_trade_price, "prix de transaction")
    return {"value": pos.quantity * (price or 0.0), "price": price, "source": source, "accrued": None, "ytm": None}


def _unit_value(pos: Position, series: pd.Series | None, day) -> float:
    """Value of one unit of the position on `day` (a bond: clean price +
    accrued interest per unit of nominal)."""
    if pos.is_bond:
        price, _ = bond_quote(pos, series, day)
        return price + bonds.accrued_interest(1.0, pos.rate, pos.maturity, day)
    px = _quote(series, day, pos)
    return px if px is not None else (pos.last_trade_price or 0.0)


def valuation_series(movements: list[dict], prices: PriceProvider, start=None, end=None) -> pd.DataFrame:
    """Daily (business days) value of the account: cash, holdings, total,
    external flow of the day, P&L of the lots bought that day from their
    trade to the close (`new_pnl`, see TWR). Positions are replayed day by
    day from the movements (incremental, one pass)."""
    if not movements:
        return pd.DataFrame(columns=["cash", "holdings", "value", "flow", "new_pnl"])
    mvs = sorted(movements, key=lambda m: (m["ts"], m.get("movement_id") or 0))
    first = pd.Timestamp(start or mvs[0]["ts"])
    last = pd.Timestamp(end or utc_today())
    days = pd.bdate_range(first, last)
    # Movements on a weekend count on the next business day.
    by_day: dict[pd.Timestamp, list[dict]] = {}
    for mv in mvs:
        d = pd.Timestamp(mv["ts"])
        pos = days.searchsorted(d)
        if pos >= len(days):
            continue
        by_day.setdefault(days[pos], []).append(mv)

    series_cache: dict[str, pd.Series | None] = {}

    def series_of(symbol: str) -> pd.Series | None:
        if symbol not in series_cache:
            s = prices(symbol)
            series_cache[symbol] = s.dropna().sort_index() if s is not None else None
        return series_cache[symbol]

    state = LedgerState()
    rows = []
    for day in days:
        todays = by_day.get(day, [])
        for mv in todays:
            apply_movement(state, mv)
        flow = sum(float(m["amount"]) for m in todays if m["kind"] in EXTERNAL_FLOW_KINDS)
        new_pnl = sum(float(m["quantity"]) * _unit_value(state.positions[m["symbol"]], series_of(m["symbol"]), day)
                      + float(m["amount"]) for m in todays if m["kind"] == "buy")
        holdings = 0.0
        for sym, pos in state.positions.items():
            if pos.quantity <= 1e-9:
                continue
            if pos.is_term_deposit:
                holdings += term_deposit_value(pos.cost, pos.rate or 0.0, pos.start, pos.maturity, day)
            else:
                holdings += pos.quantity * _unit_value(pos, series_of(sym), day)
        rows.append((day, state.cash, holdings, state.cash + holdings, flow, new_pnl))
    return pd.DataFrame(rows, columns=["date", "cash", "holdings", "value", "flow", "new_pnl"]).set_index("date")


def time_weighted_returns(val: pd.DataFrame) -> pd.Series:
    """Daily TWR returns, end-of-day flows, the day's new lots' P&L on the
    capital after the flows (module docstring); days whose starting capital
    V_{t-1} is not positive are skipped (no return on zero capital)."""
    v = val["value"].to_numpy(float)
    f = val["flow"].to_numpy(float)
    p = val["new_pnl"].to_numpy(float) if "new_pnl" in val else np.zeros(len(v))
    out = np.full(len(v), np.nan)
    for t in range(1, len(v)):
        if v[t - 1] <= 1e-9:
            continue
        old = v[t] - f[t] - p[t]
        if abs(p[t]) > 1e-9 and old + f[t] > 1e-9:
            out[t] = old / v[t - 1] * v[t] / (old + f[t]) - 1.0
        else:
            out[t] = (v[t] - f[t]) / v[t - 1] - 1.0
    return pd.Series(out, index=val.index).dropna()


def xirr(flows: list[tuple], lo: float = -0.9999, hi: float = 10.0) -> float | None:
    """Annual money-weighted rate; `flows` = [(date, amount)] from the
    investor's side (outflow < 0). None if not bracketed (all flows the
    same sign, or no root in [lo, hi])."""
    if len(flows) < 2:
        return None
    t0 = min(pd.Timestamp(d) for d, _ in flows)
    years = np.array([(pd.Timestamp(d) - t0).days / 365.0 for d, _ in flows])
    amounts = np.array([float(a) for _, a in flows])
    if not (amounts > 0).any() or not (amounts < 0).any():
        return None

    def npv(r: float) -> float:
        return float(np.sum(amounts / (1.0 + r) ** years))

    try:
        f_lo, f_hi = npv(lo), npv(hi)
        if f_lo * f_hi > 0:
            return None
        return float(brentq(npv, lo, hi, xtol=1e-10, maxiter=200))
    except (ValueError, OverflowError, FloatingPointError):
        return None


def _annualize(total: float, n_days: int) -> float | None:
    if n_days <= 0 or total <= -1:
        return None
    return (1.0 + total) ** (TRADING_DAYS / n_days) - 1.0


def benchmark_replica(val: pd.DataFrame, bench: pd.Series) -> pd.Series:
    """Value of a portfolio receiving the SAME external flows, invested in
    the benchmark on the same days (units bought/sold at that day's close)."""
    px = bench.dropna().sort_index().reindex(val.index, method="ffill")
    units, out = 0.0, []
    for day, flow in val["flow"].items():
        p = px.get(day)
        if p is None or not np.isfinite(p) or p <= 0:
            out.append(np.nan)
            continue
        units += flow / p
        out.append(units * p)
    return pd.Series(out, index=val.index)


def performance_summary(movements: list[dict], prices: PriceProvider, benchmark: str | None = None,
                        end=None) -> dict:
    val = valuation_series(movements, prices, end=end)
    if val.empty:
        return {"n_days": 0, "start": None, "end": None, "value": 0.0, "cash": 0.0, "net_deposits": 0.0,
                "twr": None, "twr_annualized": None, "xirr": None, "volatility": None, "max_drawdown": None,
                "benchmark": benchmark, "benchmark_return": None, "benchmark_replica_value": None,
                "excess_vs_benchmark": None, "valuation": val, "twr_index": pd.Series(dtype=float)}
    rets = time_weighted_returns(val)
    twr_total = float(np.prod(1.0 + rets.to_numpy()) - 1.0) if len(rets) else None
    idx = (1.0 + rets).cumprod() if len(rets) else pd.Series(dtype=float)
    max_dd = float((idx / idx.cummax() - 1.0).min()) if len(idx) else None
    vol = float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(rets) > 2 else None

    flows = [(m["ts"], -float(m["amount"])) for m in movements if m["kind"] in EXTERNAL_FLOW_KINDS]
    final_value = float(val["value"].iloc[-1])
    flows.append((val.index[-1], final_value))
    money_weighted = xirr(flows)

    out = {
        "n_days": len(val), "start": val.index[0].date().isoformat(), "end": val.index[-1].date().isoformat(),
        "value": final_value, "cash": float(val["cash"].iloc[-1]),
        "net_deposits": float(val["flow"].sum()),
        "twr": twr_total, "twr_annualized": _annualize(twr_total, len(rets)) if twr_total is not None else None,
        "xirr": money_weighted, "volatility": vol, "max_drawdown": max_dd,
        "benchmark": benchmark, "benchmark_return": None, "benchmark_replica_value": None,
        "excess_vs_benchmark": None, "valuation": val, "twr_index": idx,
    }
    if benchmark:
        bench = prices(benchmark)
        if bench is not None and len(bench.dropna()):
            b = bench.dropna().sort_index()
            b_start, b_end = _price_at(b, val.index[0]), _price_at(b, val.index[-1])
            if b_start and b_end:
                out["benchmark_return"] = b_end / b_start - 1.0
                if twr_total is not None:
                    out["excess_vs_benchmark"] = twr_total - out["benchmark_return"]
            replica = benchmark_replica(val, b)
            out["benchmark_replica"] = replica
            if len(replica.dropna()):
                out["benchmark_replica_value"] = float(replica.dropna().iloc[-1])
    return out


def holdings_table(movements: list[dict], prices: PriceProvider, as_of=None, account: dict | None = None) -> dict:
    """Current positions with PRU, last price (and its source), value,
    weight, latent P&L (bonds: coupon, maturity, accrued interest, yield);
    plus cash, total and the ledger's warnings."""
    day = pd.Timestamp(as_of or utc_today())
    state = replay(movements, as_of=day, account=account)
    rows = []
    for sym, pos in sorted(state.positions.items()):
        v = position_value(pos, None if pos.is_term_deposit else prices(sym), day)
        value = v["value"]
        rows.append({"symbol": sym, "quantity": pos.quantity, "pru": pos.pru, "price": v["price"],
                     "price_source": v["source"], "value": value, "cost": pos.cost,
                     "latent_pnl": value - pos.cost,
                     "latent_pnl_pct": (value - pos.cost) / pos.cost if pos.cost > 0 else None,
                     "realized_pnl": pos.realized,
                     "is_term_deposit": pos.is_term_deposit, "is_bond": pos.is_bond,
                     "rate": pos.rate if pos.is_bond else None, "maturity": pos.maturity if pos.is_bond else None,
                     "accrued": v["accrued"], "ytm": v["ytm"]})
    total = state.cash + sum(r["value"] for r in rows)
    for r in rows:
        r["weight"] = r["value"] / total if total else None
    return {"rows": rows, "cash": state.cash, "total": total, "warnings": state.warnings,
            "deposits": state.deposits, "withdrawals": state.withdrawals, "income": state.income,
            "fees": state.fees}


def ex_ante_risk(holdings: dict, prices: PriceProvider, lookback: int = 252, min_obs: int = 60,
                 proxies: dict[str, tuple[str, float | None]] | None = None) -> dict:
    """Annualised ex-ante volatility of the current holdings (cash and term
    deposits: zero variance). Ledoit-Wolf covariance on the risky part.

    An asset without enough history (D.A.T.E, listed 2026-09-25) is
    backfilled from its declared proxy (`config.equity_universe.
    history_proxies`, `tracking.covariance.backfill_with_proxy`) and listed
    in `proxied` with the scale and whether it is estimated or a prior;
    without a proxy it is excluded and listed in `excluded` -- never
    silently dropped."""
    from patrick.config.equity_universe import history_proxies
    from patrick.tracking.covariance import (
        backfill_with_proxy,
        point_in_time_covariance,
    )

    proxies = history_proxies() if proxies is None else proxies

    total = holdings["total"]
    if not total or total <= 0:
        return {"volatility": None, "covered_weight": 0.0, "excluded": [], "shrinkage": None, "proxied": []}
    risky = {r["symbol"]: r["value"] / total for r in holdings["rows"] if not r["is_term_deposit"] and r["value"]}
    series = {s: prices(s) for s in risky}
    usable = {s: v.dropna() for s, v in series.items() if v is not None and len(v.dropna()) > min_obs}
    proxied = []
    for s in sorted(set(risky) - set(usable)):
        if s not in proxies:
            continue
        proxy_symbol, prior = proxies[s]
        proxy_series = prices(proxy_symbol)
        if proxy_series is None or len(proxy_series.dropna()) <= min_obs:
            continue
        usable[s], info = backfill_with_proxy(series.get(s), proxy_series, prior_multiplier=prior)
        proxied.append({"symbol": s, "proxy": proxy_symbol, **info})
    excluded = sorted(set(risky) - set(usable))
    if not usable:
        return {"volatility": None if risky else 0.0, "covered_weight": 0.0 if risky else 1.0,
                "excluded": excluded, "shrinkage": None, "proxied": proxied}
    symbols = list(usable)
    if len(symbols) == 1:
        s = symbols[0]
        var = float(usable[s].pct_change().dropna().iloc[-lookback:].var(ddof=1))
        cov = pd.DataFrame([[var]], index=symbols, columns=symbols)
        shrinkage = None
    else:
        as_of = min(v.index.max() for v in usable.values())
        cov = point_in_time_covariance(usable, as_of=as_of, lookback=lookback, min_obs=min_obs,
                                       estimator="ledoit_wolf")
        shrinkage = cov.attrs.get("shrinkage")
    w = np.array([risky[s] for s in symbols])
    vol = float(np.sqrt(max(w @ cov.to_numpy() @ w, 0.0) * TRADING_DAYS))
    covered = float(sum(risky[s] for s in symbols) + (1.0 - sum(risky.values())))
    return {"volatility": vol, "covered_weight": covered, "excluded": excluded, "shrinkage": shrinkage,
            "proxied": proxied}
