"""Orchestration de l'analyse textuelle : collecte -> magasin -> notes -> liens -> vues pour la page /news.

`refresh` est ce que lance `patrick news refresh` et le bouton « Actualiser » de la page : il ne touche que le magasin de
news de la base de suivi (jamais le cache de séries ni le data lake). Les notes sont **incrémentales** : une news déjà notée
par un outil (même version) n'est pas recalculée, et la nouveauté d'une news ne change jamais quand d'autres arrivent.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pandas as pd

from patrick import settings as machine_settings
from patrick.text import central_bank, events, lexicon, novelty, sources, store
from patrick.text.entities import EntityLinker, universe_linker

LEXICON = "lexicon"
TONE = "cb_tone"
NOVELTY = "novelty"
EVENTS = "events"
LINKS = "entity_link"
VERSION = "1"
NOVELTY_WINDOW_DAYS = 7.0


def lexicon_from_settings(settings: dict | None = None) -> lexicon.Lexicon:
    """Dictionnaire LM du fichier indiqué par `news_lm_dictionary`, sinon le lexique réduit intégré."""
    settings = machine_settings.load() if settings is None else settings
    path = settings.get("news_lm_dictionary")
    if path and os.path.isfile(path):
        try:
            return lexicon.load_loughran_mcdonald(path)
        except (OSError, ValueError):
            pass
    return lexicon.default_lexicon()


def lexicon_version(settings: dict | None = None) -> str:
    return lexicon_from_settings(settings).name


def _text(row) -> str:
    return f"{row['title']}. {row['summary'] or ''}".strip()


def score_pending(conn: sqlite3.Connection, linker: EntityLinker | None = None, settings: dict | None = None) -> int:
    """Note et rattache toutes les news qui ne l'ont pas encore été. Renvoie le nombre de news notées par le lexique."""
    lex = lexicon_from_settings(settings)
    linker = linker or universe_linker()
    items = store.load_items(conn)
    if items.empty:
        return 0
    rows = {int(r["item_id"]): r for _, r in items.iterrows()}

    pending_lex = store.unscored_item_ids(conn, LEXICON, lex.name)
    scores = {}
    for i in pending_lex:
        s = lexicon.score_text(_text(rows[i]), lex)
        scores[i] = (s.polarity, {"pos": s.n_positive, "neg": s.n_negative, "unc": s.n_uncertainty,
                                  "lit": s.n_litigious, "tokens": s.n_tokens})
    store.save_scores(conn, LEXICON, lex.name, scores)

    tone = {}
    for i in store.unscored_item_ids(conn, TONE, VERSION):
        if rows[i]["source_kind"] != "central_bank":
            continue
        t = central_bank.score_tone(_text(rows[i]))
        tone[i] = (t.tone, {"hawkish": t.n_hawkish, "dovish": t.n_dovish})
    store.save_scores(conn, TONE, VERSION, tone)

    tags = {i: (None, {"tags": events.extract_events(_text(rows[i]))}) for i in store.unscored_item_ids(conn, EVENTS, VERSION)}
    store.save_scores(conn, EVENTS, VERSION, tags)

    pending_nov = store.unscored_item_ids(conn, NOVELTY, VERSION)
    if pending_nov:
        floor = items.loc[items["item_id"].isin(pending_nov), "known_at"].min() - pd.Timedelta(days=NOVELTY_WINDOW_DAYS)
        ctx = items[items["known_at"] >= floor]
        series = novelty.novelty_scores([_text(r) for _, r in ctx.iterrows()], ctx["known_at"],
                                        window_days=NOVELTY_WINDOW_DAYS, index=ctx["item_id"])
        store.save_scores(conn, NOVELTY, VERSION, {int(i): (float(series[i]), None) for i in pending_nov})

    links = []
    pending_links = store.unscored_item_ids(conn, LINKS, VERSION)
    for i in pending_links:
        links.extend((i, symbol, method) for symbol, method in linker.link(_text(rows[i])))
    store.save_links(conn, links)
    store.save_scores(conn, LINKS, VERSION, {i: (None, None) for i in pending_links})
    return len(pending_lex)


def _link_hints(conn: sqlite3.Connection, hints: dict[str, list[str]], source: str) -> None:
    links = []
    for ext, symbols in hints.items():
        row = conn.execute("SELECT item_id FROM news_item WHERE source = ? AND external_id = ?", (source, ext)).fetchone()
        if row:
            links.extend((row[0], s, "feed") for s in symbols)
    store.save_links(conn, links)


