"""Contexte partagé par les sections d'analyse : connexion, frame de l'essai, paramètres de la requête."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from patrick.analysis.frames import Frame


@dataclass
class Ctx:
    conn: sqlite3.Connection
    fr: Frame
    params: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ paramètres typés (valeurs de requête = chaînes)
    def int_param(self, name: str, default: int, lo: int = 1, hi: int = 10_000) -> int:
        try:
            v = int(self.params.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def float_param(self, name: str, default: float, lo: float = -1e9, hi: float = 1e9) -> float:
        try:
            v = float(self.params.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v)) if np.isfinite(v) else default

    def str_param(self, name: str, default: str | None = None) -> str | None:
        v = self.params.get(name)
        return str(v) if v not in (None, "") else default

    # ------------------------------------------------------------------ jeux de lignes usuels
    def one_path(self, df: pd.DataFrame) -> pd.DataFrame:
        """CPCV : une même date apparaît sur plusieurs chemins ; les vues temporelles gardent un seul chemin (`path` demandé, sinon le
        premier). Walk-forward : inchangé."""
        if not self.fr.is_cpcv or df.empty or (df["path"] < 0).all():
            return df
        wanted = self.int_param("path", int(df.loc[df["path"] >= 0, "path"].min()), lo=0, hi=10_000)
        sub = df[df["path"] == wanted]
        return sub if not sub.empty else df[df["path"] == df.loc[df["path"] >= 0, "path"].min()]

    def evaluated(self, splits: tuple[str, ...] = ("test", "holdout")) -> pd.DataFrame:
        """Prédictions test/holdout dont la direction réelle est connue, triées par date, un seul chemin CPCV."""
        d = self.fr.df
        d = d[d["split_name"].isin(splits) & d["ut"].notna()]
        return self.one_path(d).sort_values(["ts", "path"], kind="mergesort")

    @property
    def horizon(self) -> int:
        return self.fr.horizon


def iso(ts) -> str | None:
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return None
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None
