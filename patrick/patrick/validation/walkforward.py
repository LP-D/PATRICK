"""Construction des coupures de walk-forward en fenêtre expansive — identique dans
tous les notebooks du projet VIX : `min_train_frac` du fold 1, puis `n_wf_folds`
segments égaux de test jusqu'à la fin de l'historique."""
from __future__ import annotations

import pandas as pd


def build_fold_cuts(all_dates: pd.DatetimeIndex, n_wf_folds: int = 5,
                     min_train_frac: float = 0.40) -> list[int]:
    n_obs = len(all_dates)
    first_cut = int(n_obs * min_train_frac)
    test_span = (n_obs - first_cut) // n_wf_folds
    fold_cuts = [first_cut + k * test_span for k in range(n_wf_folds + 1)]
    fold_cuts[-1] = n_obs
    return fold_cuts


def describe_folds(all_dates: pd.DatetimeIndex, fold_cuts: list[int]) -> None:
    for k in range(len(fold_cuts) - 1):
        cut, nxt = fold_cuts[k], fold_cuts[k + 1]
        print(f"  Fold {k+1}: train -> {all_dates[cut-1].date()} | "
              f"test {all_dates[cut].date()} -> {all_dates[nxt-1].date()}")