def refresh(conn: sqlite3.Connection, feeds=None, fetch=None, now=None, linker: EntityLinker | None = None,
            with_gdelt: bool = False, gdelt_queries=None, gdelt_fetch=None, yahoo_symbols=None, yahoo_fetch=None,
            score: bool = True, settings: dict | None = None) -> dict:
    settings = machine_settings.load() if settings is None else settings
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    feeds = sources.feeds_from_settings(settings) if feeds is None else feeds
    collected = sources.collect_feeds(feeds, fetch=fetch or sources.fetch_url, now=now)
    items = list(collected.items)
    errors = list(collected.errors)
    skipped = collected.skipped_without_date
    hints_by_source: dict[str, dict[str, list[str]]] = {}

    if with_gdelt:
        g = sources.collect_gdelt(gdelt_queries or sources.DEFAULT_GDELT_QUERIES, fetch=gdelt_fetch or sources.fetch_url)
        items += g.items
        errors += g.errors
        skipped += g.skipped_without_date

    if yahoo_symbols:
        if yahoo_fetch is None:
            from patrick.webapp import market_data

            def yahoo_fetch(symbol):
                return market_data.latest_news(symbol, limit=20)
        yahoo_hints: dict[str, list[str]] = {}
        for symbol in yahoo_symbols:
            try:
                parsed = sources.parse_yahoo(symbol, yahoo_fetch(symbol), now)
            except Exception as exc:  # noqa: BLE001 -- frontière fournisseur : une panne Yahoo n'arrête pas la collecte
                errors.append((f"yahoo:{symbol}", str(exc)))
                continue
            items += parsed.items
            skipped += parsed.skipped_without_date
            for ident, syms in parsed.hints.items():
                yahoo_hints.setdefault(ident, []).extend(syms)
        hints_by_source["yahoo"] = yahoo_hints

    added = store.add_items(conn, items)
    for source, hints in hints_by_source.items():
        _link_hints(conn, hints, source)
    scored = score_pending(conn, linker=linker, settings=settings) if score else 0
    return {"added": added, "scored": scored, "errors": errors, "skipped_without_date": skipped}


def asset_overview(conn: sqlite3.Connection, since, now=None) -> pd.DataFrame:
    """Par actif : nombre de news utilisables depuis `since`, note moyenne du lexique, part de notes positives, nouveauté
    moyenne, dernière parution connue."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    items = store.load_items(conn, start=since, end=(now + pd.Timedelta(days=1)))
    items = items[items["known_at"] <= now]
    links = store.load_links(conn)
    score = store.load_scores(conn, LEXICON, lexicon_version())[["item_id", "score"]]
    nov = store.load_scores(conn, NOVELTY, VERSION)[["item_id", "score"]].rename(columns={"score": "novelty"})
    df = links.merge(items[["item_id", "known_at"]], on="item_id").merge(score, on="item_id", how="left") \
              .merge(nov, on="item_id", how="left")
    cols = ["symbol", "n_items", "n_scored", "mean_score", "share_positive", "mean_novelty", "last_known_at"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.groupby("symbol").agg(
        n_items=("item_id", "count"), n_scored=("score", "count"), mean_score=("score", "mean"),
        share_positive=("score", lambda s: float((s.dropna() > 0).mean()) if s.notna().any() else float("nan")),
        mean_novelty=("novelty", "mean"), last_known_at=("known_at", "max")).reset_index()
    return out.sort_values(["n_items", "symbol"], ascending=[False, True]).reset_index(drop=True)[cols]


def item_feed(conn: sqlite3.Connection, symbol: str | None = None, limit: int = 50, kinds=None) -> list[dict]:
    """Les `limit` news les plus récentes (par `known_at`), avec notes, étiquettes d'événement et actifs rattachés."""
    items = store.load_items(conn, kinds=kinds)
    links = store.load_links(conn)
    by_item = links.groupby("item_id")["symbol"].apply(list).to_dict() if not links.empty else {}
    if symbol is not None:
        items = items[items["item_id"].map(lambda i: symbol in by_item.get(i, []))]
    items = items.sort_values(["known_at", "item_id"], ascending=False).head(limit)
    if items.empty:
        return []

    def by_id(scorer, version):
        df = store.load_scores(conn, scorer, version)
        return df.set_index("item_id") if not df.empty else df

    lex, tone, nov, ev = (by_id(LEXICON, lexicon_version()), by_id(TONE, VERSION), by_id(NOVELTY, VERSION),
                          by_id(EVENTS, VERSION))

    def val(df, i, col="score"):
        if df.empty or i not in df.index:
            return None
        v = df.loc[i, col]
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    out = []
    for _, r in items.iterrows():
        i = int(r["item_id"])
        tags = val(ev, i, "detail_json")
        out.append({
            "item_id": i, "title": r["title"], "source": r["source"], "kind": r["source_kind"], "url": r["url"],
            "known_at": r["known_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "published_at": r["published_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "score": val(lex, i), "tone": val(tone, i), "novelty": val(nov, i),
            "events": json.loads(tags)["tags"] if tags else [], "symbols": by_item.get(i, []),
        })
    return out
