"""Black-Litterman v2 sur probabilités de hausse CALIBRÉES.

Remplace la version intérimaire supprimée le 2026-10-12 (aucun appelant). Ce qui change : les « vues » ne sont plus saisies
à la main ni tirées d'une classe prédite, elles viennent de `prediction.p_up` — P(hausse) = P(hausse faible) + P(hausse forte),
calibrée (isotonique ou Platt, ajustée sur des lignes réelles du jeu d'entraînement de chaque pli, `models/calibration.py`)
quand le run a activé la calibration. Une probabilité non calibrée n'est pas une probabilité : par défaut, les runs sans
calibration sont ignorés.

Chaîne :
1. **Prior** — rendements d'équilibre π = δ Σ w_réf, avec w_réf = poids HRP (aucune capitalisation de marché n'existe pour
   des matières premières, des devises ou des cryptos) ; Σ est la covariance Ledoit-Wolf point-in-time annualisée.
2. **Vues** — pour chaque actif dont la probabilité est nette (|2p − 1| ≥ `min_edge`) :
   Q = (2p − 1) · √(2/π) · σ_annuel · √(252/h). Lecture : l'espérance d'un rendement de signe aléatoire de taille |r| gaussienne
   vaut (2p − 1)·E|r| avec E|r| = σ_h·√(2/π) ; c'est une approximation (tailles de hausse et de baisse supposées égales).
3. **Confiance** — c = |2p − 1| ; incertitude de la vue Ω = τ σ² / c (He-Litterman : τΣ pour une vue absolue, divisé par la
   confiance). Une probabilité à 0,55 pèse peu, une à 0,9 beaucoup.
4. **Postérieur** — μ = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ [(τΣ)⁻¹π + PᵀΩ⁻¹Q] (P = sélection des actifs avec vue).
5. **Poids** — maximise μᵀw − (δ/2) wᵀΣw, w ≥ 0, Σw = 1, w ≤ plafond. On optimise avec Σ (et non Σ + [(τΣ)⁻¹ + …]⁻¹) : sans
   aucune vue, la solution est exactement le portefeuille de référence.

Limites : le signal P(hausse) est une probabilité par horizon sur une classe de rendement, pas une espérance de rendement ;
la conversion ci-dessus est une hypothèse, pas une mesure. Aucune garantie que les tilts battent la pondération de référence :
la comparaison hors échantillon reste à faire (critère d'entrée de `docs/modelisation/chantiers-lointains.md`).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
from scipy.optimize import minimize

TRADING_DAYS = 252
GAUSSIAN_MEAN_ABS = float(np.sqrt(2.0 / np.pi))
DEFAULT_TAU = 0.05
DEFAULT_RISK_AVERSION = 2.5


def implied_returns(cov: pd.DataFrame, weights: pd.Series, risk_aversion: float = DEFAULT_RISK_AVERSION) -> pd.Series:
    w = weights.reindex(cov.index).astype(float)
    return pd.Series(risk_aversion * cov.values @ w.values, index=cov.index)


def view_returns(p_up: pd.Series, vol_annual: pd.Series, horizon: int) -> pd.Series:
    """Rendement annualisé impliqué par P(hausse) à l'horizon `horizon` jours de bourse."""
    edge = 2.0 * p_up.astype(float) - 1.0
    return edge * GAUSSIAN_MEAN_ABS * vol_annual.reindex(p_up.index) * np.sqrt(TRADING_DAYS / horizon)


def select_views(p_up: pd.Series, min_edge: float = 0.05) -> pd.Series:
    """Garde les probabilités assez nettes : une probabilité à 0,51 est une absence d'avis, pas une vue."""
    p = p_up.dropna().astype(float)
    return p[(2.0 * p - 1.0).abs() >= min_edge]


def view_confidence(p_up: pd.Series) -> pd.Series:
    return (2.0 * p_up.astype(float) - 1.0).abs().clip(1e-6, 1.0)


