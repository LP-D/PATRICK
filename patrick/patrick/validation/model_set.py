"""Ensemble de confiance de modèles et test SPA de Hansen sur une paire cible × horizon (FO1 et FO2 du 25/11).

Une paire a souvent des dizaines de runs ; le champion est le meilleur d'entre eux au holdout, donc le gagnant d'une course : son avance
peut n'être que du bruit. Deux lectures, sur les pertes de Brier de P(hausse) au holdout, dates communes à tous les candidats :

- **MCS** (Model Confidence Set, Hansen-Lunde-Nason 2011) : l'ensemble des modèles qu'on ne peut PAS distinguer statistiquement du
  meilleur, au seuil `size` (10 %). Un MCS de 12 modèles dit que le champion n'a rien de spécial parmi eux ; un MCS d'un seul modèle dit
  que son avance tient. Le fonds peut moyenner les probabilités de l'ensemble au lieu de parier sur un seul.
- **SPA** (Superior Predictive Ability, Hansen 2005) : « le MEILLEUR des candidats bat-il vraiment la référence, compte tenu de TOUS ceux
  qu'on a essayés ? ». La référence est le pile ou face (P(hausse) = 0,5) : une probabilité qui ne bat pas 0,5 en Brier n'apporte rien.
  p-value « consistante » de Hansen ; sous 5 %, au moins un modèle bat vraiment le hasard, après la recherche entière.

Tout est calculé à la demande sur les prédictions déjà stockées (aucun entraînement, aucune lecture du holdout comptée comme sélection :
c'est une lecture diagnostique). Bootstrap stationnaire par blocs (les pertes d'un horizon h se chevauchent : bloc = max(h, 5)).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

MAX_MODELS = 25
MIN_OBS = 40


def candidate_losses(conn: sqlite3.Connection, target: str, horizon: int, split: str = "holdout", max_models: int = MAX_MODELS) -> pd.DataFrame:
    """Pertes de Brier (P(hausse) contre hausse réalisée) de l'essai retenu de chaque run terminé de la paire, sur les dates communes.

    Colonnes = identifiants de run (les plus récents d'abord, au plus `max_models`), lignes = dates."""
    runs = [r[0] for r in conn.execute(
        "SELECT r.run_id FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
        "WHERE r.target = ? AND r.horizon = ? AND r.status = 'done' ORDER BY r.started_at DESC LIMIT ?", (target, horizon, max_models))]
    series = {}
    for run_id in runs:
        rows = conn.execute(
            "SELECT p.ts, p.y_true, p.p_up FROM prediction p JOIN trial t ON t.trial_id = p.trial_id AND t.is_best = 1 "
            "WHERE t.run_id = ? AND p.split = ? AND p.p_up IS NOT NULL AND p.y_true IS NOT NULL", (run_id, split)).fetchall()
        if len(rows) < MIN_OBS:
            continue
        frame = pd.DataFrame(rows, columns=["ts", "y", "p"])
        frame["ts"] = frame["ts"].astype(str).str[:10]
        frame = frame.drop_duplicates("ts", keep="last").set_index("ts")
        up = (frame["y"].astype(float) >= 2).astype(float)
        series[run_id] = (frame["p"].astype(float) - up) ** 2
    if not series:
        return pd.DataFrame()
    losses = pd.DataFrame(series).dropna()
    return losses.sort_index()


def _benchmark_loss(conn: sqlite3.Connection, target: str, horizon: int, index: pd.Index, split: str) -> pd.Series:
    """Perte du pile ou face (P = 0,5) : 0,25 à chaque date, quelle que soit l'issue."""
    return pd.Series(0.25, index=index)


def evaluate(conn: sqlite3.Connection, target: str, horizon: int, *, split: str = "holdout", size: float = 0.10, reps: int = 1000,
             seed: int = 0) -> dict:
    """`{n_models, n_obs, champion_run, mcs: {included, pvalues}, spa: {p_consistent, p_lower, p_upper, best}, reason}`."""
    from arch.bootstrap import MCS, SPA

    losses = candidate_losses(conn, target, horizon, split)
    champion = conn.execute("SELECT run_id FROM champion WHERE target = ? AND horizon = ?", (target, horizon)).fetchone()
    out: dict = {"target": target, "horizon": int(horizon), "split": split, "n_models": int(losses.shape[1]), "n_obs": len(losses),
                 "champion_run": champion[0] if champion else None, "mcs": None, "spa": None, "reason": None}
    if losses.shape[1] < 2 or len(losses) < MIN_OBS:
        out["reason"] = (f"{losses.shape[1]} modèle(s) avec au moins {MIN_OBS} prédictions communes au {split} : "
                         "il en faut deux pour comparer")
        return out
    block = max(int(horizon), 5)
    mcs = MCS(losses.to_numpy(), size=size, reps=reps, block_size=block, method="R", bootstrap="stationary", seed=seed)
    mcs.compute()
    cols = list(losses.columns)
    included = sorted(cols[i] for i in mcs.included)
    pvals = {cols[int(i)]: float(p) for i, p in mcs.pvalues["Pvalue"].items()}
    out["mcs"] = {"size": size, "included": included, "pvalues": pvals,
                  "mean_loss": {c: float(losses[c].mean()) for c in cols}, "champion_in": (champion[0] in included) if champion else None}
    bench = _benchmark_loss(conn, target, horizon, losses.index, split)
    spa = SPA(bench.to_numpy(), losses.to_numpy(), reps=reps, block_size=block, bootstrap="stationary", studentize=True, seed=seed)
    spa.compute()
    pv = spa.pvalues
    best = cols[int(np.argmin(losses.mean().to_numpy()))]
    out["spa"] = {"benchmark": "pile ou face (P = 0,5)", "p_consistent": float(pv["consistent"]), "p_lower": float(pv["lower"]),
                  "p_upper": float(pv["upper"]), "best": best, "best_loss": float(losses[best].mean()), "benchmark_loss": 0.25}
    return out
