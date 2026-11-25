"""Prévision du NIVEAU de volatilité (A1, décision proposée le 02/11 dans `docs/modelisation/cible-volatilite-faisabilite-2026-11-02.md`).

La direction de la volatilité se prévoit (AUC 0,73 à 0,78) mais presque entièrement par retour à la moyenne : ce n'est pas un signal à parier,
c'est une TAILLE de position. Le pilote des fonds dimensionne à volatilité inverse ; il utilisait la volatilité des 60 dernières séances. Ce
module prévoit la volatilité du lendemain par un HAR-RV (Corsi 2009) sur le log de la variance journalière, jugé en QLIKE contre la volatilité
glissante (jamais en AUC, jamais rangé avec les directions de prix : D8).

Variance journalière (A5) : Garman-Klass quand les cours ouverture / haut / bas / clôture existent (bien moins bruitée qu'un rendement au carré),
ramenée à l'échelle clôture à clôture par le rapport de leurs moyennes sur la fenêtre (les estimateurs intrajournaliers ignorent l'écart de nuit,
donc sous-estiment) ; sinon le rendement au carré. Tout est causal : rien après `today`.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HISTORY = 504                 # ~2 ans de séances pour l'ajustement
MIN_ROWS = 160                # en dessous : pas de HAR, la volatilité glissante reste
TRAILING_WINDOW = 60          # la volatilité glissante que le pilote utilisait (`autopilot.VOL_WINDOW`)
EVAL_DAYS = 250
REFIT_EVERY = 20


def daily_variance(df: pd.DataFrame) -> pd.Series:
    """Variance journalière, échelle clôture à clôture. `df` : colonnes `close` et, si possible, `open`, `high`, `low`."""
    close = df["close"].astype(float)
    r2 = np.log(close).diff() ** 2
    cols = {"open", "high", "low"}
    if cols.issubset(df.columns) and df[list(cols)].notna().mean().min() > 0.9:
        o, h, lo = (df[c].astype(float) for c in ("open", "high", "low"))
        gk = 0.5 * np.log(h / lo) ** 2 - (2 * math.log(2) - 1) * np.log(close / o) ** 2
        gk = gk.where(np.isfinite(gk) & (gk > 0))
        both = pd.concat([r2.rename("r2"), gk.rename("gk")], axis=1).dropna()
        if len(both) >= 60 and both["gk"].mean() > 0:
            return (gk * (both["r2"].mean() / both["gk"].mean())).rename("variance")
    return r2.rename("variance")


def _design_last(log_v: pd.Series) -> np.ndarray:
    """Régresseurs HAR pour prévoir le LENDEMAIN de la dernière date : log-variance du jour, moyennes sur 5 et 22 jours (jour compris)."""
    return np.array([1.0, log_v.iloc[-1], log_v.iloc[-5:].mean(), log_v.iloc[-22:].mean()])


def har_sigma(df: pd.DataFrame, today: pd.Timestamp | None = None) -> dict | None:
    """Volatilité journalière prévue pour la séance suivant `today` (HAR sur le log de la variance, correction log-normale), avec la volatilité
    glissante de `TRAILING_WINDOW` séances pour comparaison. None si l'historique est trop court."""
    from patrick.econometrics import variance_models as V

    data = df if today is None else df[df.index <= pd.Timestamp(today)]
    v = daily_variance(data).replace([np.inf, -np.inf], np.nan).dropna()
    v = v[v > 0].iloc[-HISTORY:]
    if len(v) < MIN_ROWS:
        return None
    log_v = np.log(v)
    X, y = V._har_design(log_v)
    if len(y) < MIN_ROWS - 30:
        return None
    A = np.column_stack([np.ones(len(X)), X.to_numpy()])
    beta, *_ = np.linalg.lstsq(A, y.to_numpy(), rcond=None)
    resid_var = float(np.var(y.to_numpy() - A @ beta, ddof=A.shape[1]))
    var_hat = float(np.exp(_design_last(log_v) @ beta + 0.5 * resid_var))
    close = data["close"].astype(float)
    trailing = float(np.log(close).diff().dropna().tail(TRAILING_WINDOW).std())
    return {"sigma": math.sqrt(var_hat), "trailing": trailing if math.isfinite(trailing) else None, "n_obs": len(y),
            "persistence": float(beta[1:].sum()), "as_of": v.index[-1].strftime("%Y-%m-%d")}