def posterior(cov: pd.DataFrame, prior: pd.Series, q: pd.Series, omega: pd.Series,
              tau: float = DEFAULT_TAU) -> tuple[pd.Series, pd.DataFrame]:
    """Rendements et covariance postérieurs. `q`/`omega` : vues absolues indexées par actif (peuvent être vides)."""
    symbols = list(cov.index)
    sigma = cov.values
    tau_inv = np.linalg.inv(tau * sigma)
    precision = tau_inv.copy()
    rhs = tau_inv @ prior.reindex(symbols).values
    for symbol, value in q.items():
        i = symbols.index(symbol)
        inv_omega = 1.0 / float(omega[symbol])
        precision[i, i] += inv_omega
        rhs[i] += inv_omega * float(value)
    cov_mu = np.linalg.inv(precision)
    mu = pd.Series(cov_mu @ rhs, index=symbols)
    return mu, pd.DataFrame(sigma + cov_mu, index=symbols, columns=symbols)


def optimal_weights(mu: pd.Series, cov: pd.DataFrame, risk_aversion: float = DEFAULT_RISK_AVERSION,
                    max_weight: float = 0.3, start: pd.Series | None = None) -> pd.Series:
    """Portefeuille long seul, somme 1, plafonné. Renvoie `start` (ou l'équipondération) si l'optimiseur échoue."""
    n = len(mu)
    cap = max(max_weight, 1.0 / n)
    x0 = (start.reindex(mu.index).values if start is not None else np.full(n, 1.0 / n)).astype(float)
    x0 = np.clip(x0, 0.0, cap)
    x0 = x0 / x0.sum()
    m, s = mu.values.astype(float), cov.values.astype(float)

    res = minimize(lambda w: -(m @ w) + 0.5 * risk_aversion * w @ s @ w, x0, jac=lambda w: -m + risk_aversion * s @ w,
                   method="SLSQP", bounds=[(0.0, cap)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones_like(w)}],
                   options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, 0.0, cap) if res.success else x0
    return pd.Series(w / w.sum(), index=mu.index)


def black_litterman(cov_annual: pd.DataFrame, reference: pd.Series, p_up: pd.Series, horizon: int,
                    tau: float = DEFAULT_TAU, risk_aversion: float = DEFAULT_RISK_AVERSION, min_edge: float = 0.05,
                    max_weight: float = 0.3) -> dict:
    reference = (reference.reindex(cov_annual.index) / reference.reindex(cov_annual.index).sum()).astype(float)
    pi = implied_returns(cov_annual, reference, risk_aversion)
    views_p = select_views(p_up.reindex(cov_annual.index).dropna(), min_edge)
    vol = pd.Series(np.sqrt(np.diag(cov_annual.values)), index=cov_annual.index)
    q = view_returns(views_p, vol, horizon)
    conf = view_confidence(views_p)
    omega = tau * vol.reindex(views_p.index) ** 2 / conf
    mu, sigma_post = posterior(cov_annual, pi, q, omega, tau)
    weights = optimal_weights(mu, cov_annual, risk_aversion, max(max_weight, float(reference.max())), start=reference)
    views = pd.DataFrame({"p_up": views_p, "view_return": q, "confidence": conf, "omega": omega,
                          "prior_return": pi.reindex(views_p.index), "posterior_return": mu.reindex(views_p.index)})
    return {"weights": weights, "reference": reference, "prior_returns": pi, "posterior_returns": mu, "views": views,
            "posterior_covariance": sigma_post, "tau": tau, "risk_aversion": risk_aversion}


def latest_calibrated_p_up(conn: sqlite3.Connection, targets: list[str], horizon: int, since: str | None = None,
                           require_calibrated: bool = True) -> dict[str, float]:
    """Dernière P(hausse) LIVE de chaque cible à l'horizon donné (une sous-requête corrélée par cible, comme les autres
    lectures de `prediction` : pas de fonction de fenêtre sur 12 M de lignes). Par défaut, uniquement les runs qui ont
    calibré leurs probabilités (`config.models.calibration`)."""
    if not targets:
        return {}
    marks = ",".join("?" for _ in targets)
    calibrated = "AND json_extract(r2.config_json, '$.models.calibration') = 1 " if require_calibrated else ""
    recent = "AND p.ts >= ? " if since else ""
    sql = (
        "SELECT r.target, (SELECT p.p_up FROM prediction p JOIN trial t ON t.trial_id = p.trial_id "
        "JOIN run r2 ON r2.run_id = t.run_id "
        f"WHERE r2.target = r.target AND r2.horizon = ? AND p.split = 'live' AND p.p_up IS NOT NULL {calibrated}{recent}"
        "ORDER BY p.ts DESC LIMIT 1) "
        f"FROM (SELECT DISTINCT target FROM run WHERE target IN ({marks}) AND horizon = ?) r")
    args = [horizon] + ([since] if since else []) + list(targets) + [horizon]
    return {target: float(p) for target, p in conn.execute(sql, args).fetchall() if p is not None}


