"""CHANTIER (feature/equity-asset-class, suite) -- injection des
fondamentaux actions comme FEATURE d'entrainement est BLOQUEE : yfinance ne
fournit aucune source POINT-IN-TIME pour les fondamentaux (uniquement
l'etat ACTUEL, potentiellement retraite, des 4 derniers exercices annuels /
6 derniers trimestres -- verifie empiriquement le 2026-09-19,
`data/sources/fundamentals_source.py`). Les reindexer sur `fiscalDateEnding`
(sans decalage de publication) introduit un biais look-ahead deja demontre
empiriquement (investigation dediee, tour precedent : une valeur close le
31/12 etait visible des le 02/01 dans la matrice de features).

`build_equity_fundamentals_features` (point d'entree PUBLIC, appele depuis
`pipeline/engine.py::build_base_feature_pool` quand
`config.features.enable_fundamentals_features` est True) leve donc TOUJOURS
`FundamentalsFeaturesNotSupportedError` -- garde "le plus en amont possible"
complementaire a celui de `cli.py` (validation a la soumission, YAML/
--config, seule voie de soumission reelle du flag aujourd'hui : aucun champ
formulaire ni option CLI positive ne l'expose). `_reindex_fundamentals`
(prive) CONSERVE la logique de reindexation/ffill elle-meme -- jamais
appelee tant que ce garde est actif, gardee pour une eventuelle source
point-in-time future (ex. Alpha Vantage EARNINGS avec `reportedDate`)."""
from __future__ import annotations

import pandas as pd

from patrick.config.equity_universe import is_equity_symbol
from patrick.data.sources import fundamentals_source


class FundamentalsFeaturesNotSupportedError(RuntimeError):
    """Levee par `build_equity_fundamentals_features` : aucune source
    point-in-time pour les fondamentaux actions n'existe dans ce projet --
    voir le docstring du module pour la justification complete."""


def _reindex_fundamentals(target_symbol: str, index: pd.Index) -> pd.DataFrame:
    """Reindexation/ffill des fondamentaux sur `index` -- logique PRIVEE,
    jamais appelee depuis le pipeline tant que `build_equity_fundamentals_
    features` reste bloquee. DataFrame vide (jamais d'exception) si
    `target_symbol` n'est pas une action de `config.equity_universe.
    EQUITY_UNIVERSE`, ou si aucun fondamental n'a pu etre recupere."""
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


def build_equity_fundamentals_features(target_symbol: str, index: pd.Index) -> pd.DataFrame:
    """Point d'entree PUBLIC -- leve TOUJOURS `FundamentalsFeaturesNotSupportedError`
    (voir le docstring du module). `data/sources/fundamentals_source.
    fetch_fundamentals` reste directement utilisable pour un AFFICHAGE
    (jamais comme feature datee) -- voir `webapp/app.py::equities_page`,
    qui ne passe pas par cette fonction."""
    raise FundamentalsFeaturesNotSupportedError(
        f"Fondamentaux actions desactives comme feature d'entrainement pour {target_symbol} : "
        "yfinance ne fournit aucune source point-in-time (etat actuel seulement, potentiellement "
        "retraite -- 4 exercices annuels / 6 trimestres). Les reindexer sur fiscalDateEnding "
        "introduit un biais look-ahead deja demontre empiriquement. "
        "Voir data/sources/fundamentals_source.py et features/equity_fundamentals.py."
    )
