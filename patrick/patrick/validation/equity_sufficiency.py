"""CHANTIER (feature/equity-asset-class) -- badge d'insuffisance de donnees
pour la classe "actions individuelles" (`config.equity_universe.
EQUITY_UNIVERSE`) : seuil ABSOLU de jours de cotation disponibles avant
d'envisager tout entrainement, INDEPENDANT du garde-fou horizon existant
(`validation/feasibility.py`, qui exige un historique proportionnel a
l'horizon walk-forward choisi ET ne s'applique qu'a une cible DEJA mise en
cache localement, `data/store.py`).

Difference structurelle avec `feasibility.py`/`data/freshness.py` : ces
deux modules lisent EXCLUSIVEMENT le data lake local (jamais de reseau) --
principe correct pour une cible qui a deja servi au moins une fois, mais
inapplicable ici. Une action neuve (jamais lancee comme cible, ex. une IPO
recente comme D.A.T.E) n'a par construction AUCUNE entree dans
`data/store.py` -- rester limite au store laisserait ce badge bloque a
"jamais verifie" pour precisement le cas qu'il doit couvrir : evaluer une
action AVANT de lancer un run dessus. Ce module interroge donc yfinance
directement, via `data/sources/yfinance_source.download_one` (deja mis en
cache localement par ce dernier, `LocalCache`, 7 jours) -- jamais un appel
reseau brut non mis en cache."""
from __future__ import annotations

from dataclasses import dataclass

from patrick.config.defaults import DEFAULT_MIN_TRADING_DAYS_FOR_EQUITY
from patrick.data.sources import yfinance_source

# Date de depart tres ancienne pour capturer l'integralite de l'historique
# disponible d'une action, quelle que soit sa date reelle de premiere
# cotation -- le nombre de jours de cotation compte est celui REELLEMENT
# renvoye par yfinance, jamais une valeur deduite de
# `config.equity_universe.EQUITY_UNIVERSE[...]["first_listed"]` (qui reste
# une metadonnee informative, voir son propre docstring).
_FULL_HISTORY_START = "1970-01-01"


@dataclass(frozen=True)
class DataSufficiencyResult:
    symbol: str
    sufficient: bool
    n_trading_days: int
    min_required: int
    reason: str


def check_data_sufficiency(
    symbol: str,
    min_trading_days: int = DEFAULT_MIN_TRADING_DAYS_FOR_EQUITY,
    start: str = _FULL_HISTORY_START,
) -> DataSufficiencyResult:
    """Jamais d'exception : une action introuvable chez yfinance (ex.
    D.A.T.E avant sa cotation effective le 2026-09-25 -- `download_one`
    renvoie `None` dans ce cas, deja gere par son propre `try/except`) est
    simplement traitee comme 0 jour de cotation disponible, jamais comme
    une erreur serveur -- meme discipline que `data/freshness.py::
    compute_freshness` (etat explicite, jamais un crash)."""
    series = yfinance_source.download_one(symbol, start)
    n_trading_days = 0 if series is None else int(series.dropna().shape[0])
    sufficient = n_trading_days >= min_trading_days

    if sufficient:
        reason = (f"{n_trading_days} jours de cotation disponibles "
                   f"(seuil minimum : {min_trading_days}).")
    else:
        reason = (
            f"Historique insuffisant pour {symbol} : {n_trading_days} jour(s) de cotation "
            f"disponible(s), {min_trading_days} requis avant tout entraînement "
            "(l'affichage prix/fondamentaux reste consultable sous ce seuil)."
        )
    return DataSufficiencyResult(
        symbol=symbol, sufficient=sufficient, n_trading_days=n_trading_days,
        min_required=min_trading_days, reason=reason,
    )
