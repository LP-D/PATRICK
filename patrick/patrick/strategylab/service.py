"""Une étude complète du laboratoire de stratégies : de la description JSON envoyée par la page au résultat JSON affiché.

`normalise(spec)` valide et complète la description (dates, frais en %, exécution, modèle ou règles libres, robustesse) ;
`run(spec, book, progress)` charge les cours, compile la stratégie, lance le backtest, l'indice de référence, les métriques, les épreuves de
robustesse et la grille de sensibilité. Tout est déterministe (graines fixes) : relancer la même étude donne le même résultat.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from patrick.strategylab import (
    backtest,
    data,
    indicators,
    metrics,
    robustness,
    rules,
    templates,
)

VERSION = 2
MAX_GRID = 144
MAX_TRADES_SHOWN = 4000
RISK_KEYS = ("stop_loss", "take_profit", "trailing", "max_days")
SIZING_KEYS = ("method", "n", "target", "max_weight", "leverage", "allocation")
COST_DEFAULTS = {"commission": 0.10, "min_fee": 0.0, "fixed": 0.0, "slippage": 5.0, "borrow": 1.0, "cash_rate": 2.0, "financing_spread": 1.0}
COST_BOUNDS = {"commission": (0, 5), "min_fee": (0, 100), "fixed": (0, 100), "slippage": (0, 500), "borrow": (0, 50), "cash_rate": (-5, 20),
               "financing_spread": (0, 20)}


class StudyError(ValueError):
    """Description d'étude invalide : message en français."""


