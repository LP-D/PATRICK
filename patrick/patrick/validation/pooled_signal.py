"""Signal d'une paire cible-horizon, mesuré en regroupant les runs, et test de permutation qui respecte le chevauchement des horizons.

Pourquoi : le F1 d'UN run sur 15 mois de holdout (~270 jours) a un écart-type de bruit de ~0,04 à 1 jour et de ~0,12 (AUC) à 30 jours :
on ne distingue rien run par run, et les 3 400 runs d'une base ne sont que ~500 cibles refaites avec d'autres réglages. Ici : une ligne par
paire (cible, horizon), le score de tous ses runs moyenné date par date, puis un test qui dit si cette AUC dépasse ce que le hasard donne.

Le test décale l'étiquette de façon circulaire (au moins `max(horizon, 5)` lignes) face aux scores au lieu de la mélanger : au-delà de 1
jour les étiquettes se recouvrent (rendement sur h jours), une permutation libre les rendrait indépendantes et le test déclarerait trop
de signaux ; le décalage garde leur autocorrélation. Unilatéral : seule une AUC AU-DESSUS du hasard est une découverte. Les p-values de
plusieurs paires sont corrigées ensemble (Benjamini-Hochberg, `validation/fdr.py`)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from patrick.validation.fdr import benjamini_hochberg

DEFAULT_SHIFTS = 1000
MIN_DATES = 80


def _auc_from_ranks(ranks: np.ndarray, y: np.ndarray) -> float:
    n1 = float(y.sum())
    n0 = float(len(y)) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def shift_test(y, score, horizon: int, n_shift: int = DEFAULT_SHIFTS, seed: int = 7) -> dict:
    """`{auc, p_value, null_sd, n}` : l'AUC de `score` contre la direction `y` (0/1) et la part des décalages circulaires de `y` qui font
    au moins aussi bien. `p_value` est NaN quand la série est trop courte (< `MIN_DATES`), à une seule direction, ou trop courte pour
    des décalages d'au moins `max(horizon, 5)` lignes."""
    y = np.asarray(y, dtype=int).ravel()
    s = np.asarray(score, dtype=float).ravel()
    keep = np.isfinite(s)
    y, s = y[keep], s[keep]
    n = len(y)
    nan = {"auc": float("nan"), "p_value": float("nan"), "null_sd": float("nan"), "n": int(n)}
    if n < MIN_DATES or len(np.unique(y)) < 2:
        return nan
    ranks = rankdata(s)
    auc = _auc_from_ranks(ranks, y)
    low = max(int(horizon), 5)
    high = n - low
    if high <= low:
        return {**nan, "auc": auc}
    rng = np.random.default_rng(seed)
    shifts = rng.integers(low, high, size=n_shift)
    shifted = y[(np.arange(n)[None, :] - shifts[:, None]) % n]
    n1 = float(y.sum())
    null = ((shifted * ranks[None, :]).sum(axis=1) - n1 * (n1 + 1) / 2) / (n1 * (n - n1))
    return {"auc": auc, "p_value": float((1 + (null >= auc).sum()) / (1 + n_shift)), "null_sd": float(null.std()), "n": int(n)}


def pool_scores(frames: list[pd.Series], min_coverage: float = 0.6) -> pd.Series:
    """Moyenne, date par date, des rangs centiles des scores de plusieurs runs (index = dates). Une date n'est gardée que si au moins
    `min_coverage` des runs la couvrent : la moyenne d'un seul run ne doit pas faire croire à un consensus."""
    if not frames:
        return pd.Series(dtype=float)
    table = pd.concat(frames, axis=1, join="outer").sort_index()
    table = table.dropna(thresh=max(1, int(np.ceil(min_coverage * table.shape[1]))))
    return table.rank(pct=True).mean(axis=1)


def test_pair(frames: list[pd.Series], y: pd.Series, horizon: int, n_shift: int = DEFAULT_SHIFTS, seed: int = 7) -> dict:
    """Test d'une paire : `frames` = P(hausse) de chaque run (index = dates), `y` = direction réelle (0/1, index = dates). Renvoie `n_runs`,
    `n_dates`, `auc` (score regroupé), `auc_run_mean` (AUC moyenne d'un run seul, sur les mêmes dates), `p_value`, `null_sd`."""
    pooled = pool_scores(frames)
    common = pooled.index.intersection(y.index)
    out = {"n_runs": len(frames), "n_dates": len(common), "auc": float("nan"), "auc_run_mean": float("nan"),
           "p_value": float("nan"), "null_sd": float("nan")}
    if len(common) < MIN_DATES:
        return out
    yy = y.loc[common].astype(int).to_numpy()
    res = shift_test(yy, pooled.loc[common].to_numpy(), horizon, n_shift, seed)
    out.update({"auc": res["auc"], "p_value": res["p_value"], "null_sd": res["null_sd"]})
    singles = []
    for frame in frames:
        both = frame.dropna().index.intersection(common)
        if len(both) >= MIN_DATES and len(np.unique(y.loc[both])) == 2:
            singles.append(_auc_from_ranks(rankdata(frame.loc[both].to_numpy()), y.loc[both].astype(int).to_numpy()))
    if singles:
        out["auc_run_mean"] = float(np.mean(singles))
    return out


def adjust(results: dict[str, dict], alpha: float = 0.10) -> dict[str, dict]:
    """Ajoute `q_value` et `significant` (Benjamini-Hochberg au niveau `alpha`) à `{clé: résultat de test_pair}` ; les p-values NaN sont
    ignorées (la paire reste dans le résultat, sans q-value)."""
    adjusted = benjamini_hochberg({k: v["p_value"] for k, v in results.items()}, alpha=alpha)
    table = adjusted.get("results", {})
    return {k: {**v, "q_value": table.get(k, {}).get("adjusted_p_value"), "significant": bool(table.get(k, {}).get("significant", False))}
            for k, v in results.items()}
