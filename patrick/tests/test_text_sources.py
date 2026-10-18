"""Sources de news : analyse d'un flux RSS/Atom, de GDELT et de Yahoo, collecte tolérante aux pannes.

Aucun test n'ouvre le réseau : les charges utiles sont des exemples de la forme réelle des flux (vérifiée le 2026-10-18).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from patrick.text import sources, store

FETCHED = pd.Timestamp("2026-10-18 12:00:00", tz="UTC")

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Fed</title>
<item><title>Federal Reserve issues FOMC statement</title><link>https://fed.example/a</link>
<guid>https://fed.example/a</guid><description>&lt;p&gt;The Committee decided to &lt;b&gt;maintain&lt;/b&gt; the target range.&lt;/p&gt;</description>
<pubDate>Wed, 17 Sep 2025 18:00:00 GMT</pubDate></item>
<item><title>Item sans date</title><link>https://fed.example/b</link></item>
<item><title>Speech by Governor X</title><link>https://fed.example/c</link><pubDate>Tue, 16 Sep 2025 09:30:00 -0400</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>BoE</title>
<entry><title>Bank Rate decision</title><id>tag:boe,2025:1</id><link href="https://boe.example/1"/>
<summary>Bank Rate maintained at 4%.</summary><updated>2025-09-18T11:00:00Z</updated></entry>
<entry><title>Entry with published</title><id>tag:boe,2025:2</id><link href="https://boe.example/2"/>
<published>2025-09-19T08:00:00+01:00</published><updated>2025-09-20T08:00:00+01:00</updated></entry>
</feed>"""

FEED = sources.Feed("fed", "https://fed.example/rss", "central_bank", "en")


def test_rss_items_are_parsed_with_clean_text_and_utc_dates():
    parsed = sources.parse_feed(RSS, FEED, FETCHED)
    assert [i.title for i in parsed.items] == ["Federal Reserve issues FOMC statement", "Speech by Governor X"]
    first = parsed.items[0]
    assert first.summary == "The Committee decided to maintain the target range."
    assert pd.Timestamp(first.published_at) == pd.Timestamp("2025-09-17 18:00:00", tz="UTC")
    assert pd.Timestamp(parsed.items[1].published_at) == pd.Timestamp("2025-09-16 13:30:00", tz="UTC")
    assert first.source == "rss:fed" and first.source_kind == "central_bank" and first.language == "en"
    assert first.external_id == "https://fed.example/a"


def test_an_item_without_a_date_is_skipped_and_counted_never_dated_by_us():
    parsed = sources.parse_feed(RSS, FEED, FETCHED)
    assert parsed.skipped_without_date == 1


def test_first_sight_is_the_fetch_time_so_a_backlog_is_not_visible_in_the_past():
    parsed = sources.parse_feed(RSS, FEED, FETCHED)
    assert all(pd.Timestamp(i.first_seen_at) == FETCHED for i in parsed.items)


def test_atom_prefers_published_over_updated():
    parsed = sources.parse_feed(ATOM, sources.Feed("boe", "u", "central_bank", "en"), FETCHED)
    assert pd.Timestamp(parsed.items[0].published_at) == pd.Timestamp("2025-09-18 11:00:00", tz="UTC")
    assert pd.Timestamp(parsed.items[1].published_at) == pd.Timestamp("2025-09-19 07:00:00", tz="UTC")
    assert parsed.items[0].url == "https://boe.example/1"


def test_malformed_xml_is_an_error_not_an_empty_feed():
    with pytest.raises(sources.FeedError):
        sources.parse_feed("<rss><channel><item>", FEED, FETCHED)


GDELT = json.dumps({"articles": [
    {"url": "https://news.example/1", "title": "Fed signals patience as inflation cools", "seendate": "20250917T181500Z",
     "domain": "news.example", "language": "English", "sourcecountry": "United States"},
    {"url": "https://presse.example/2", "title": "La BCE maintient ses taux", "seendate": "20250918T093000Z",
     "domain": "presse.example", "language": "French"},
    {"url": "https://bad.example/3", "title": "Sans date", "seendate": ""},
]})