def bl_overview(conn: sqlite3.Connection, horizon: int, as_of=None, lookback: int = 252, min_obs: int = 60, store=None,
                estimator: str = "ledoit_wolf", tau: float = DEFAULT_TAU, risk_aversion: float = DEFAULT_RISK_AVERSION,
                min_edge: float = 0.05, max_weight: float = 0.3, max_age_days: int | None = 14,
                require_calibrated: bool = True) -> dict:
    """Portefeuille Black-Litterman de l'univers complet, lu sur les prix DÉJÀ en cache (jamais de téléchargement : même
    discipline que `hrp_overview`) et sur les P(hausse) calibrées les plus récentes. Les actifs sans prix suffisant sont listés
    dans `skipped`."""
    from patrick.config import defaults as D
    from patrick.data.sources.yfinance_source import clean_symbol
    from patrick.data.store import DataStore
    from patrick.tracking.covariance import point_in_time_covariance
    from patrick.tracking.hrp import hrp_weights

    empty = {"weights": pd.Series(dtype=float), "reference": pd.Series(dtype=float), "views": pd.DataFrame(),
             "n_assets": 0, "n_views": 0, "horizon": horizon, "as_of": as_of}
    store = store or DataStore()
    prices: dict[str, pd.Series] = {}
    skipped: list[str] = []
    for symbol in D.DEFAULT_UNIVERSE_YF_TICKERS:
        if not store.exists(f"raw_{symbol}"):
            skipped.append(symbol)
            continue
        df = store.load(f"raw_{symbol}")
        col = clean_symbol(symbol)
        if col not in df.columns:
            col = "Close" if "Close" in df.columns else df.columns[0]
        prices[symbol] = df[col].dropna()
    if not prices:
        return {**empty, "skipped": sorted(skipped)}

    as_of_ts = pd.Timestamp(as_of) if as_of is not None else max(s.index.max() for s in prices.values())
    usable = {}
    for symbol, s in prices.items():
        trunc = s[s.index <= as_of_ts]
        if len(trunc) >= min_obs + 1:
            usable[symbol] = trunc
        else:
            skipped.append(symbol)
    if len(usable) < 2:
        return {**empty, "skipped": sorted(set(skipped)), "as_of": as_of_ts}
    try:
        cov_daily = point_in_time_covariance(usable, as_of=as_of_ts, lookback=lookback, min_obs=min_obs,
                                             estimator=estimator)
    except ValueError:
        return {**empty, "skipped": sorted(set(skipped) | set(usable)), "as_of": as_of_ts}

    since = (pd.Timestamp.now() - pd.Timedelta(days=max_age_days)).strftime("%Y-%m-%d") if max_age_days else None
    p_up = pd.Series(latest_calibrated_p_up(conn, list(usable), horizon, since=since,
                                            require_calibrated=require_calibrated), dtype=float)
    reference = hrp_weights(cov_daily)
    result = black_litterman(cov_daily * TRADING_DAYS, reference, p_up, horizon, tau, risk_aversion, min_edge, max_weight)
    return {**result, "n_assets": len(usable), "n_views": len(result["views"]), "horizon": horizon, "as_of": as_of_ts,
            "skipped": sorted(set(skipped)), "covariance": estimator, "shrinkage": cov_daily.attrs.get("shrinkage"),
            "n_obs": cov_daily.attrs.get("n_obs"), "n_probabilities": len(p_up)}


def table_rows(result: dict) -> list[dict]:
    """Une ligne par actif, triées par poids Black-Litterman décroissant, pour l'affichage : poids de référence, poids final,
    écart en points, et la vue (probabilité, rendement visé, confiance) quand l'actif en a une."""
    views = result["views"]
    rows = []
    for symbol, weight in result["weights"].sort_values(ascending=False).items():
        view = views.loc[symbol] if symbol in views.index else None
        ref = float(result["reference"][symbol])
        rows.append({
            "symbol": symbol, "reference": ref, "weight": float(weight), "tilt_pts": (float(weight) - ref) * 100.0,
            "p_up": None if view is None else float(view["p_up"]),
            "view_return": None if view is None else float(view["view_return"]),
            "confidence": None if view is None else float(view["confidence"]),
        })
    return rows
