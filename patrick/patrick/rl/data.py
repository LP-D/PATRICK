"""États et rendements du RL, sans regard vers l'avenir.

- Variables : la réserve « de base » du pipeline (`pipeline/engine.build_base_feature_pool`), causale par construction (fenêtres
  glissantes et retards, aucun paramètre estimé sur tout l'échantillon). Les niveaux bruts (non stationnaires) en sont retirés.
  EGARCH, HMM et interactions sont exclus : ajustés sur un échantillon, ils auraient besoin d'un réajustement pli par pli.
- Rendement : `fwd_ret[i] = P[i+1] / P[i] − 1`, le rendement qu'on touche en prenant une position à la date i.
- Sélection et mise à l'échelle : par pli, sur les lignes d'ENTRAÎNEMENT seulement (`select_columns`, `scale_fold`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.preprocessing import RobustScaler

from patrick.config import defaults as D
from patrick.rl.config import RLRunConfig

MIN_COVERAGE = 0.6          # une variable doit être renseignée sur au moins 60 % des dates (sinon écartée)
ROW_COVERAGE = 0.9          # une date n'entre dans l'échantillon que si 90 % des variables retenues sont renseignées
DECORRELATE_ABOVE = 0.9     # à la sélection, une variable trop corrélée à une déjà retenue est sautée


class RLDataError(ValueError):
    """Données inutilisables pour le RL : message affichable tel quel."""


@dataclass
class RLData:
    dates: pd.DatetimeIndex          # date de décision de chaque ligne (n)
    features: pd.DataFrame           # (n, k) variables causales, non mises à l'échelle
    fwd_ret: np.ndarray              # (n,) rendement de i à i+1
    price: pd.Series                 # (n + 1) cours, du premier jour utilisable au dernier
    target_col: str
    warnings: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.dates)


def build_rl_data(raw: pd.DataFrame, config: RLRunConfig, target_col: str, base_pool_builder=None) -> RLData:
    """`base_pool_builder(raw, run_config, target_col)` : injectable pour les tests (défaut : `build_base_feature_pool`)."""
    if target_col not in raw.columns:
        raise RLDataError(f"Colonne cible absente des données : {target_col}")
    price = pd.to_numeric(raw[target_col], errors="coerce").dropna()
    price = price[~price.index.duplicated(keep="last")].sort_index()
    if len(price) < D.RL_MIN_ROWS:
        raise RLDataError(f"Historique de la cible trop court : {len(price)} cours, il en faut au moins {D.RL_MIN_ROWS}.")
    if bool((price <= 0).any()):
        raise RLDataError("Cours nul ou négatif : le rendement d'une position n'est pas défini sur cette série.")
    if base_pool_builder is None:
        from patrick.pipeline.engine import build_base_feature_pool as base_pool_builder
    pool = base_pool_builder(raw, config.to_run_config(), target_col)
    warnings: list[str] = []
    stationary = [c for c in pool.columns if c not in raw.columns]            # sans les niveaux bruts
    feats = pool[stationary].reindex(price.index).replace([np.inf, -np.inf], np.nan)
    feats = feats.ffill(limit=5)                                              # comble d'éventuels trous de publication, jamais l'avenir
    keep = feats.columns[feats.notna().mean() >= MIN_COVERAGE]
    feats = feats[keep]
    feats = feats.loc[:, feats.nunique(dropna=True) > 1]
    if feats.shape[1] == 0:
        raise RLDataError("Aucune variable exploitable : vérifie les familles de variables choisies.")
    covered = feats.notna().mean(axis=1) >= ROW_COVERAGE
    first = covered.idxmax() if covered.any() else None
    if first is None:
        raise RLDataError("Aucune date n'a assez de variables renseignées.")
    feats = feats.loc[first:]
    price = price.loc[first:]
    fwd = (price.shift(-1) / price - 1.0).iloc[:-1]
    feats = feats.iloc[:-1]
    if len(fwd) < D.RL_MIN_ROWS:
        raise RLDataError(f"Après les fenêtres de calcul des variables il reste {len(fwd)} dates : il en faut au moins {D.RL_MIN_ROWS}.")
    if feats.shape[1] > 400:
        warnings.append(f"{feats.shape[1]} variables disponibles : seule la sélection du pli (max_features) entre dans l'observation.")
    return RLData(dates=pd.DatetimeIndex(fwd.index), features=feats, fwd_ret=fwd.to_numpy(dtype=float), price=price,
                  target_col=target_col, warnings=warnings)


def _rank_matrix(x: np.ndarray) -> np.ndarray:
    return np.apply_along_axis(rankdata, 0, x)


def select_columns(train: pd.DataFrame, fwd_ret: np.ndarray, k: int, method: str = "correlation") -> list[str]:
    """Colonnes retenues d'après les SEULES lignes d'entraînement. `correlation` : |corrélation de rang| avec le rendement de la
    période suivante (les lignes de chaque variable remplies à la médiane de l'entraînement), puis écartement des quasi-doublons ;
    `none` : les k premières colonnes dans l'ordre de la réserve."""
    cols = list(train.columns)
    if method == "none" or len(cols) <= k:
        return cols[:k]
    x = train.to_numpy(dtype=float)
    med = np.nanmedian(x, axis=0)
    x = np.where(np.isnan(x), med, x)
    xr, yr = _rank_matrix(x), rankdata(fwd_ret)
    xr = xr - xr.mean(axis=0)
    yr = yr - yr.mean()
    denom = np.sqrt((xr ** 2).sum(axis=0) * (yr ** 2).sum())
    score = np.abs((xr * yr[:, None]).sum(axis=0) / np.where(denom > 0, denom, np.inf))
    order = np.argsort(-score)
    pool = order[: max(4 * k, 40)]
    chosen: list[int] = []
    corr = np.corrcoef(xr[:, pool].T) if len(pool) > 1 else np.ones((1, 1))
    position_in_pool = {int(c): i for i, c in enumerate(pool)}
    for pos, col in enumerate(pool):
        if all(abs(corr[pos, position_in_pool[c]]) < DECORRELATE_ABOVE for c in chosen):
            chosen.append(int(col))
        if len(chosen) == k:
            break
    if len(chosen) < k:                       # tout est redondant : on complète par le classement brut
        for col in pool:
            if int(col) not in chosen:
                chosen.append(int(col))
            if len(chosen) == k:
                break
    return [cols[i] for i in chosen]


def scale_fold(train: pd.DataFrame, others: pd.DataFrame, columns: list[str], clip: float = 5.0) -> tuple[np.ndarray, np.ndarray]:
    """Mise à l'échelle robuste (médiane / interquartile) ajustée sur l'entraînement ; valeurs manquantes -> 0 (neutre) ; bornes ±clip."""
    scaler = RobustScaler()
    med = train[columns].median()
    a = scaler.fit_transform(train[columns].fillna(med).to_numpy(dtype=float))
    b = scaler.transform(others[columns].fillna(med).to_numpy(dtype=float))
    return (np.clip(np.nan_to_num(a), -clip, clip).astype(np.float32), np.clip(np.nan_to_num(b), -clip, clip).astype(np.float32))
