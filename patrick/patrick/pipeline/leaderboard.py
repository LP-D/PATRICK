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

import numpy as np
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

    def _aggregate(self, metric: str, group_cols: tuple[str, ...]):
        """(one row per configuration: mean, number of folds, standard error `_se`; the grouping columns kept) or (None, [])."""
        df = self.as_df()
        if df.empty or metric not in df.columns:
            return None, []
        cols = [c for c in group_cols if c in df.columns]
        grouped = df.groupby(cols)[metric]
        agg = grouped.mean().reset_index()
        agg["n_folds"] = grouped.count().values
        agg["_se"] = grouped.std(ddof=1).fillna(0.0).values / np.sqrt(np.maximum(agg["n_folds"].values, 1))
        return agg, cols

    @staticmethod
    def _one_se_first(ranked: pd.DataFrame, cols: list[str], metric: str) -> pd.DataFrame:
        """`ranked` (best mean first) with the parsimony rule's choice moved to the top: among the configurations whose
        mean is within one standard error of the best one, the simplest (fewest features, then the higher mean). Needs
        `N` among the grouping columns and at least two folds for the best configuration (no standard error otherwise)."""
        head = ranked.iloc[0]
        if "N" not in cols or head["n_folds"] < 2:
            return ranked
        near = ranked[ranked[metric] >= head[metric] - head["_se"] - 1e-12]
        others = [c for c in _TIEBREAK_ORDER if c in cols and c != "N"]
        chosen = near.sort_values(["N", metric] + others, ascending=[True, False] + [True] * len(others),
                                  kind="mergesort").index[0]
        return pd.concat([ranked.loc[[chosen]], ranked.drop(index=chosen)])

    def best(self, metric: str = "F1_dir", group_cols: tuple[str, ...] = DEFAULT_GROUP_COLS,
             one_se: bool = False) -> dict | None:
        """The configuration of highest walk-forward mean. `one_se`: among the configurations whose mean is within one
        standard error of the best one, the SIMPLEST (fewest features, then the higher mean) -- with hundreds of
        near-equal candidates the plain maximum is noise. Needs `N` among the grouping columns and at least two
        folds for the best configuration (no standard error otherwise: the plain maximum)."""
        top = self.top_k(1, metric=metric, group_cols=group_cols, one_se=one_se)
        return top[0] if top else None

    def top_k(self, k: int, metric: str = "F1_dir", group_cols: tuple[str, ...] = DEFAULT_GROUP_COLS,
              one_se: bool = False) -> list[dict]:
        """The `k` configurations of highest mean; with `one_se` the parsimony rule's choice (see `best`) comes first and
        the others follow by mean."""
        agg, cols = self._aggregate(metric, group_cols)
        if agg is None:
            return []
        ranked = rank_configs(agg, metric, cols)
        if one_se:
            ranked = self._one_se_first(ranked, cols, metric)
        return ranked.head(k).drop(columns="_se").to_dict("records")

    def export(self, out_dir: str, name: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        df = self.as_df()
        csv_path = os.path.join(out_dir, f"{name}_leaderboard.csv")
        df.to_csv(csv_path, index=False)
        xlsx_path = os.path.join(out_dir, f"{name}_leaderboard.xlsx")
        try:
            df.to_excel(xlsx_path, index=False)
        except (ImportError, OSError, ValueError) as e:
            print(f"  [WARN] export xlsx: {str(e)[:100]}")
        return csv_path
