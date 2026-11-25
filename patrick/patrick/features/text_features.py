"""Variables texte de l'entraînement (A4, `FeaturesConfig.enable_text_features`).

Deux familles, toutes deux par `text/aggregate.py` (une nouvelle n'atteint une séance qu'à partir de sa clôture-précédente : aucune
variable d'une séance t n'utilise d'information postérieure à t ; les nouvelles vues plus de 72 h après leur publication sont écartées) :
- `news_*` : sentiment (lexique) des nouvelles rattachées à la cible, sur 1, 5 et 20 séances, attention et nouveauté ;
- `cb_*` : ton faucon / colombe de TOUS les communiqués de banque centrale (Fed, BCE, BoE, BoC, BRI), quelle que soit la cible.

Porte : `text/readiness.require_history` (250 séances, 60 jours avec nouvelles), pour la cible et pour le magasin entier. Tant qu'elle
n'est pas franchie, le run s'arrête avec `NewsHistoryTooShort` au lieu d'apprendre sur des colonnes presque vides. Les valeurs passées ne
changent pas quand le magasin grandit (une nouvelle rattrapée aujourd'hui a une heure de connaissance d'aujourd'hui) : un run se rejoue
et ses prédictions quotidiennes recalculent les mêmes colonnes.
"""
from __future__ import annotations

import pandas as pd

from patrick.text import aggregate, readiness, store

HORIZONS = (1, 5, 20)


def _central_bank_tone(conn, days: pd.DatetimeIndex) -> pd.DataFrame:
    from patrick.text import service

    readiness.require_history(conn, None)
    items = store.load_items(conn, kinds=["central_bank"], max_lag_hours=readiness.MAX_LAG_HOURS)
    scores = store.load_scores(conn, service.TONE, service.TONE_VERSION)[["item_id", "score"]]
    merged = items.merge(scores, on="item_id", how="left")
    return aggregate.sentiment_features(merged[["known_at", "score"]], days, horizons=HORIZONS, prefix="cb")


def store_fingerprint() -> str:
    """État du magasin de nouvelles (nombre et dernier identifiant des nouvelles et des notes) pour la clé du cache de variables."""
    from patrick.tracking import db as trackdb

    conn = trackdb.connect()
    try:
        n, last = conn.execute("SELECT COUNT(*), COALESCE(MAX(item_id), 0) FROM news_item").fetchone()
        scores = conn.execute("SELECT COUNT(*) FROM news_score").fetchone()[0]
    finally:
        conn.close()
    return f"{n}:{last}:{scores}"


def build_text_features(index: pd.DatetimeIndex, symbol: str, conn=None) -> pd.DataFrame:
    """Colonnes `news_*` (cible) et `cb_*` (banques centrales) sur `index` ; lève `readiness.NewsHistoryTooShort` si la porte est fermée."""
    from patrick.text import service
    from patrick.tracking import db as trackdb

    own = conn is None
    conn = trackdb.connect() if own else conn
    try:
        days = pd.DatetimeIndex(index)
        news = aggregate.training_features_for_symbol(conn, symbol, days, service.LEXICON, service.lexicon_version(),
                                                      horizons=HORIZONS, prefix="news")
        cb = _central_bank_tone(conn, days)
    finally:
        if own:
            conn.close()
    out = pd.concat([news, cb], axis=1)
    out.index = index
    return out