def _num(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _num(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_num(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return f if math.isfinite(f) else None
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.date().isoformat()
    return x


def _date(value, name: str, default: str | None = None) -> pd.Timestamp | None:
    if value in (None, ""):
        return pd.Timestamp(default) if default else None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise StudyError(f"Date invalide pour {name}.") from exc
    if not 1950 <= ts.year <= 2100:
        raise StudyError(f"Date hors limites pour {name}.")
    return ts.normalize()


def _pct(value, name: str, lo: float, hi: float) -> float | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise StudyError(f"{name} : nombre attendu.") from exc
    if not lo <= v <= hi:
        raise StudyError(f"{name} doit être compris entre {lo} et {hi}.")
    return v


def normalise(spec: dict) -> dict:
    """Description complète et validée (copie)."""
    s = copy.deepcopy(spec or {})
    s["name"] = str(s.get("name") or "Étude").strip()[:80]
    s["symbols"] = data.parse_symbols(s.get("symbols") or [])
    if not s["symbols"]:
        raise StudyError("Choisissez au moins un instrument.")
    if len(s["symbols"]) > data.MAX_TRADED:
        raise StudyError(f"Au plus {data.MAX_TRADED} instruments.")
    start = _date(s.get("start"), "le début", "2005-01-01")
    end = _date(s.get("end"), "la fin") or pd.Timestamp(datetime.now(UTC).date())
    if end <= start:
        raise StudyError("La fin doit être postérieure au début.")
    oos = _date(s.get("oos_start"), "la coupure hors échantillon")
    if oos is not None and not start < oos < end:
        raise StudyError("La coupure hors échantillon doit tomber entre le début et la fin.")
    s.update({"start": start.date().isoformat(), "end": end.date().isoformat(), "oos_start": oos.date().isoformat() if oos is not None else None})
    try:
        s["capital"] = float(s.get("capital") or 10_000)
    except (TypeError, ValueError) as exc:
        raise StudyError("Capital invalide.") from exc
    if not 100 <= s["capital"] <= 1e10:
        raise StudyError("Le capital doit être compris entre 100 et 10 milliards.")
    costs = {**COST_DEFAULTS, **{k: v for k, v in (s.get("costs") or {}).items() if v not in (None, "")}}
    for k, (lo, hi) in COST_BOUNDS.items():
        try:
            costs[k] = float(costs[k])
        except (TypeError, ValueError) as exc:
            raise StudyError(f"Frais : {k} invalide.") from exc
        if not lo <= costs[k] <= hi:
            raise StudyError(f"Frais : {k} doit être compris entre {lo} et {hi}.")
    s["costs"] = {k: costs[k] for k in COST_DEFAULTS}
    ex = s.get("execution") or {}
    s["execution"] = {"lag": int(ex.get("lag", 1)), "at": ex.get("at", "close") if ex.get("at") in ("close", "open") else "close"}
    s["template"] = s.get("template") or "custom"
    if s["template"] not in templates.TEMPLATES:
        raise StudyError("Modèle inconnu.")
    try:
        s["params"] = templates.resolve(s["template"], s.get("params") or {})
    except templates.TemplateError as exc:
        raise StudyError(str(exc)) from exc
    risk = s.get("risk") or {}
    s["risk"] = {"stop_loss": _pct(risk.get("stop_loss"), "Stop de perte (%)", 0.1, 95), "take_profit": _pct(risk.get("take_profit"), "Objectif de gain (%)", 0.1, 1000),
                 "trailing": _pct(risk.get("trailing"), "Stop suiveur (%)", 0.1, 95), "max_days": _pct(risk.get("max_days"), "Durée maximale (séances)", 1, 2520)}
    bench = str(s.get("benchmark") or "").strip().upper()
    s["benchmark"] = bench or ("__EQUAL__" if len(s["symbols"]) > 1 else s["symbols"][0])
    if s["benchmark"] not in ("__EQUAL__", "__CASH__") and not data.SYMBOL_RE.match(s["benchmark"]):
        raise StudyError("Indice de référence invalide.")
    ev = s.get("events") or {}
    s["events"] = {"source": ev.get("source") or "earnings", "dates": str(ev.get("dates") or "")[:20_000], "quarters": int(ev.get("quarters") or 40)}
    rob = s.get("robustness") or {}
    s["robustness"] = {"random": bool(rob.get("random", True)), "bootstrap": bool(rob.get("bootstrap", True)), "grid": rob.get("grid") or None}
    s["allow_yahoo"] = bool(s.get("allow_yahoo", True))
    return s


def compile_strategy(s: dict) -> tuple[backtest.Strategy, dict]:
    """La stratégie du moteur et sa forme lisible (règles affichées par la page). Les règles libres (`rules`) remplacent celles du modèle."""
    built = templates.compile_template(s["template"], s["params"])
    custom = s.get("rules") or None
    if custom:
        for key in ("long_entry", "long_exit", "short_entry", "short_exit", "selection", "overlay"):
            if key in custom:
                built[key] = custom[key] or None
        for key in ("decision", "rebalance"):
            if custom.get(key):
                built[key] = custom[key]
        if custom.get("sizing"):
            built["sizing"] = {**(built.get("sizing") or {}), **custom["sizing"]}
    sizing = {"method": "equal", "allocation": "sleeves", **(built.get("sizing") or {})}
    for k in SIZING_KEYS:
        if (s.get("sizing") or {}).get(k) not in (None, ""):
            sizing[k] = s["sizing"][k]
    if sizing.get("method") == "fixed":
        sizing["weights"] = {str(k).upper(): v for k, v in (s.get("weights") or {}).items()}
    if s.get("decision"):
        built["decision"] = s["decision"]
    if s.get("rebalance"):
        built["rebalance"] = s["rebalance"]
    risk = {k: v for k, v in s["risk"].items() if v}
    risk = {k: (v / 100 if k != "max_days" else v) for k, v in risk.items()}
    strat = backtest.Strategy(long_entry=built.get("long_entry"), long_exit=built.get("long_exit"), short_entry=built.get("short_entry"),
                              short_exit=built.get("short_exit"), selection=built.get("selection"), sizing=sizing, overlay=built.get("overlay"),
                              risk=risk, decision=built.get("decision", "daily"), rebalance=built.get("rebalance", "monthly"))
    readable = {k: v for k, v in {"long_entry": strat.long_entry, "long_exit": strat.long_exit, "short_entry": strat.short_entry, "short_exit": strat.short_exit,
                                   "selection": strat.selection, "sizing": {k: v for k, v in sizing.items() if not k.startswith("_")}, "overlay": strat.overlay,
                                   "risk": risk, "decision": strat.decision, "rebalance": strat.rebalance}.items()}
    return strat, {**readable, "pair": bool(built.get("pair")), "events": bool(built.get("events"))}


def costs_of(s: dict) -> backtest.Costs:
    c = s["costs"]
    return backtest.Costs(commission=c["commission"] / 100, min_fee=c["min_fee"], fixed=c["fixed"], slippage=c["slippage"] / 10_000,
                          borrow=c["borrow"] / 100, cash_rate=c["cash_rate"] / 100, financing_spread=c["financing_spread"] / 100)


def aux_symbols(strat: backtest.Strategy, benchmark: str) -> list[str]:
    out = []
    for grp in (strat.long_entry, strat.long_exit, strat.short_entry, strat.short_exit):
        for op in rules.operands(grp):
            if op.get("symbol"):
                out.append(str(op["symbol"]).upper())
    if strat.selection and isinstance(strat.selection.get("rank_by"), dict) and strat.selection["rank_by"].get("symbol"):
        out.append(str(strat.selection["rank_by"]["symbol"]).upper())
    if benchmark not in ("__EQUAL__", "__CASH__"):
        out.append(benchmark)
    return list(dict.fromkeys(out))


def _equity_from(ret: pd.Series, capital: float) -> pd.Series:
    eq = capital * (1 + ret).cumprod()
    return eq


def _benchmark(m: indicators.Market, s: dict, costs: backtest.Costs, start, end, capital: float) -> tuple[pd.Series | None, str]:
    bench = s["benchmark"]
    if bench == "__CASH__":
        return None, "liquidités"
    if bench == "__EQUAL__":
        strat = backtest.Strategy(rebalance="monthly", sizing={"method": "equal", "allocation": "active"})
        res = backtest.run(m, strat, costs, start, end, capital, lag=1)
        return res.daily["equity"], "équipondéré (rééquilibré chaque mois)"
    if bench not in m.close.columns:
        return None, bench
    px = m.close[bench].ffill(limit=5)
    px = px[(px.index >= pd.Timestamp(start)) & (px.index <= pd.Timestamp(end))].dropna()
    if len(px) < 20:
        return None, bench
    return capital * px / px.iloc[0], bench


def run_once(m: indicators.Market, s: dict, strat: backtest.Strategy, costs: backtest.Costs) -> backtest.Result:
    return backtest.run(m, strat, costs, pd.Timestamp(s["start"]), pd.Timestamp(s["end"]), s["capital"], lag=s["execution"]["lag"], at=s["execution"]["at"])


def _grid_axes(s: dict) -> list[tuple[str, list]]:
    grid = s["robustness"].get("grid")
    if not grid:
        return []
    meta = templates.TEMPLATES[s["template"]]["params"]
    axes = []
    for axis in ("x", "y"):
        a = grid.get(axis)
        if not a or not a.get("param"):
            continue
        name = a["param"]
        if name not in meta or meta[name]["type"] not in ("int", "float"):
            raise StudyError(f"Grille : le paramètre {name} n'est pas numérique.")
        try:
            lo, hi, n = float(a["min"]), float(a["max"]), int(a.get("steps", 6))
        except (KeyError, TypeError, ValueError) as exc:
            raise StudyError("Grille : bornes invalides.") from exc
        if not 2 <= n <= 12 or hi <= lo:
            raise StudyError("Grille : entre 2 et 12 valeurs, maximum supérieur au minimum.")
        values = list(np.linspace(lo, hi, n))
        if meta[name]["type"] == "int":
            values = sorted({round(v) for v in values})
        axes.append((name, values))
    if len(axes) == 2 and axes[0][0] == axes[1][0]:
        raise StudyError("Grille : deux paramètres différents.")
    total = int(np.prod([len(v) for _, v in axes])) if axes else 0
    if total > MAX_GRID:
        raise StudyError(f"Grille : au plus {MAX_GRID} combinaisons.")
    return axes


def run_grid(m: indicators.Market, s: dict, costs: backtest.Costs, axes: list[tuple[str, list]], say) -> dict:
    combos = [[]]
    for name, values in axes:
        combos = [c + [(name, v)] for c in combos for v in values]
    returns, cells, labels = {}, [], []
    cash = s["costs"]["cash_rate"] / 100
    for i, combo in enumerate(combos):
        say(0.55 + 0.30 * i / len(combos), f"Grille {i + 1}/{len(combos)}")
        variant = copy.deepcopy(s)
        variant["params"] = {**s["params"], **dict(combo)}
        label = ", ".join(f"{k} = {v}" for k, v in combo)
        try:
            variant["params"] = templates.resolve(s["template"], variant["params"])
            strat, _ = compile_strategy(variant)
            res = run_once(m, variant, strat, costs)
        except (templates.TemplateError, backtest.BacktestError, rules.RuleError, StudyError) as exc:
            cells.append({"params": dict(combo), "error": str(exc)})
            continue
        ret = res.daily["ret"]
        returns[label] = ret
        labels.append(label)
        core = metrics.core(ret, res.daily["equity"], cash)
        cells.append({"params": dict(combo), "sharpe": core["sharpe"], "cagr": core["cagr"], "max_dd": core["max_dd"],
                      "trades": len(res.trades)})
    frame = pd.DataFrame(returns).fillna(0.0) if returns else pd.DataFrame()
    daily_sr = np.array([(frame[c].mean() / frame[c].std()) if frame[c].std() > 0 else np.nan for c in frame.columns]) if len(frame.columns) else np.array([])
    wf = robustness.walk_forward(frame, list(frame.columns)) if len(frame.columns) >= 2 else None
    valid = [c for c in cells if c.get("sharpe") is not None and c["sharpe"] == c["sharpe"]]
    plateau = None
    if valid:
        best = max(c["sharpe"] for c in valid)
        plateau = float(np.mean([c["sharpe"] >= 0.5 * best for c in valid])) if best > 0 else 0.0
    pbo = robustness.pbo_of(frame) if len(frame.columns) >= 2 else None
    return {"axes": [{"param": n, "values": v} for n, v in axes], "cells": cells, "walk_forward": wf, "plateau": plateau, "pbo": pbo,
            "_daily_sharpes": daily_sr}


def run(spec: dict, book: data.PriceBook, progress: Callable[[float, str], None] | None = None, file_events: pd.DataFrame | None = None,
        earnings_fetch: Callable | None = None) -> dict:
    say = progress or (lambda _f, _m: None)
    s = normalise(spec)
    strat, readable = compile_strategy(s)
    costs = costs_of(s)
    aux = aux_symbols(strat, s["benchmark"])
    needed = book.downloads_needed(list(dict.fromkeys(s["symbols"] + aux)))
    if len(needed) > data.MAX_DOWNLOADS:
        raise StudyError(f"{len(needed)} instruments à télécharger, au plus {data.MAX_DOWNLOADS}.")
    m, missing, notes = data.build_market(s["symbols"], aux, book, end=pd.Timestamp(s["end"]), pair=readable["pair"],
                                          benchmark=None if s["benchmark"].startswith("__") else s["benchmark"], progress=say)
    if readable["events"]:
        say(0.32, "Événements")
        notes += data.attach_events(m, s["events"]["source"], m.traded, file_events, s["events"]["dates"], s["events"]["quarters"], fetch=earnings_fetch)
    first_price = min(m.close[c].first_valid_index() for c in m.traded)
    if pd.Timestamp(s["start"]) < first_price:
        notes.append(f"premiers cours le {first_price.date().isoformat()} : l'étude commence à cette date")
        s["start"] = first_price.date().isoformat()
        if s["oos_start"] and pd.Timestamp(s["oos_start"]) <= first_price:
            s["oos_start"] = None
    say(0.36, "Backtest")
    try:
        res = run_once(m, s, strat, costs)
    except (rules.RuleError, indicators.IndicatorError) as exc:
        raise StudyError(str(exc)) from exc
    notes += res.notes
    daily = res.daily
    cash = costs.cash_rate
    core = metrics.core(daily["ret"], daily["equity"], cash)
    trades_stats = metrics.trade_stats(res.trades)
    say(0.42, "Indice de référence")
    bench_eq, bench_label = _benchmark(m, s, costs, pd.Timestamp(s["start"]), pd.Timestamp(s["end"]), s["capital"])
    bench_core, vs, bench_ret = None, {}, None
    if bench_eq is not None:
        bench_eq = bench_eq.reindex(daily.index).ffill()
        bench_ret = bench_eq.pct_change().fillna(0.0)
        bench_core = metrics.core(bench_ret, bench_eq, cash)
        vs = metrics.versus(daily["ret"], bench_ret, cash)
    say(0.46, "Robustesse")
    split = robustness.split(daily["ret"], s["oos_start"], cash) if s["oos_start"] else None
    returns = m.returns()[m.traded]
    timed = bool(strat.long_entry or strat.short_entry or strat.selection)      # toujours investi : le calendrier n'a rien à prouver
    rand = robustness.random_timing(res.weights, returns, n=300) if s["robustness"]["random"] and timed else None
    cost_frac = (daily["costs"] / daily["equity"].shift(1).fillna(s["capital"]))
    cost_sens = robustness.cost_sensitivity(daily["ret_gross"], cost_frac, cash, bench_core["cagr"] if bench_core else None)
    boot = robustness.bootstrap(daily["ret"], n=500, cash_rate=cash) if s["robustness"]["bootstrap"] else None
    psr = robustness.psr(daily["ret"].to_numpy())
    grid = None
    dsr = None
    axes = _grid_axes(s)
    if axes:
        grid = run_grid(m, s, costs, axes, say)
        dsr = robustness.deflated(daily["ret"].to_numpy(), grid.pop("_daily_sharpes"))
    say(0.9, "Mise en forme")
    verdict = robustness.verdict(core, bench_core, rand, split, cost_sens, dsr, trades_stats.get("count", 0))

    eq = daily["equity"]
    dd = metrics.drawdown(eq)
    dates, eq_s = metrics.sample(eq)
    keep = [daily.index.get_loc(pd.Timestamp(d)) for d in dates]
    series = {"dates": dates, "equity": eq_s, "drawdown": [float(dd.iloc[i]) for i in keep], "gross": [float(daily["gross"].iloc[i]) for i in keep],
              "net": [float(daily["net"].iloc[i]) for i in keep], "positions": [int(daily["positions"].iloc[i]) for i in keep]}
    if bench_eq is not None:
        bdd = metrics.drawdown(bench_eq)
        series["benchmark"] = [float(bench_eq.iloc[i]) for i in keep]
        series["bench_drawdown"] = [float(bdd.iloc[i]) for i in keep]
    monthly = res.weights.resample("ME").last()
    held = [c for c in monthly.columns if monthly[c].abs().max() > 1e-4]
    order = sorted(held, key=lambda c: -monthly[c].abs().mean())[:12]
    allocation = {"dates": [d.date().isoformat() for d in monthly.index], "symbols": order,
                  "weights": [[float(monthly[c].iloc[i]) for c in order] for i in range(len(monthly))],
                  "other": [float(monthly.drop(columns=order).abs().sum(axis=1).iloc[i]) if len(held) > len(order) else 0.0 for i in range(len(monthly))]}
    gain = float(eq.iloc[-1] - s["capital"])
    contrib = sorted(({"symbol": k, "pnl": v, "share": (v / gain) if gain else None} for k, v in res.contributions.items()), key=lambda x: -abs(x["pnl"]))
    by_year = daily["costs"].groupby(daily.index.year).sum()
    years = max(core["years"], 1 / 252)
    result = {
        "version": VERSION, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "spec": s, "strategy": readable,
        "universe": [{"symbol": c, "first": m.close[c].first_valid_index().date().isoformat(), "last": m.close[c].last_valid_index().date().isoformat(),
                      "source": book.source.get(c, "calculé")} for c in m.traded],
        "aux": m.aux, "missing": missing, "notes": notes,
        "period": {"start": daily.index[0].date().isoformat(), "end": daily.index[-1].date().isoformat(), "days": len(daily)},
        "summary": {**core, "final_equity": float(eq.iloc[-1]), "pnl": gain, "exposure": float(daily["gross"].mean()),
                    "time_invested": float((daily["gross"] > 1e-6).mean()), "turnover_annual": float(daily["turnover"].sum() / years),
                    "costs_total": res.costs_total, "costs_annual_share": float(cost_frac.sum() / years)},
        "trade_stats": trades_stats,
        "benchmark": {"label": bench_label, "metrics": bench_core, "versus": vs} if bench_core else {"label": bench_label, "metrics": None},
        "periodic": metrics.periodic(eq), "bench_periodic": metrics.periodic(bench_eq) if bench_eq is not None else None,
        "drawdowns": metrics.drawdown_periods(eq), "series": series, "allocation": allocation,
        "rolling": metrics.rolling(daily["ret"], cash_rate=cash),
        "trades": res.trades[-MAX_TRADES_SHOWN:], "trades_total": len(res.trades), "contributions": contrib,
        "costs": {"total": res.costs_total, "by_year": {str(k): float(v) for k, v in by_year.items()}},
        "robustness": {"split": split, "random": rand, "costs": cost_sens, "bootstrap": boot, "psr": psr, "grid": grid, "dsr": dsr},
        "verdict": verdict,
    }
    say(1.0, "Terminé")
    return _num(result)
