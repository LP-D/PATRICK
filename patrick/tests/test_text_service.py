"""Orchestration : collecte -> magasin -> notes (lexique, ton, nouveauté, événements) -> liens -> vues pour la page /news."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from patrick.text import entities, service, sources, store

NOW = pd.Timestamp("2026-10-18 12:00:00", tz="UTC")


def _rss(*entries):
    items = "".join(
        f"<item><title>{t}</title><link>https://x.example/{i}</link><description>{d}</description>"
        f"<pubDate>{p}</pubDate></item>" for i, (t, d, p) in enumerate(entries))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{items}</channel></rss>'


FEEDS = [sources.Feed("press", "https://press.example/rss", "news"),
         sources.Feed("fedx", "https://fed.example/rss", "central_bank")]

PRESS = _rss(("Apple shares surge as profit beats forecasts", "Strong iPhone demand", "Fri, 16 Oct 2026 14:00:00 GMT"),
             ("Oil prices plunge after sanctions are lifted", "Brent falls", "Fri, 16 Oct 2026 15:00:00 GMT"))
FED = _rss(("FOMC statement", "The Committee judges that further rate hikes may be appropriate; inflation remains elevated.",
            "Fri, 16 Oct 2026 18:00:00 GMT"))


def _fetch(url):
    return PRESS if "press" in url else FED


@pytest.fixture
def linker():
    return entities.EntityLinker(names={"AAPL": "Apple"}, themes={"CL=F": ["oil prices"], "BZ=F": ["Brent"]})


def test_refresh_stores_scores_and_links_everything(conn, linker):
    report = service.refresh(conn, feeds=FEEDS, fetch=_fetch, now=NOW, linker=linker, with_gdelt=False)
    assert report["added"] == 3 and report["errors"] == []
    items = store.load_items(conn).set_index("title")
    assert (items["source_kind"] == "central_bank").sum() == 1
    lex = store.load_scores(conn, "lexicon", service.lexicon_version()).set_index("item_id")["score"]
    apple_id = int(items.loc["Apple shares surge as profit beats forecasts", "item_id"])
    oil_id = int(items.loc["Oil prices plunge after sanctions are lifted", "item_id"])
    assert lex[apple_id] > 0 and lex[oil_id] < 0
    tone = store.load_scores(conn, "cb_tone", "1").set_index("item_id")["score"]
    fed_id = int(items.loc["FOMC statement", "item_id"])
    assert list(tone.index) == [fed_id] and tone[fed_id] > 0
    links = store.load_links(conn)
    assert {(r.item_id, r.symbol) for r in links.itertuples()} == {(apple_id, "AAPL"), (oil_id, "CL=F"), (oil_id, "BZ=F")}   # le résumé cite aussi Brent
    events = store.load_scores(conn, "events", "1").set_index("item_id")["detail_json"]
    assert "sanction" in json.loads(events[oil_id])["tags"]


def test_a_second_refresh_adds_nothing_and_rescoring_is_incremental(conn, linker):
    service.refresh(conn, feeds=FEEDS, fetch=_fetch, now=NOW, linker=linker, with_gdelt=False)
    again = service.refresh(conn, feeds=FEEDS, fetch=_fetch, now=NOW + pd.Timedelta(hours=1), linker=linker,
                            with_gdelt=False)
    assert again["added"] == 0 and again["scored"] == 0


def test_a_failing_source_is_reported_and_the_others_still_land(conn, linker):
    def fetch(url):
        if "fed" in url:
            raise OSError("hors ligne")
        return PRESS

    report = service.refresh(conn, feeds=FEEDS, fetch=fetch, now=NOW, linker=linker, with_gdelt=False)
    assert report["added"] == 2 and report["errors"][0][0] == "fedx"


def test_novelty_of_a_reprint_is_low_and_the_original_is_not_rewritten(conn, linker):
    service.refresh(conn, feeds=FEEDS[:1], fetch=lambda u: PRESS, now=NOW, linker=linker, with_gdelt=False)
    before = store.load_scores(conn, "novelty", "1").set_index("item_id")["score"].to_dict()
    reprint = _rss(("Apple shares surge as profit beats forecasts!", "Strong iPhone demand", "Sat, 17 Oct 2026 09:00:00 GMT"))
    service.refresh(conn, feeds=[sources.Feed("wire", "https://wire.example/rss", "news")], fetch=lambda u: reprint,
                    now=NOW + pd.Timedelta(days=1), linker=linker, with_gdelt=False)
    after = store.load_scores(conn, "novelty", "1").set_index("item_id")["score"]
    assert all(after[i] == v for i, v in before.items())
    new_id = next(i for i in after.index if i not in before)
    assert after[new_id] < 0.2


def test_yahoo_headlines_are_linked_to_the_queried_symbol(conn, linker):
    raw = {"AAPL": [{"title": "Quarterly numbers out", "link": "https://y.example/1", "publisher": "R",
                     "published": "2026-10-16T14:00:00Z"}]}
    report = service.refresh(conn, feeds=[], fetch=lambda u: "", now=NOW, linker=linker, with_gdelt=False,
                             yahoo_symbols=["AAPL"], yahoo_fetch=lambda s: raw[s])
    assert report["added"] == 1
    assert [(r.symbol, r.method) for r in store.load_links(conn).itertuples()] == [("AAPL", "feed")]


def test_asset_overview_summarises_recent_news_per_symbol(conn, linker):
    service.refresh(conn, feeds=FEEDS, fetch=_fetch, now=NOW, linker=linker, with_gdelt=False)
    table = service.asset_overview(conn, since=NOW - pd.Timedelta(days=7), now=NOW).set_index("symbol")
    assert table.loc["AAPL", "n_items"] == 1 and table.loc["AAPL", "mean_score"] > 0
    assert table.loc["CL=F", "mean_score"] < 0


def test_item_feed_filters_by_symbol_and_exposes_the_scores(conn, linker):
    service.refresh(conn, feeds=FEEDS, fetch=_fetch, now=NOW, linker=linker, with_gdelt=False)
    feed = service.item_feed(conn, symbol="CL=F", limit=10)
    assert len(feed) == 1 and feed[0]["score"] < 0 and "sanction" in feed[0]["events"] and feed[0]["symbols"] == ["BZ=F", "CL=F"]
    everything = service.item_feed(conn, limit=10)
    assert len(everything) == 3 and everything[0]["known_at"] >= everything[-1]["known_at"]


def test_lm_dictionary_path_from_settings_changes_the_scorer_version(tmp_path):
    path = tmp_path / "lm.csv"
    path.write_text("Word,Negative,Positive,Uncertainty,Litigious\nGLORBLE,2009,0,0,0\n", encoding="utf-8")
    assert service.lexicon_version() .startswith("builtin")
    assert service.lexicon_from_settings({"news_lm_dictionary": str(path)}).name == "lm:lm.csv"
    assert service.lexicon_from_settings({"news_lm_dictionary": str(tmp_path / "absent.csv")}).name.startswith("builtin")


def test_stories_republished_long_after_their_date_do_not_count_as_fresh_news(conn, linker):
    old = _rss(("Apple shares surge as profit beats forecasts", "Strong demand", "Mon, 06 Jan 2025 14:00:00 GMT"))
    service.refresh(conn, feeds=FEEDS[:1], fetch=lambda u: old, now=NOW, linker=linker, with_gdelt=False)
    assert service.summary(conn, now=NOW)["n_stale"] == 1
    assert service.asset_overview(conn, since=NOW - pd.Timedelta(days=30), now=NOW).empty
    assert service.item_feed(conn, limit=10) == []
    assert len(service.item_feed(conn, limit=10, include_stale=True)) == 1
    assert service.scored_items_for_symbol(conn, "AAPL").empty
