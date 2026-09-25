"""Collects a run's results and exports CSV/xlsx -- replaces the Colab hack of
"push every checkpoint to a Git branch" with a plain disk write, now that the
machine is persistent.

Ranking rules (see `tests/test_selection_determinism.py`):
- a configuration is ranked on its walk-forward MEAN over the folds it was
  evaluated on, never on its single best fold (F07: ranking on the max of
  noisy per-fold scores selects the luckiest configuration and inflates the
  reported score);
- ties are broken deterministically -- fewer features first (parsimony),
  then horizon, regime, sampler, algo in ascending order -- so the winner
  never depends on insertion order or on the sort implementation (numpy's
  default quicksort orders ties differently depending on CPU SIMD support).
"""
from __future__ import annotations

import os

import pandas as pd

DEFAULT_GROUP_COLS: tuple[str, ...] = ("horizon", "regime", "N", "sampler", "algo")
_TIEBREAK_ORDER: tuple[str, ...] = ("N", "horizon", "regime", "sampler", "algo")


def rank_configs(df: pd.DataFrame, metric: str, cols: list[str] | tuple[str, ...]) -> pd.DataFrame:
    """Sorts `df` by `metric` descending with the deterministic tie-break
    documented in the module docstring (NaN metric last)."""
    tiebreak = [c for c in _TIEBREAK_ORDER if c in cols] + [c for c in cols if c not in _TIEBREAK_ORDER]
    keys = [metric] + tiebreak
    return df.sort_values(keys, ascending=[False] + [True] * len(tiebreak),
                          kind="mergesort", na_position="last")


class Leaderboard:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, **kwargs) -> None:
        self.rows.append(kwargs)

    def as_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def best(self, metric: str = "F1_dir",
             group_cols: tuple[str, ...] = DEFAULT_GROUP_COLS) -> dict | None:
        top = self.top_k(1, metric=metric, group_cols=group_cols)
        return top[0] if top else None

    def top_k(self, k: int, metric: str = "F1_dir",
              group_cols: tuple[str, ...] = DEFAULT_GROUP_COLS) -> list[dict]:
        df = self.as_df()
        if df.empty or metric not in df.columns:
            return []
        cols = [c for c in group_cols if c in df.columns]
        grouped = df.groupby(cols)[metric]
        agg = grouped.mean().reset_index()
        agg["n_folds"] = grouped.count().values
        return rank_configs(agg, metric, cols).head(k).to_dict("records")

    def export(self, out_dir: str, name: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        df = self.as_df()
        csv_path = os.path.join(out_dir, f"{name}_leaderboard.csv")
        df.to_csv(csv_path, index=False)
        xlsx_path = os.path.join(out_dir, f"{name}_leaderboard.xlsx")
        try:
            df.to_excel(xlsx_path, index=False)
        except Exception as e:
            print(f"  [WARN] export xlsx: {str(e)[:100]}")
        return csv_path
