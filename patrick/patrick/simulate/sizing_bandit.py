"""Dimensionnement appris par bandit contextuel (LinUCB), évalué par rejeu sur les prédictions déjà stockées.

Cadrage : `docs/modelisation/chantiers-lointains.md` §1. L'environnement est un backtest rejoué : l'agent n'influence pas les prix, donc un RL complet ajoute de la variance
sans information. La version défendable est un bandit qui, pour chaque signal d'un modèle, choisit la TAILLE de la position (jamais le sens, donné par P(hausse)) parmi quelques
fractions de la taille maximale, en observant sa récompense après coup.

Récompense d'un bras `s` (fraction de taille), en unités de volatilité quotidienne `sigma` connue à la date du signal :

    u(s) = s * g - gamma * s^2 / 2 - frais * |s * sens - position_précédente| / sigma,      g = sens * rendement_suivant / sigma

`gamma = REFERENCE_EDGE` (1 / racine de 252, l'espérance quotidienne, en unités de volatilité, d'un Sharpe annualisé de 1) : l'optimum `s* = E[g | x] / gamma` vaut 1 pour un signal
d'un Sharpe de 1, 0,3 pour un Sharpe de 0,3, 0 si l'espérance est nulle ou négative. La taille proportionnelle à l'espérance, plafonnée à la taille maximale, est la forme
de Kelly fractionnaire que le cadrage demandait.

Tout est causal : le contexte d'un signal ne lit que des rendements jusqu'à sa date ; le bandit n'apprend que de récompenses de signaux passés (le rendement du lendemain d'un signal
est observé avant le signal suivant) ; il est préchauffé sur le segment `test` du modèle (antérieur au holdout, walk-forward) puis continue d'apprendre en ligne sur le holdout. Une
configuration unique, fixée avant la mesure, jamais réglée (voir `ARMS`, `ALPHA`, `RIDGE`).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.simulate import engine as sim_engine
from patrick.simulate import metrics as simmetrics

ARMS = (0.0, 0.25, 0.5, 1.0)                       # fractions de la taille maximale
ALPHA = 1.0                                        # largeur de l'intervalle de confiance (exploration)
RIDGE = 1.0                                        # régularisation initiale
REFERENCE_EDGE = 1.0 / np.sqrt(simmetrics.TRADING_DAYS_PER_YEAR)
N_FEATURES = 3                                     # biais, force du signal |2p - 1|, log du rapport de volatilités (20 j / 250 j)
VOL_SHORT, VOL_LONG = 20, 250
COST_BPS = 5.0                                     # frais par unité de rotation, appliqués à TOUTES les politiques comparées
HEURISTICS = {
    "threshold": sim_engine.SimParams(position_mode="threshold", threshold=0.55),
    "proportional": sim_engine.SimParams(position_mode="proportional"),
    "leverage_half": sim_engine.SimParams(position_mode="heuristic_leverage", kelly_fraction=0.5),
}


class LinUCB:
    """Un modèle ridge par bras ; choisit le bras de plus grande borne haute `theta.x + alpha * sqrt(x' A^-1 x)`. Retour de bandit : seul le bras joué est mis à jour."""

    def __init__(self, n_arms: int = len(ARMS), dim: int = N_FEATURES, alpha: float = ALPHA, ridge: float = RIDGE):
        self.alpha = alpha
        self.A = [ridge * np.eye(dim) for _ in range(n_arms)]
        self.b = [np.zeros(dim) for _ in range(n_arms)]

    def choose(self, x: np.ndarray) -> int:
        bounds = []
        for A, b in zip(self.A, self.b, strict=True):
            inv = np.linalg.inv(A)
            bounds.append(float((inv @ b) @ x + self.alpha * np.sqrt(max(x @ inv @ x, 0.0))))
        return int(np.argmax(bounds))                # égalité : le premier bras (la taille la plus prudente)

    def update(self, arm: int, x: np.ndarray, reward: float) -> None:
        self.A[arm] += np.outer(x, x)
        self.b[arm] += reward * x


def contexts(score: np.ndarray, close: pd.Series, idx: np.ndarray) -> np.ndarray:
    """Contexte de chaque signal. `close` : cours journaliers COMPLETS ; `idx` : position de la date de chaque signal dans leur index. Les écarts-types glissants ne lisent que le passé
    (la valeur à la date t n'utilise aucun rendement postérieur à t) : lus à la date du signal, ils sont causaux."""
    ret = close.astype(float).pct_change()                      # pas de logarithme : un cours peut être nul ou négatif (pétrole, avril 2020)
    short = ret.rolling(VOL_SHORT, min_periods=VOL_SHORT // 2).std()
    long_ = ret.rolling(VOL_LONG, min_periods=VOL_LONG // 4).std()
    ratio = np.log((short / long_).clip(lower=1e-6)).fillna(0.0).clip(-1.5, 1.5).to_numpy()[np.minimum(idx, len(close) - 1)]
    strength = np.abs(2.0 * np.asarray(score, dtype=float) - 1.0)
    return np.column_stack([np.ones(len(strength)), strength, ratio])


@dataclass
class ModelData:
    """Un modèle à rejouer : P(hausse) par jour de signal, segment, et cours journaliers de la cible (index de dates)."""
    target: str
    scores: pd.Series                       # index = date du signal, valeurs = P(hausse)
    segments: pd.Series                     # même index : "test" ou "holdout"
    close: pd.Series


def _daily_features(close: pd.Series, dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pour chaque date de signal : position dans l'index des cours, rendement du lendemain et sigma connue ce jour-là."""
    idx = close.index.searchsorted(dates)
    ret = close.pct_change()
    sigma = ret.rolling(VOL_SHORT, min_periods=VOL_SHORT // 2).std()
    nxt = ret.shift(-1)
    sig = sigma.to_numpy()[np.minimum(idx, len(close) - 1)]
    nx = nxt.to_numpy()[np.minimum(idx, len(close) - 1)]
    nx = np.where(idx >= len(close) - 1, np.nan, nx)
    return idx, nx, sig


def run_bandit(data: ModelData, *, alpha: float = ALPHA, ridge: float = RIDGE, cost_bps: float = COST_BPS) -> pd.Series:
    """Positions (signées, de -1 à +1) du bandit aux dates de signal du HOLDOUT. Préchauffage en ligne sur le segment `test`, puis suite sur le holdout."""
    dates = pd.DatetimeIndex(data.scores.index)
    score = data.scores.to_numpy(dtype=float)
    idx, nx, sigma = _daily_features(data.close, dates)
    x_all = contexts(score, data.close, idx)
    policy = LinUCB(alpha=alpha, ridge=ridge)
    cost = cost_bps / 1e4
    prev = 0.0
    positions: dict[pd.Timestamp, float] = {}
    for i in range(len(score)):
        direction = 0.0 if score[i] == 0.5 else (1.0 if score[i] > 0.5 else -1.0)
        arm = policy.choose(x_all[i])
        size = ARMS[arm]
        position = size * direction
        sig = sigma[i]
        if np.isfinite(nx[i]) and np.isfinite(sig) and sig > 0:
            g = direction * nx[i] / sig
            reward = size * g - 0.5 * REFERENCE_EDGE * size * size - cost * abs(position - prev) / sig
            policy.update(arm, x_all[i], reward)
        prev = position
        if data.segments.iloc[i] == "holdout":
            positions[dates[i]] = position
    return pd.Series(positions, dtype=float)


def run_kelly_ridge(data: ModelData, *, ridge: float = RIDGE) -> pd.Series:
    """Kelly fractionnaire appris, à information COMPLÈTE : régression ridge en ligne de l'espérance `g` (en unités de volatilité) sur le contexte, taille `clip(g_hat / gamma, 0, 1)`.
    Dans un rejeu l'action de l'agent ne change pas les prix : le gain qu'aurait eu n'importe quelle taille est observable après coup, il n'y a donc pas lieu de n'observer que le bras
    joué. Même préchauffage sur `test`, même contexte, mêmes données que le bandit : c'est le même problème avec l'estimateur le moins gourmand en observations."""
    dates = pd.DatetimeIndex(data.scores.index)
    score = data.scores.to_numpy(dtype=float)
    idx, nx, sigma = _daily_features(data.close, dates)
    x_all = contexts(score, data.close, idx)
    A, b = ridge * np.eye(N_FEATURES), np.zeros(N_FEATURES)
    positions: dict[pd.Timestamp, float] = {}
    for i in range(len(score)):
        direction = 0.0 if score[i] == 0.5 else (1.0 if score[i] > 0.5 else -1.0)
        g_hat = float(np.linalg.solve(A, b) @ x_all[i])
        size = float(min(1.0, max(0.0, g_hat / REFERENCE_EDGE)))
        if np.isfinite(nx[i]) and np.isfinite(sigma[i]) and sigma[i] > 0:
            g = direction * nx[i] / sigma[i]
            A += np.outer(x_all[i], x_all[i])
            b += g * x_all[i]
        if data.segments.iloc[i] == "holdout":
            positions[dates[i]] = size * direction
    return pd.Series(positions, dtype=float)


def replay(positions_at_signals: pd.Series, close: pd.Series, *, cost_bps: float = COST_BPS) -> dict:
    """Rejeu d'une série de positions (une par jour de signal, horizon 1, décalage d'une barre comme `simulate`) : rendements nets de frais, Sharpe, exposition, rotation."""
    params = sim_engine.SimParams(spread_bps=cost_bps / 2, commission_bps=cost_bps / 2)
    first, last = positions_at_signals.index.min(), positions_at_signals.index.max()
    last_pos = close.index.searchsorted(last)
    end_pos = min(last_pos + params.execution_lag_bars, len(close.index) - 1)
    daily = close.index[(close.index >= first) & (close.index <= close.index[end_pos])]
    ret = close.reindex(daily).pct_change().fillna(0.0)
    exposure = sim_engine._build_exposure(pd.DatetimeIndex(positions_at_signals.index), positions_at_signals.to_numpy(dtype=float), daily, 1, params)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    net = exposure * ret - turnover * (params.spread_bps + params.commission_bps) / 1e4
    sharpe = simmetrics.sharpe_ratio(net)
    if not np.isfinite(sharpe) and float(net.abs().sum()) == 0.0:
        sharpe = 0.0                                                    # jamais en position : ni gain ni risque, pas une valeur manquante
    return {"sharpe": sharpe, "mean_exposure": float(exposure.abs().mean()), "turnover": float(turnover.sum() / max(len(daily) / 252, 1e-9)),
            "total_return": float((1 + net).prod() - 1), "n_days": len(daily)}


def heuristic_positions(scores: pd.Series, name: str) -> pd.Series:
    params = HEURISTICS[name]
    return pd.Series(sim_engine._position_from_score(scores.to_numpy(dtype=float), params), index=scores.index)


def compare_model(data: ModelData, *, cost_bps: float = COST_BPS) -> dict:
    """Sharpe net du bandit et des heuristiques sur le holdout d'un modèle (mêmes jours, mêmes frais)."""
    holdout = data.scores[data.segments == "holdout"]
    if len(holdout) < 30:
        return {"ok": False, "reason": "holdout trop court"}
    out: dict = {"ok": True, "target": data.target, "n_holdout": len(holdout)}
    out["bandit"] = replay(run_bandit(data, cost_bps=cost_bps), data.close, cost_bps=cost_bps)
    out["kelly_ridge"] = replay(run_kelly_ridge(data), data.close, cost_bps=cost_bps)
    for name in HEURISTICS:
        out[name] = replay(heuristic_positions(holdout, name), data.close, cost_bps=cost_bps)
    return out


def summarize(results: list[dict], candidate: str = "bandit", baselines: tuple[str, ...] = tuple(HEURISTICS), n_boot: int = 4000, seed: int = 7,
              ci_level: float = 0.95) -> dict:
    """Écart de Sharpe (`candidate` - heuristique) sur l'ensemble des modèles : moyenne, médiane, part positive, test des signes, intervalle de bootstrap de la moyenne (`ci_level`).
    `beats_all` : l'intervalle exclut 0 du bon côté contre TOUTES les heuristiques."""
    from scipy import stats

    rng = np.random.default_rng(seed)
    lo, hi = (1 - ci_level) / 2, 1 - (1 - ci_level) / 2
    ok = [r for r in results if r.get("ok") and np.isfinite(r[candidate]["sharpe"])]
    out: dict = {"candidate": candidate, "n_models": len(ok), "mean_sharpe": float(np.mean([r[candidate]["sharpe"] for r in ok])) if ok else float("nan"), "versus": {}}
    for name in baselines:
        pairs = [(r[candidate]["sharpe"], r[name]["sharpe"]) for r in ok if np.isfinite(r[name]["sharpe"])]
        if len(pairs) < 10:
            continue
        diff = np.array([a - b for a, b in pairs])
        boots = rng.choice(diff, size=(n_boot, len(diff)), replace=True).mean(axis=1)
        wins = int((diff > 0).sum())
        out["versus"][name] = {"n": len(diff), "mean_diff": float(diff.mean()), "median_diff": float(np.median(diff)), "share_better": wins / len(diff),
                               "ci": (float(np.quantile(boots, lo)), float(np.quantile(boots, hi))),
                               "sign_test_p": float(stats.binomtest(wins, int((diff != 0).sum()), 0.5).pvalue) if (diff != 0).any() else 1.0,
                               "baseline_mean_sharpe": float(np.mean([b for _, b in pairs]))}
    out["beats_all"] = bool(out["versus"]) and all(v["ci"][0] > 0 for v in out["versus"].values())
    return out
