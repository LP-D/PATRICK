"""Du flux de news aux variables par séance : sentiment, attention et nouveauté, par actif et par horizon.

Chaque news passe par `features.event_features.align_items` avant d'atteindre une séance : elle n'est visible qu'à partir de
sa **clôture-précédente** (`known_at` = max(publication, première observation) ; après la clôture ou un jour férié, la séance
suivante). Aucune variable d'une séance t n'utilise donc d'information postérieure à t.

Pour chaque horizon h (séances) et le préfixe `news` :
- `news_sent_mean_{h}d`  : moyenne des notes des news des h dernières séances ; **manquante** s'il n'y en a pas (pas de news
  n'est pas une news neutre) ;
- `news_sent_ewm_{h}d`   : moyenne à décroissance exponentielle (demi-vie h/2 séances), toute l'histoire passée pèse un peu ;
- `news_sent_nov_{h}d`   : moyenne pondérée par la nouveauté (une dépêche recopiée compte peu) — si la colonne `novelty` existe ;
- `news_count_{h}d`      : nombre de news (notées ou non) ;
- `news_attention_{h}d`  : z-score du nombre de news par rapport aux `attention_lookback` séances **précédentes** ;
- `news_days_since`      : séances écoulées depuis la dernière news.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features import event_features as ef
from patrick.research import event_study as es
from patrick.text import store

MIN_ATTENTION_HISTORY = 30


def _empty_frame(days, horizons, prefix, with_novelty) -> pd.DataFrame:
    out = {}
    for h in horizons:
        out[f"{prefix}_sent_mean_{h}d"] = pd.Series(np.nan, index=days)
        out[f"{prefix}_sent_ewm_{h}d"] = pd.Series(np.nan, index=days)
        if with_novelty:
            out[f"{prefix}_sent_nov_{h}d"] = pd.Series(np.nan, index=days)
        out[f"{prefix}_count_{h}d"] = pd.Series(0.0, index=days)
        out[f"{prefix}_attention_{h}d"] = pd.Series(np.nan, index=days)
    out[f"{prefix}_days_since"] = pd.Series(np.nan, index=days)
    return pd.DataFrame(out, index=days)


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den).where(den > 0)


def sentiment_features(items: pd.DataFrame, trading_days, horizons=(1, 5, 20), prefix: str = "news",
                       attention_lookback: int = 252, **align_kwargs) -> pd.DataFrame:
    """`items` : colonnes `known_at` (horodatage tz-aware ou UTC naïf), `score` (NaN = non noté), `novelty` (optionnelle).
    Renvoie un DataFrame indexé par les séances de `trading_days`."""
    days = pd.DatetimeIndex(trading_days).normalize()
    with_novelty = "novelty" in items.columns
    if len(items) == 0:
        return _empty_frame(days, horizons, prefix, with_novelty)
    if "known_at" not in items.columns:
        raise ValueError("items need a `known_at` column (published_at = max(publication, first sight))")
    known = pd.to_datetime(items["known_at"], utc=True)
    aligned = ef.align_items(items.assign(published_at=known).drop(columns=["known_at"]), days, **align_kwargs)

    score = aligned["score"].astype(float)
    scored = score.notna()
    vis = aligned["visible_session"]
    count = pd.Series(1.0, index=aligned.index).groupby(vis).sum().reindex(days, fill_value=0.0)
    n_scored = scored.astype(float).groupby(vis).sum().reindex(days, fill_value=0.0)
    s_sum = score.where(scored, 0.0).groupby(vis).sum().reindex(days, fill_value=0.0)
    if with_novelty:
        nov = aligned["novelty"].astype(float).clip(0, 1).where(scored, 0.0)
        nov_den = nov.groupby(vis).sum().reindex(days, fill_value=0.0)
        nov_num = (score.where(scored, 0.0) * nov).groupby(vis).sum().reindex(days, fill_value=0.0)

    out: dict[str, pd.Series] = {}
    for h in horizons:
        out[f"{prefix}_sent_mean_{h}d"] = _ratio(s_sum.rolling(h, min_periods=1).sum(),
                                                 n_scored.rolling(h, min_periods=1).sum())
        lam = 0.5 ** (1.0 / max(h / 2.0, 0.5))
        num = np.zeros(len(days))
        den = np.zeros(len(days))
        a = b = 0.0
        for i in range(len(days)):
            a = lam * a + s_sum.iloc[i]
            b = lam * b + n_scored.iloc[i]
            num[i], den[i] = a, b
        out[f"{prefix}_sent_ewm_{h}d"] = pd.Series(np.where(den > 1e-6, num / np.where(den > 1e-6, den, 1), np.nan),
                                                  index=days)
        if with_novelty:
            out[f"{prefix}_sent_nov_{h}d"] = _ratio(nov_num.rolling(h, min_periods=1).sum(),
                                                    nov_den.rolling(h, min_periods=1).sum())
        c = count.rolling(h, min_periods=1).sum()
        out[f"{prefix}_count_{h}d"] = c
        prev = c.shift(1)
        mu = prev.rolling(attention_lookback, min_periods=MIN_ATTENTION_HISTORY).mean()
        sd = prev.rolling(attention_lookback, min_periods=MIN_ATTENTION_HISTORY).std()
        out[f"{prefix}_attention_{h}d"] = ((c - mu) / sd).where(sd > 0)
    pos = pd.Series(np.arange(len(days), dtype=float), index=days)
    out[f"{prefix}_days_since"] = pos - pos.where(count > 0).ffill()
    return pd.DataFrame(out, index=days)


MAX_LAG_HOURS = 72.0


def features_for_symbol(conn, symbol: str, trading_days, scorer: str, version: str, horizons=(1, 5, 20),
                        novelty_scorer: str | None = "novelty", novelty_version: str | None = None,
                        max_lag_hours: float | None = MAX_LAG_HOURS, **kwargs) -> pd.DataFrame:
    """Variables d'un actif depuis le magasin : news rattachées à `symbol`, notées par (`scorer`, `version`). Les news vues plus
    de `max_lag_hours` après leur publication sont écartées (flux relus des mois plus tard) ; `None` les garde."""
    days = pd.DatetimeIndex(trading_days).normalize()
    items = store.load_items(conn, max_lag_hours=max_lag_hours)
    links = store.load_links(conn)
    ids = set(links.loc[links["symbol"] == symbol, "item_id"])
    items = items[items["item_id"].isin(ids)]
    scores = store.load_scores(conn, scorer, version).rename(columns={"score": "score"})[["item_id", "score"]]
    merged = items.merge(scores, on="item_id", how="left")
    if novelty_scorer:
        nov = _novelty_scores(conn, novelty_scorer, novelty_version)
        if nov is not None:
            merged = merged.merge(nov, on="item_id", how="left")
    cols = ["known_at", "score"] + (["novelty"] if "novelty" in merged.columns else [])
    return sentiment_features(merged[cols], days, horizons=horizons, **kwargs)


def _novelty_scores(conn, scorer: str, version: str | None) -> pd.DataFrame | None:
    sql = "SELECT item_id, score AS novelty FROM news_score WHERE scorer = ?"
    args = [scorer]
    if version is not None:
        sql += " AND version = ?"
        args.append(str(version))
    rows = conn.execute(sql, args).fetchall()
    return pd.DataFrame(rows, columns=["item_id", "novelty"]) if rows else None


def strong_events(items: pd.DataFrame, min_abs_score: float = 0.5, min_novelty: float = 0.3) -> pd.DataFrame:
    """Les news qui peuvent servir d'événement : notées, |note| ≥ `min_abs_score`, nouveauté ≥ `min_novelty`."""
    df = items.dropna(subset=["known_at", "score"]).copy()
    if "novelty" in df.columns:
        df = df[df["novelty"] >= min_novelty]
    return df[df["score"].abs() >= min_abs_score]


def textual_event_study(prices: pd.Series, items: pd.DataFrame, benchmark: pd.Series | None = None,
                        min_abs_score: float = 0.5, min_novelty: float = 0.3, model: str = "market",
                        event_window: tuple[int, int] = (-5, 20), **kwargs) -> dict[str, es.EventStudy]:
    """Réaction des prix aux news fortes : événements = news dont |note| ≥ `min_abs_score` et nouveauté ≥ `min_novelty`,
    en deux groupes (`positive`, `negative`). J0 = première séance dont la clôture suit **strictement** la parution
    (`event_study.event_day_zero`). Un groupe sans événement est omis. Même réserve que toute étude d'événements : des
    news groupées dans le temps ne sont pas indépendantes (`overlapping_events`)."""
    df = strong_events(items, min_abs_score, min_novelty)
    out: dict[str, es.EventStudy] = {}
    for label, part in (("positive", df[df["score"] > 0]), ("negative", df[df["score"] < 0])):
        if part.empty:
            continue
        events = [pd.Timestamp(t) for t in pd.to_datetime(part["known_at"], utc=True)]
        out[label] = es.run_event_study(prices, events, benchmark=benchmark, model=model, event_window=event_window,
                                        labels=[label] * len(events), **kwargs)
    return out
