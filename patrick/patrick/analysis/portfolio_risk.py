"""Risque et simulation de portefeuille (page `/risque`) : lecture seule, aucune écriture dans le registre patrimoine.

Trois blocs, tous calculés à partir des cours que le fournisseur de prix du patrimoine sait lire (`wealth.prices`) :

* `risk_report`   : VaR / ES (historique, gaussienne, Cornish-Fisher), baisse maximale, contributions au risque, corrélations,
                    scénarios historiques (fenêtres de crise) et chocs uniformes sur la part risquée ;
* `backtest`      : simulation « marche avant » de règles d'allocation (poids égaux, inverse de la volatilité, HRP, poids actuels)
                    avec coûts de transaction sur la rotation, attribution par ligne, intervalle de confiance du Sharpe ;
* `rebalance_gaps`: écarts arithmétiques entre les poids actuels et une allocation cible (montants, bande de tolérance, coût estimé).

Hypothèses assumées et affichées : poids constants entre deux dates (rééquilibrage quotidien) pour le risque historique ; cours de
clôture non ajustés des dividendes (comme le registre) ; espèces et dépôts à terme sans variance. Rien ici n'est un conseil :
les écarts à la cible sont de l'arithmétique, pas une recommandation d'opération.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

from patrick.analysis import stats_core as sc
from patrick.features._utils import safe_pct_change
from patrick.tracking.hrp import hrp_weights
from patrick.wealth import ledger, performance

TRADING_DAYS = 252
MAX_POINTS = 700
LEVELS = (0.95, 0.99)
METHODS = ("equal", "inv_vol", "hrp", "current")
MIN_COVERAGE = 0.5                          # part minimale du poids risqué qui doit exister sur une fenêtre de crise

# Fenêtres de crise : date de sommet → date de creux de l'indice S&P 500 (cours de clôture historiques).
STRESS_WINDOWS = (
    ("dotcom", "2000-03-24", "2002-10-09"),
    ("gfc", "2007-10-09", "2009-03-09"),
    ("euro_debt", "2011-07-22", "2011-10-03"),
    ("q4_2018", "2018-09-20", "2018-12-24"),
    ("covid", "2020-02-19", "2020-03-23"),
    ("bear_2022", "2022-01-03", "2022-10-12"),
)
SHOCKS = (-0.10, -0.20, -0.30)

PriceFn = Callable[[str], pd.Series | None]


# ------------------------------------------------------------------------------------------------------------ positions
def resolve_holdings(conn, prices: PriceFn, source: str = "real") -> dict:
    """Positions à analyser : `real` (tout le patrimoine réel consolidé), `fictive` ou l'identifiant d'un compte.

    Renvoie `{label, total, cash, rows: [{symbol, value, weight, is_term_deposit}], accounts}` ; les poids sont rapportés au total
    (espèces et dépôts à terme inclus)."""
    accounts = ledger.list_accounts(conn)
    if source in ("real", "fictive"):
        chosen = [a for a in accounts if a["mode"] == source]
    else:
        chosen = [a for a in accounts if a["account_id"] == source]
    rows: dict[str, dict] = {}
    cash = 0.0
    for acc in chosen:
        h = performance.holdings_table(ledger.list_movements(conn, acc["account_id"]), prices, account=acc)
        cash += h["cash"]
        for r in h["rows"]:
            c = rows.setdefault(r["symbol"], {"symbol": r["symbol"], "value": 0.0, "is_term_deposit": r["is_term_deposit"]})
            c["value"] += float(r["value"] or 0.0)
    invested = sum(r["value"] for r in rows.values())
    total = cash + invested
    warnings: list[str] = []
    if cash < -1e-6:                                    # solde négatif (mouvements incomplets) : les poids sont rapportés aux positions seules
        warnings.append("negative_cash")
        total = invested
    for r in rows.values():
        r["weight"] = r["value"] / total if total > 0 else None
    out = sorted(rows.values(), key=lambda r: -r["value"])
    return {"source": source, "total": total, "cash": cash, "rows": out, "warnings": warnings,
            "accounts": [{"account_id": a["account_id"], "name": a["name"], "mode": a["mode"], "kind": a["kind"]} for a in accounts]}


def risky_weights(holdings: dict) -> dict[str, float]:
    """Poids (sur le total) des lignes cotées ; espèces et dépôts à terme sont exclus (variance nulle)."""
    return {r["symbol"]: r["weight"] for r in holdings["rows"] if not r["is_term_deposit"] and r["weight"] and r["weight"] > 0}


def load_prices(symbols, prices: PriceFn, min_obs: int = 60) -> tuple[dict[str, pd.Series], list[dict]]:
    """Séries exploitables (au moins `min_obs` rendements) et liste des exclusions motivées."""
    usable: dict[str, pd.Series] = {}
    excluded: list[dict] = []
    for s in symbols:
        ser = prices(s)
        if ser is None or len(ser.dropna()) <= min_obs:
            excluded.append({"symbol": s, "reason": "no_data" if ser is None else "short_history", "n": 0 if ser is None else len(ser.dropna())})
        else:
            usable[s] = ser.dropna()
    return usable, excluded


def returns_frame(series: dict[str, pd.Series], lookback: int | None = None) -> pd.DataFrame:
    """Rendements journaliers alignés sur les dates communes (jointure interne, comme la covariance du dépôt)."""
    df = pd.DataFrame({s: safe_pct_change(v) for s, v in series.items()}).dropna(how="any")
    return df.iloc[-lookback:] if lookback else df


# ------------------------------------------------------------------------------------------------------------- VaR / ES
def _z(level: float) -> float:
    from scipy.stats import norm
    return float(norm.ppf(1.0 - level))


def var_es(returns, level: float = 0.95, horizon: int = 1) -> dict:
    """Perte (valeur positive) non dépassée avec la probabilité `level`, et perte moyenne au-delà (ES).

    Trois estimations : historique (percentile des rendements réels), gaussienne (moyenne et écart-type) et Cornish-Fisher
    (gaussienne corrigée de l'asymétrie et de l'aplatissement). L'horizon multiple utilise la racine du temps (hypothèse indépendante)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 30:
        return {"n": n, "hist": None, "es_hist": None, "gauss": None, "es_gauss": None, "cf": None}
    scale = math.sqrt(horizon)
    q = float(np.quantile(r, 1.0 - level))
    tail = r[r <= q]
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    z = _z(level)
    from scipy.stats import kurtosis, norm, skew
    s, k = float(skew(r)), float(kurtosis(r))        # k : excès d'aplatissement
    zcf = z + (z * z - 1) * s / 6 + (z ** 3 - 3 * z) * k / 24 - (2 * z ** 3 - 5 * z) * s * s / 36
    return {"n": n, "level": level, "horizon": horizon, "skew": s, "kurt": k,
            "hist": max(0.0, -q) * scale, "es_hist": max(0.0, -float(tail.mean())) * scale if len(tail) else None,
            "gauss": max(0.0, -(mu + z * sd)) * scale, "es_gauss": max(0.0, -(mu - sd * float(norm.pdf(z)) / (1.0 - level))) * scale,
            "cf": max(0.0, -(mu + zcf * sd)) * scale}