def evaluate(df: pd.DataFrame, today: pd.Timestamp | None = None, days: int = EVAL_DAYS) -> dict | None:
    """QLIKE hors échantillon sur les `days` dernières séances : HAR (réajusté tous les `REFIT_EVERY` jours sur le passé seul) contre la
    volatilité glissante. `skill` > 0 : le HAR prévoit mieux. Jugé contre la variance journalière elle-même (proxy bruité mais sans biais)."""
    from patrick.econometrics import variance_models as V
    from patrick.econometrics.forecast_eval import qlike

    data = df if today is None else df[df.index <= pd.Timestamp(today)]
    v = daily_variance(data).replace([np.inf, -np.inf], np.nan).dropna()
    v = v[v > 0]
    if len(v) < MIN_ROWS + days:
        return None
    log_v = np.log(v)
    X, y = V._har_design(log_v)
    test = y.index[-days:]
    har = pd.Series(np.nan, index=test)
    for start in range(0, len(test), REFIT_EVERY):
        block = test[start:start + REFIT_EVERY]
        past = y.index < block[0]
        past_idx = y.index[past][-HISTORY:]
        A = np.column_stack([np.ones(len(past_idx)), X.loc[past_idx].to_numpy()])
        beta, *_ = np.linalg.lstsq(A, y.loc[past_idx].to_numpy(), rcond=None)
        s2 = float(np.var(y.loc[past_idx].to_numpy() - A @ beta, ddof=A.shape[1]))
        rows = X.loc[block]
        har.loc[block] = np.exp(np.column_stack([np.ones(len(rows)), rows.to_numpy()]) @ beta + 0.5 * s2)
    trailing = v.shift(1).rolling(TRAILING_WINDOW).mean().reindex(test)
    frame = pd.concat([v.reindex(test).rename("p"), har.rename("har"), trailing.rename("tr")], axis=1).dropna()
    if len(frame) < days // 2:
        return None
    q_har, q_tr = float(qlike(frame["p"], frame["har"]).mean()), float(qlike(frame["p"], frame["tr"]).mean())
    return {"qlike_har": q_har, "qlike_trailing": q_tr, "skill": 1 - q_har / q_tr if q_tr else None, "n": len(frame)}


# FO24 (25/11) : volatilité implicite à 30 jours publiée par les marchés d'options pour quelques indices (en points de pourcentage annualisés).
IMPLIED_INDEX = {"^GSPC": "^VIX", "^NDX": "^VXN", "^IXIC": "^VXN", "^RUT": "^RVX", "^DJI": "^VXD", "GC=F": "^GVZ", "CL=F": "^OVX",
                 "EURUSD=X": "^EVZ"}


def implied_vs_forecast(symbol: str, sigma_daily: float | None, implied_close: float | None) -> dict | None:
    """Volatilité implicite (indice VIX & co.) contre la prévision HAR annualisée : la PRIME de risque de volatilité.

    Prime = implicite² − prévue² (en variance annualisée) ; positive presque toujours : les vendeurs d'options se font payer le risque de
    krach. Une prime négative (le marché d'options attend MOINS de mouvement que le modèle) est rare et mérite un coup d'œil."""
    if sigma_daily is None or implied_close is None or implied_close <= 0:
        return None
    forecast_ann = sigma_daily * math.sqrt(252)
    implied = implied_close / 100.0
    return {"index": IMPLIED_INDEX.get(symbol), "implied": implied, "forecast": forecast_ann,
            "premium_var": implied ** 2 - forecast_ann ** 2, "ratio": implied / forecast_ann if forecast_ann else None}
