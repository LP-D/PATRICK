"""Phase 6.2 (P6.2) -- poids d'unicité et bootstrap séquentiel (López de
Prado, "Advances in Financial Machine Learning", chapitre 4). Avec un horizon
`h > 1` et une prédiction par barre, les fenêtres de label se chevauchent :
l'observation à la barre `t` prédit la direction sur `[t, t+h]`, donc deux
observations à moins de `h` barres l'une de l'autre partagent de l'information
(même mouvement de marché sous-jacent en partie compté deux fois) -- les
observations d'entraînement ne sont PAS indépendantes, et la taille
d'échantillon EFFECTIVE est très inférieure à `n`."""
from __future__ import annotations

import numpy as np


def build_indicator_matrix(start_positions: np.ndarray, horizon: int, n_bars: int) -> np.ndarray:
    """`ind[i, t] = True` si l'observation `i` (span `[start_positions[i],
    start_positions[i]+horizon]`, en positions entières sur la grille de
    barres du fold -- pas en dates calendaires) recouvre la barre `t`.
    Matrice dense (n_obs x n_bars) : n_obs est le nombre d'observations
    d'ENTRAÎNEMENT d'un seul fold (quelques centaines), pas tout l'historique
    -- reste tractable en mémoire."""
    n_obs = len(start_positions)
    ind = np.zeros((n_obs, n_bars), dtype=bool)
    for i, start in enumerate(start_positions):
        start = max(int(start), 0)
        end = min(start + horizon, n_bars - 1)
        if end >= start:
            ind[i, start:end + 1] = True
    return ind


def bar_concurrency(ind: np.ndarray) -> np.ndarray:
    """`c[t]` : nombre d'observations dont le span recouvre la barre `t`."""
    return ind.sum(axis=0)


def average_uniqueness(ind: np.ndarray) -> np.ndarray:
    """Unicité moyenne par observation : moyenne de `1/concurrence(t)` sur les
    barres couvertes par cette observation. 1.0 si aucune autre observation ne
    la recouvre (totalement unique), tend vers 0 si beaucoup d'observations se
    chevauchent sur tout son span."""
    concurrency = bar_concurrency(ind)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv_c = np.where(concurrency > 0, 1.0 / concurrency, 0.0)
    n_obs = ind.shape[0]
    u = np.zeros(n_obs)
    counts = ind.sum(axis=1)
    for i in range(n_obs):
        if counts[i] > 0:
            u[i] = inv_c[ind[i]].mean()
    return u


def effective_sample_size(avg_uniqueness: np.ndarray) -> float:
    """Somme des unicités moyennes -- taille d'échantillon EFFECTIVE (P6.2),
    à rapporter à côté de `n` : conditionne l'interprétation de toute métrique
    calculée sur cet échantillon (un F1/MCC sur `n=500` lignes mais
    `n_eff=80` a l'incertitude statistique d'un échantillon de 80, pas 500)."""
    return float(avg_uniqueness.sum())


def sequential_bootstrap(ind: np.ndarray, sample_length: int | None = None,
                          rng: np.random.Generator | None = None) -> np.ndarray:
    """Tirage séquentiel (López de Prado, snippet 4.5) : à chaque étape, la
    probabilité de tirer l'observation `i` est proportionnelle à l'unicité
    moyenne qu'elle AURAIT compte tenu des observations DÉJÀ tirées dans CET
    échantillon -- favorise dynamiquement les observations les moins
    concurrentes avec le tirage en cours (pas seulement entre elles au global,
    ce que ferait un tri statique par unicité). Renvoie les INDICES (dans
    `ind`, donc dans le train du fold), avec répétition possible (bootstrap).

    Coût O(sample_length x n_obs x n_bars) -- assumé, c'est le coût de calcul
    CONNU de cette méthode dans la littérature, pas une régression involontaire
    (cf. rapport P6.2 pour la mesure sur une cible synthétique)."""
    rng = rng if rng is not None else np.random.default_rng()
    n_obs, n_bars = ind.shape
    sample_length = sample_length if sample_length is not None else n_obs
    ind_int = ind.astype(np.int64)
    span_size = ind_int.sum(axis=1)  # nombre de barres couvertes par chaque observation, fixe
    drawn_concurrency = np.zeros(n_bars, dtype=np.int64)
    phi = np.empty(sample_length, dtype=np.int64)
    for k in range(sample_length):
        candidate_concurrency = drawn_concurrency[None, :] + ind_int  # (n_obs, n_bars)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv_c = np.where(candidate_concurrency > 0, 1.0 / candidate_concurrency, 0.0)
        numer = (inv_c * ind_int).sum(axis=1)
        avg_u = np.divide(numer, span_size, out=np.zeros(n_obs), where=span_size > 0)
        total = avg_u.sum()
        prob = avg_u / total if total > 0 else np.full(n_obs, 1.0 / n_obs)
        choice = int(rng.choice(n_obs, p=prob))
        phi[k] = choice
        drawn_concurrency += ind_int[choice]
    return phi