def kupiec(returns, var_hist: float, level: float = 0.95) -> dict:
    """Test de Kupiec : la fréquence réelle de dépassement de la VaR est-elle compatible avec 1 - level ? (sur l'échantillon même, donc indicatif)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 100 or var_hist is None:
        return {"n": n, "breaches": None, "expected": None, "p": None}
    x = int((r < -var_hist).sum())
    p0 = 1.0 - level
    from scipy.stats import chi2
    ph = min(max(x / n, 1e-9), 1 - 1e-9)
    lr = -2.0 * ((n - x) * math.log(1 - p0) + x * math.log(p0) - (n - x) * math.log(1 - ph) - x * math.log(ph))
    return {"n": n, "breaches": x, "expected": n * p0, "p": float(chi2.sf(max(lr, 0.0), 1))}


# ----------------------------------------------------------------------------------------------------- contributions
def risk_contributions(weights: dict[str, float], cov: pd.DataFrame) -> list[dict]:
    """Contribution de chaque ligne à la volatilité du portefeuille (théorème d'Euler) : w_i·(Σw)_i / σ_p.

    Les poids sont ceux sur le total ; la somme des contributions vaut la volatilité du portefeuille (annualisée)."""
    syms = list(cov.index)
    w = np.array([weights.get(s, 0.0) for s in syms], dtype=float)
    C = cov.to_numpy(dtype=float)
    var = float(w @ C @ w)
    if var <= 0:
        return []
    vol = math.sqrt(var)
    marginal = C @ w / vol
    comp = w * marginal
    ann = math.sqrt(TRADING_DAYS)
    out = []
    for i, s in enumerate(syms):
        out.append({"symbol": s, "weight": float(w[i]), "vol": float(math.sqrt(C[i, i]) * ann), "marginal": float(marginal[i] * ann),
                    "contribution": float(comp[i] * ann), "share": float(comp[i] / vol)})
    out.sort(key=lambda r: -r["share"])
    return out


def _ledoit_wolf(df: pd.DataFrame) -> pd.DataFrame:
    from sklearn.covariance import LedoitWolf
    lw = LedoitWolf().fit(df.to_numpy())
    cov = pd.DataFrame(lw.covariance_, index=df.columns, columns=df.columns)
    cov.attrs["shrinkage"] = float(lw.shrinkage_)
    return cov


# --------------------------------------------------------------------------------------------------------------- crises
def stress_windows(series: dict[str, pd.Series], weights: dict[str, float], windows=STRESS_WINDOWS) -> list[dict]:
    """Rendement qu'aurait eu la part risquée actuelle sur chaque fenêtre de crise historique.

    Seules les lignes cotées sur toute la fenêtre comptent ; les poids sont renormalisés sur elles et la couverture est affichée.
    Sous `MIN_COVERAGE` de couverture le résultat est marqué insuffisant plutôt que présenté comme une mesure."""
    risky_total = sum(weights.values())
    out = []
    for key, start, end in windows:
        t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
        legs, covered = [], 0.0
        for s, w in weights.items():
            ser = series.get(s)
            if ser is None or ser.index.min() > t0 or ser.index.max() < t1:
                continue
            a = ser[ser.index <= t0]
            b = ser[ser.index <= t1]
            if a.empty or b.empty or float(a.iloc[-1]) <= 0:
                continue
            ret = float(b.iloc[-1]) / float(a.iloc[-1]) - 1.0
            legs.append({"symbol": s, "weight": w, "return": ret})
            covered += w
        cov_share = covered / risky_total if risky_total > 0 else 0.0
        ok = cov_share >= MIN_COVERAGE and covered > 0
        ret = sum(l["weight"] * l["return"] for l in legs) / covered if ok else None
        out.append({"key": key, "start": start, "end": end, "coverage": cov_share, "sufficient": ok,
                    "return_risky": ret, "return_total": ret * risky_total if ret is not None else None,
                    "legs": sorted(legs, key=lambda l: l["return"])})
    return out


def shock_scenarios(weights: dict[str, float], total_cash_share: float) -> list[dict]:
    """Effet d'un choc uniforme sur toutes les lignes cotées (sensibilité, pas une prévision)."""
    risky = sum(weights.values())
    return [{"shock": s, "loss_total": s * risky, "risky_share": risky, "protected_share": total_cash_share} for s in SHOCKS]


# ------------------------------------------------------------------------------------------------------------------ rapport
def risk_report(holdings: dict, prices: PriceFn, lookback: int = 504, min_obs: int = 60) -> dict:
    weights = risky_weights(holdings)
    out: dict = {"label": holdings["source"], "total": holdings["total"], "cash": holdings["cash"], "holdings": holdings["rows"],
                 "accounts": holdings["accounts"], "lookback": lookback, "weights_risky": weights,
                 "warnings": holdings.get("warnings", []), "risky_share": float(sum(weights.values())), "excluded": [], "dates": [], "available": False}
    if not weights or holdings["total"] <= 0:
        return out
    series, excluded = load_prices(list(weights), prices, min_obs)
    out["excluded"] = excluded
    if not series:
        return out
    df = returns_frame(series, lookback)
    if len(df) < min_obs:
        out["excluded"] += [{"symbol": "*", "reason": "common_window", "n": len(df)}]
        return out
    w = {s: weights[s] for s in df.columns}
    covered = sum(w.values())
    wv = np.array([w[s] for s in df.columns])
    port = pd.Series(df.to_numpy() @ wv, index=df.index)                   # rendement total (la part non cotée contribue 0)
    eq = sc.equity_from_returns(port.to_numpy())
    dd = sc.drawdown_series(eq)
    cov = _ledoit_wolf(df)
    contrib = risk_contributions(w, cov)
    pvol = float(sum(c["contribution"] for c in contrib)) if contrib else None
    risk_rows = []
    for lvl in LEVELS:
        for hz in (1, 10):
            v = var_es(port.to_numpy(), lvl, hz)
            risk_rows.append({**v, "kupiec": kupiec(port.to_numpy(), v["hist"], lvl) if hz == 1 else None})
    idx = sc.thin_indices(len(port), MAX_POINTS)
    corr = df.corr()
    order = [c["symbol"] for c in contrib]
    out.update({
        "available": True, "start": str(df.index[0].date()), "end": str(df.index[-1].date()), "n_days": len(df),
        "covered_weight": float(covered), "shrinkage": cov.attrs.get("shrinkage"), "volatility": pvol,
        "perf": sc.performance_summary(port.to_numpy()), "var": risk_rows, "contributions": contrib,
        "dates": [str(df.index[i].date()) for i in idx], "equity": [float(eq[i]) for i in idx], "drawdown": [float(dd[i]) for i in idx],
        "daily_returns": [float(v) for v in port.to_numpy()[idx]],
        "worst_days": [{"date": str(d.date()), "return": float(v)} for d, v in port.nsmallest(8).items()],
        "correlation": {"symbols": order, "values": [[float(corr.loc[a, b]) for b in order] for a in order]},
        "stress": stress_windows({s: series[s] for s in w}, w), "shocks": shock_scenarios(w, 1.0 - float(sum(weights.values()))),
    })
    return sc.jsonable(out)


# ------------------------------------------------------------------------------------------------------------ allocation
def target_weights(method: str, window: pd.DataFrame, current: dict[str, float] | None = None) -> pd.Series:
    """Poids cibles (somme 1, long seulement) d'une règle d'allocation calculés sur une fenêtre de rendements passés."""
    cols = list(window.columns)
    n = len(cols)
    if method == "equal" or n == 1:
        return pd.Series(1.0 / n, index=cols)
    if method == "current":
        w = pd.Series({c: max((current or {}).get(c, 0.0), 0.0) for c in cols})
        return w / w.sum() if w.sum() > 0 else pd.Series(1.0 / n, index=cols)
    vol = window.std(ddof=1).replace(0, np.nan)
    if method == "inv_vol":
        iv = (1.0 / vol).fillna(0.0)
        return iv / iv.sum() if iv.sum() > 0 else pd.Series(1.0 / n, index=cols)
    if method == "hrp":
        return hrp_weights(_ledoit_wolf(window))
    raise ValueError(f"méthode inconnue : {method!r} ({METHODS})")


def backtest_method(df: pd.DataFrame, method: str, lookback: int = 252, rebalance_days: int = 21, cost_bps: float = 10.0,
                    current: dict[str, float] | None = None) -> dict:
    """Simulation marche avant : à chaque date de rééquilibrage, poids calculés avec les `lookback` rendements passés seulement,
    appliqués à partir du jour suivant ; entre deux dates les poids dérivent avec les cours. Coût = rotation × `cost_bps` (un sens)."""
    R = df.to_numpy()
    n, m = R.shape
    cols = list(df.columns)
    if n <= lookback + 1:
        raise ValueError("historique commun trop court pour cette fenêtre d'estimation")
    cost = cost_bps / 1e4
    w = np.zeros(m)
    net = np.full(n - lookback, np.nan)
    gross = np.full(n - lookback, np.nan)
    turnover = np.zeros(n - lookback)
    contrib = np.zeros(m)
    weights_log: list[tuple[int, np.ndarray]] = []
    since = rebalance_days
    for k, t in enumerate(range(lookback, n)):
        if since >= rebalance_days or k == 0:
            target = target_weights(method, df.iloc[t - lookback:t], current).reindex(cols).to_numpy()
            turnover[k] = float(np.abs(target - w).sum())
            w = target
            weights_log.append((t, w.copy()))
            since = 0
        r = R[t]
        g = float(w @ r)
        gross[k] = g
        net[k] = g - cost * turnover[k]
        contrib += w * r
        denom = 1.0 + g
        w = w * (1.0 + r) / denom if denom > 0 else w
        since += 1
    eq = sc.equity_from_returns(net)
    return {"net": net, "gross": gross, "equity": eq, "turnover": turnover, "contrib": contrib, "weights_log": weights_log,
            "dates": df.index[lookback:]}


def _sharpe_stat(r):
    return sc.sharpe(r, TRADING_DAYS)


def backtest(holdings: dict, prices: PriceFn, methods=METHODS, lookback: int = 252, rebalance_days: int = 21, cost_bps: float = 10.0,
             min_obs: int = 60, n_boot: int = 200) -> dict:
    weights = risky_weights(holdings)
    out: dict = {"label": holdings["source"], "lookback": lookback, "rebalance_days": rebalance_days, "cost_bps": cost_bps,
                 "available": False, "excluded": [], "methods": []}
    if len(weights) < 2:
        out["reason"] = "need_two_assets"
        return out
    series, excluded = load_prices(list(weights), prices, min_obs)
    out["excluded"] = excluded
    if len(series) < 2:
        out["reason"] = "need_two_assets"
        return out
    df = returns_frame(series)
    limiting = max(series, key=lambda s: series[s].index.min())
    out["common_start"] = str(df.index[0].date()) if len(df) else None
    out["limiting_asset"] = limiting
    if len(df) <= lookback + 60:
        out["reason"] = "short_common_window"
        out["n_common"] = len(df)
        return out
    cur = {s: weights[s] for s in df.columns}
    results = {}
    for m in methods:
        if m not in METHODS:
            continue
        results[m] = backtest_method(df, m, lookback, rebalance_days, cost_bps, cur)
    dates = results[next(iter(results))]["dates"]
    idx = sc.thin_indices(len(dates), MAX_POINTS)
    out.update({"available": True, "assets": list(df.columns), "start": str(dates[0].date()), "end": str(dates[-1].date()),
                "n_days": len(dates), "dates": [str(dates[i].date()) for i in idx]})
    for m, res in results.items():
        net, gross = res["net"], res["gross"]
        perf = sc.performance_summary(net)
        ci = sc.block_bootstrap(_sharpe_stat, (net,), block=20, n_boot=n_boot)
        years = len(net) / TRADING_DAYS
        total_cost = float(np.nansum(gross - net))
        dd = sc.drawdown_series(res["equity"])
        wl = res["weights_log"]
        step = max(1, len(wl) // 60)
        out["methods"].append({
            "method": m, "perf": perf, "sharpe_ci": ci, "turnover_annual": float(res["turnover"].sum() / years) if years > 0 else None,
            "cost_total": total_cost, "cost_annual": total_cost / years if years > 0 else None,
            "equity": [float(res["equity"][i]) for i in idx], "drawdown": [float(dd[i]) for i in idx],
            "attribution": sorted([{"symbol": s, "contribution": float(c)} for s, c in zip(df.columns, res["contrib"], strict=True)],
                                  key=lambda r: -r["contribution"]),
            "weights": {"dates": [str(df.index[t].date()) for t, _ in wl[::step]], "symbols": list(df.columns),
                        "values": [[float(x) for x in w] for _, w in wl[::step]]},
            "last_weights": {s: float(x) for s, x in zip(df.columns, wl[-1][1], strict=True)},
        })
    return sc.jsonable(out)


# ---------------------------------------------------------------------------------------------------------------- écarts
def rebalance_gaps(holdings: dict, prices: PriceFn, method: str = "hrp", tolerance: float = 0.05, cost_bps: float = 10.0,
                   lookback: int = 252, min_obs: int = 60) -> dict:
    """Écarts entre poids actuels et allocation cible, sur la part risquée cotée.

    La cible est calculée sur la part risquée (somme des poids risqués conservée) ; les espèces et dépôts à terme ne bougent pas.
    Montants signés : positif = la ligne serait en dessous de la cible, négatif = au-dessus. Arithmétique uniquement."""
    weights = risky_weights(holdings)
    out: dict = {"method": method, "tolerance": tolerance, "cost_bps": cost_bps, "available": False, "rows": [], "excluded": []}
    if len(weights) < 2 or holdings["total"] <= 0:
        out["reason"] = "need_two_assets"
        return out
    series, excluded = load_prices(list(weights), prices, min_obs)
    out["excluded"] = excluded
    if len(series) < 2:
        out["reason"] = "need_two_assets"
        return out
    df = returns_frame(series, lookback)
    if len(df) < min_obs:
        out["reason"] = "short_common_window"
        return out
    risky_total = sum(weights[s] for s in df.columns)
    cur = {s: weights[s] / risky_total for s in df.columns}
    tgt = target_weights(method, df, cur)
    total = holdings["total"]
    rows = []
    for s in df.columns:
        gap = float(tgt[s] - cur[s]) * risky_total
        rows.append({"symbol": s, "current": float(cur[s] * risky_total), "target": float(tgt[s] * risky_total), "gap": gap,
                     "amount": gap * total, "outside_band": abs(gap) > tolerance})
    rows.sort(key=lambda r: -abs(r["gap"]))
    turnover = float(sum(abs(r["amount"]) for r in rows))
    out.update({"available": True, "rows": rows, "total": total, "risky_share": risky_total, "turnover_amount": turnover,
                "cost_estimate": turnover * cost_bps / 1e4, "n_outside": int(sum(r["outside_band"] for r in rows)),
                "as_of": str(df.index[-1].date())})
    return sc.jsonable(out)