def test_gdelt_seen_date_is_both_publication_and_first_sight():
    parsed = sources.parse_gdelt(GDELT)
    assert len(parsed.items) == 2 and parsed.skipped_without_date == 1
    a, b = parsed.items
    assert pd.Timestamp(a.published_at) == pd.Timestamp("2025-09-17 18:15:00", tz="UTC") == pd.Timestamp(a.first_seen_at)
    assert a.source == "gdelt" and a.language == "en" and b.language == "fr"


def test_gdelt_url_is_built_with_parentheses_and_bounded_results():
    url = sources.gdelt_url("oil OR OPEC", timespan="2d", maxrecords=50)
    assert "query=%28oil+OR+OPEC%29" in url or "query=%28oil%20OR%20OPEC%29" in url
    assert "mode=artlist" in url and "format=json" in url and "maxrecords=50" in url and "timespan=2d" in url
    assert "maxrecords=250" in sources.gdelt_url("x", maxrecords=9999)


def test_yahoo_items_use_their_publication_time():
    raw = [{"title": "Apple unveils phone", "link": "https://y.example/1", "publisher": "Reuters",
            "published": "2025-09-17T14:00:00Z"},
           {"title": "Sans date", "link": "https://y.example/2", "publisher": "X", "published": ""}]
    parsed = sources.parse_yahoo("AAPL", raw, FETCHED)
    assert len(parsed.items) == 1 and parsed.skipped_without_date == 1
    assert parsed.items[0].source == "yahoo" and parsed.items[0].source_kind == "news"
    assert pd.Timestamp(parsed.items[0].first_seen_at) == FETCHED


def test_collect_keeps_going_when_one_source_fails(conn):
    feeds = [sources.Feed("ok", "https://ok", "news", "en"), sources.Feed("down", "https://down", "news", "en")]

    def fetch(url):
        if "down" in url:
            raise OSError("connexion refusée")
        return RSS

    result = sources.collect_feeds(feeds, fetch=fetch, now=FETCHED)
    assert len(result.items) == 2
    assert [e[0] for e in result.errors] == ["down"] and "connexion" in result.errors[0][1]
    assert store.add_items(conn, result.items) == 2


def test_default_feeds_are_unique_and_well_formed():
    names = [f.name for f in sources.DEFAULT_FEEDS]
    assert len(names) == len(set(names))
    for f in sources.DEFAULT_FEEDS:
        assert f.url.startswith("https://") and f.kind in ("news", "central_bank", "commodity_report")


def test_extra_feeds_come_from_settings():
    feeds = sources.feeds_from_settings({"news_extra_feeds": [
        {"name": "ecb", "url": "https://ecb.example/rss", "kind": "central_bank", "language": "en"},
        {"name": "bad", "url": "http://insecure.example", "kind": "news"},       # http refusé
        {"name": "x"},                                                           # incomplet
    ]})
    assert [f.name for f in feeds][-1:] == ["ecb"]
    assert "bad" not in [f.name for f in feeds]


def test_a_feed_declaring_entities_is_refused():
    bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    with pytest.raises(sources.FeedError, match="DOCTYPE|ENTITY"):
        sources.parse_feed(bomb, FEED, FETCHED)


def test_plain_http_urls_are_never_fetched():
    with pytest.raises(OSError, match="https"):
        sources.fetch_url("http://insecure.example/rss")


def test_gdelt_rate_limit_stops_the_series_without_hammering():
    import urllib.error

    calls = []

    def fetch(url):
        calls.append(url)
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    result = sources.collect_gdelt(("a", "b", "c"), fetch=fetch, sleep=lambda s: None)
    assert len(calls) == 1 and result.errors == [("gdelt", "HTTP 429")]


def test_comparison_signs_in_a_headline_are_not_mistaken_for_markup():
    rss = ('<?xml version="1.0"?><rss version="2.0"><channel><item>'
           "<title>Gold &lt; 2000 as S&amp;P &gt; 5000 &lt;b&gt;now&lt;/b&gt;</title><link>https://x.example/1</link>"
           "<pubDate>Wed, 17 Sep 2025 18:00:00 GMT</pubDate></item></channel></rss>")
    parsed = sources.parse_feed(rss, FEED, FETCHED)
    assert parsed.items[0].title == "Gold < 2000 as S&P > 5000 now"
