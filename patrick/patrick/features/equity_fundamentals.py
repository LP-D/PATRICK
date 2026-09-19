"""CHANTIER (feature/equity-asset-class) -- fondamentaux actions reindexes
sur l'index quotidien du pool de features, appele depuis
`pipeline/engine.py::build_base_feature_pool` uniquement quand
`config.features.enable_fundamentals_features` est True (meme pattern que
`features/guida.py::build_guida_estimated_features` avec
`enable_guida_features`).

Reindexation : chaque `(fiscalDateEnding, metric, value)` est place a sa
date de fin d'exercice puis propage vers l'avant (`ffill`) jusqu'a la
publication suivante -- une approximation documentee (voir les mises en
garde de `data/sources/fundamentals_source.py`, non repetees ici) : AUCUN
decalage n'est applique pour le delai de publication reel, donc une valeur
peut apparaitre comme "connue" a sa date de fin d'exercice alors qu'elle
n'a ete rendue publique que plusieurs semaines plus tard."""
from __future__ import annotations

import pandas as pd

from patrick.config.equity_universe import is_equity_symbol
from patrick.data.sources import fundamentals_source


def build_equity_fundamentals_features(target_symbol: str, index: pd.Index) -> pd.DataFrame:
    """DataFrame vide (jamais d'exception) si `target_symbol` n'est pas une
    action de `config.equity_universe.EQUITY_UNIVERSE` (fondamentaux non
    applicables a un indice/une commodite/une serie macro) ou si aucun
    fondamental n'a pu etre recupere (titre trop recent, ex. D.A.T.E avant
    son premier exercice publie)."""
    if not is_equity_symbol(target_symbol):
        return pd.DataFrame(index=index)

    long = fundamentals_source.fetch_fundamentals(target_symbol)
    if long.empty:
        return pd.DataFrame(index=index)

    prefix = target_symbol.replace(".", "_")
    out = pd.DataFrame(index=index)
    for metric, sub in long.groupby("metric"):
        sub = sub.sort_values("fiscalDateEnding")
        s = pd.Series(
            sub["value"].to_numpy(dtype=float),
            index=pd.to_datetime(sub["fiscalDateEnding"]),
        )
        s = s[~s.index.duplicated(keep="last")]
        col = f"{prefix}_{metric}_fundamental".replace(" ", "_")
        out[col] = s.reindex(out.index, method="ffill")
    return out
