"""Collecte des résultats d'un run et export CSV/xlsx — remplace le hack "push
chaque checkpoint sur une branche Git" de Colab par une simple écriture disque,
la machine étant persistante."""
from __future__ import annotations

import os

import pandas as pd


class Leaderboard:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, **kwargs) -> None:
        self.rows.append(kwargs)

    def as_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def best(self, metric: str = "F1_dir") -> dict | None:
        df = self.as_df()
        if df.empty:
            return None
        return df.sort_values(metric, ascending=False).iloc[0].to_dict()

    def top_k(self, k: int, metric: str = "F1_dir",
              group_cols: tuple[str, ...] = ("horizon", "regime", "N", "sampler", "algo")) -> list[dict]:
        df = self.as_df()
        if df.empty:
            return []
        cols = [c for c in group_cols if c in df.columns]
        agg = df.groupby(cols)[metric].mean().reset_index().sort_values(metric, ascending=False)
        return agg.head(k).to_dict("records")

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
