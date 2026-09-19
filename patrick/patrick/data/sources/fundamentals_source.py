"""CHANTIER (feature/equity-asset-class) -- fondamentaux actions, collecte
via yfinance (`Ticker.quarterly_income_stmt`), HORS pipeline ML par defaut
(voir `config.schema.FeaturesConfig.enable_fundamentals_features`, meme
pattern que `enable_guida_features`).

MISES EN GARDE EXPLICITES -- a lire avant tout usage de ces donnees comme
feature datee (`features/equity_fundamentals.py`) :

1. AUCUNE garantie de non-revision. yfinance expose l'etat ACTUEL des
   comptes tels que rapportes par la source sous-jacente : un exercice
   fiscal deja publie peut etre retraite a posteriori (correction
   comptable, ajustement post-cloture) sans que ce module ne le detecte ni
   n'en date la revision -- la valeur renvoyee aujourd'hui pour un
   `fiscalDateEnding` donne n'est pas necessairement celle qui etait
   connue a l'epoque.

2. Le delai reel de publication n'est PAS verifie ici. `fiscalDateEnding`
   est la date de FIN D'EXERCICE comptable (ex. cloture trimestrielle),
   PAS la date a laquelle l'information est devenue publiquement
   disponible (qui suit toujours de plusieurs semaines la cloture). Toute
   feature construite sur `fiscalDateEnding` sans decalage explicite
   introduit un risque de look-ahead (information utilisee avant sa
   publication reelle) -- non resolu a ce stade, documente comme limite
   connue.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from patrick.cache_manager import LocalCache

FUNDAMENTALS_COLUMNS = ["fiscalDateEnding", "metric", "value"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)


def fetch_fundamentals(symbol: str) -> pd.DataFrame:
    """Fondamentaux trimestriels d'une action, au format LONG
    (`fiscalDateEnding`, `metric`, `value`) -- un DataFrame VIDE (jamais
    d'exception) si yfinance ne renvoie rien (titre trop recent, pas encore
    de publication -- ex. D.A.T.E avant son premier exercice publie, ou
    tout ticker que yfinance ne reconnait pas).

    Mis en cache localement 7 jours (`LocalCache`, meme convention que
    `yfinance_source.download_one`) : des fondamentaux trimestriels ne
    changent pas d'un appel a l'autre dans cette fenetre, inutile de
    re-interroger yfinance a chaque chargement de page."""
    key = f"fundamentals_{symbol.replace('.', '_')}"
    cache = LocalCache()
    cached = cache.load_dataframe(key, max_age_days=7)
    if cached is not None:
        return cached

    try:
        stmt = yf.Ticker(symbol).quarterly_income_stmt
    except Exception:
        return _empty()

    if stmt is None or stmt.empty:
        out = _empty()
        cache.save_dataframe(key, out, max_age_days=7)
        return out

    long = stmt.T.reset_index().rename(columns={"index": "fiscalDateEnding"})
    long = long.melt(id_vars="fiscalDateEnding", var_name="metric", value_name="value")
    long = long.dropna(subset=["value"])
    long["fiscalDateEnding"] = pd.to_datetime(long["fiscalDateEnding"]).dt.strftime("%Y-%m-%d")
    long = long[FUNDAMENTALS_COLUMNS].reset_index(drop=True)
    cache.save_dataframe(key, long, max_age_days=7)
    return long
