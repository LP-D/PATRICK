"""Texte complet des nouvelles de banque centrale : extraction, lecture bornée aux hôtes des flux, ton calculé sur la page."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.text import central_bank, fulltext, service, sources, store

NOW = pd.Timestamp("2026-10-27 12:00:00", tz="UTC")

FED_PAGE = """<html><head><title>x</title><script>var evil = "inflation remains elevated";</script></head><body>
<nav><a href="/">Home</a> rate hikes menu</nav>
<div id="header"><p>Federal Reserve Board</p></div>
<div id="article"><div class="heading"><h1>Federal Reserve issues FOMC statement</h1></div>
<div class="col-xs-12"><p>The Committee decided to raise the target range for the federal funds rate by 1/4 percentage point.</p>
<p>Inflation remains elevated.<br>Price stability is the goal.</p></div></div>
<div id="footer"><p>Contact us</p></div></body></html>"""

BOE_PAGE = """<html><body><div class="cookie-content"><p>We use cookies</p></div>
<main class="main" id="main-content"><h1>Bank Rate maintained</h1><p>Three members voted to increase Bank Rate by 0.25 percentage points.</p>
<h2>Other news</h2><p>An unrelated headline about banknotes</p></main></body></html>"""

MINUTES_RELEASE = """<div id="article"><p>The Federal Reserve released the minutes.</p>
<a href="/monetarypolicy/fomcminutes20260916.htm">HTML</a></div>"""
MINUTES_PAGE = """<div id="article"><p>Participants judged that inflation remained elevated and that further increases in the target
range could be appropriate.</p></div>"""


def _rss(url):
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title><item><title>FOMC statement</title>'
            f"<link>{url}</link><description>Short.</description><pubDate>Mon, 26 Oct 2026 18:00:00 GMT</pubDate>"
            "</item></channel></rss>")


FEEDS = [sources.Feed("fed_x", "https://www.federalreserve.gov/feeds/press_monetary.xml", "central_bank"),
         sources.Feed("press", "https://press.example/rss", "news")]


def test_extract_text_keeps_the_article_and_drops_scripts_menus_and_footers():
    text = fulltext.extract_text(FED_PAGE)

    assert "raise the target range" in text and "Price stability is the goal." in text
    assert "evil" not in text and "menu" not in text and "Contact us" not in text and "Federal Reserve Board" not in text
    assert "Inflation remains elevated.\nPrice stability" in text                 # <br> sépare les lignes


def test_extract_text_reads_main_and_stops_at_the_page_footer_block():
    text = fulltext.extract_text(BOE_PAGE)

    assert "voted to increase Bank Rate" in text
    assert "cookies" not in text and "banknotes" not in text and "Other news" not in text


def test_a_page_without_a_known_container_gives_nothing_rather_than_the_whole_page():
    assert fulltext.extract_text("<html><body><p>menus and banners only</p></body></html>") == ""
    assert fulltext.extract_text("") == "" and fulltext.extract_text(None) == ""
    assert fulltext.extract_text('<div id="article"><p>unclosed <b>tag').startswith("unclosed")


def test_extract_text_is_capped():
    assert len(fulltext.extract_text('<div id="article"><p>' + "word " * 100_000 + "</p></div>", max_chars=1000)) == 1000


def test_only_https_pages_on_a_central_bank_feed_host_are_readable():
    hosts = fulltext.allowed_hosts(FEEDS)

    assert hosts == {"www.federalreserve.gov"}                                    # le flux « news » n'ouvre aucun hôte
    assert fulltext.readable_url("https://www.federalreserve.gov/newsevents/x.htm", hosts)
    assert fulltext.readable_url("https://federalreserve.gov/x.htm", hosts)       # avec ou sans « www. »
    assert fulltext.readable_url("https://sub.federalreserve.gov/x.htm", hosts)
    assert not fulltext.readable_url("http://www.federalreserve.gov/x.htm", hosts)
    assert not fulltext.readable_url("https://federalreserve.gov.evil.example/x.htm", hosts)
    assert not fulltext.readable_url("https://evil.example/federalreserve.gov", hosts)
    assert not fulltext.readable_url(None, hosts) and not fulltext.readable_url("", hosts)


def _store_item(conn, url):
    store.add_items(conn, [store.NewsItem(source="rss:fed_x", source_kind="central_bank", external_id="1",
                                          published_at="2026-10-26T18:00:00Z", first_seen_at="2026-10-26T18:05:00Z",
                                          title="FOMC statement", summary="Short.", url=url)])
    return int(store.load_items(conn)["item_id"].iloc[0])


def test_fetch_bodies_stores_the_page_once(conn):
    item = _store_item(conn, "https://www.federalreserve.gov/newsevents/pressreleases/monetary1.htm")
    calls = []

    def fetch(url):
        calls.append(url)
        return FED_PAGE

    first = fulltext.fetch_bodies(conn, FEEDS, fetch, now=NOW, sleep=lambda s: None)
    second = fulltext.fetch_bodies(conn, FEEDS, fetch, now=NOW, sleep=lambda s: None)

    assert first == {"fetched": 1, "failed": 0, "skipped": 0} and second == {"fetched": 0, "failed": 0, "skipped": 0}
    assert len(calls) == 1
    assert "raise the target range" in fulltext.load_body_texts(conn, [item])[item]
    assert item in fulltext.tone_ready_ids(conn)


def test_a_page_that_never_loads_is_retried_then_given_up(conn):
    item = _store_item(conn, "https://www.federalreserve.gov/newsevents/pressreleases/monetary1.htm")

    def fetch(url):
        raise OSError("hors ligne")

    for attempt in range(1, fulltext.MAX_ATTEMPTS + 1):
        report = fulltext.fetch_bodies(conn, FEEDS, fetch, now=NOW, sleep=lambda s: None)
        assert report["failed"] == 1
        assert (item in fulltext.tone_ready_ids(conn)) == (attempt == fulltext.MAX_ATTEMPTS)
    assert fulltext.fetch_bodies(conn, FEEDS, fetch, now=NOW, sleep=lambda s: None)["failed"] == 0      # abandonnée
    assert fulltext.load_body_texts(conn, [item]) == {}


def test_a_link_to_another_host_is_never_fetched(conn):
    item = _store_item(conn, "https://evil.example/page.htm")

    def fetch(url):
        raise AssertionError("aucune lecture attendue")

    assert fulltext.fetch_bodies(conn, FEEDS, fetch, now=NOW, sleep=lambda s: None) == {"fetched": 0, "failed": 0, "skipped": 1}
    assert item in fulltext.tone_ready_ids(conn)                                    # ton calculé sur le titre et le résumé


def test_the_press_release_of_the_minutes_is_replaced_by_the_minutes_themselves(conn):
    item = _store_item(conn, "https://www.federalreserve.gov/newsevents/pressreleases/monetary2.htm")
    pages = {"https://www.federalreserve.gov/newsevents/pressreleases/monetary2.htm": MINUTES_RELEASE,
             "https://www.federalreserve.gov/monetarypolicy/fomcminutes20260916.htm": MINUTES_PAGE}

    fulltext.fetch_bodies(conn, FEEDS, pages.__getitem__, now=NOW, sleep=lambda s: None)

    assert "further increases in the target" in fulltext.load_body_texts(conn, [item])[item]


def test_the_fetch_loop_stops_at_its_time_budget(conn):
    for n in range(3):
        store.add_items(conn, [store.NewsItem(source="rss:fed_x", source_kind="central_bank", external_id=str(n),
                                              published_at=f"2026-10-2{n}T18:00:00Z", first_seen_at="2026-10-26T18:05:00Z",
                                              title=f"Statement {n}", url=f"https://www.federalreserve.gov/p{n}.htm")])
    ticks = iter([0.0, 0.0, 1000.0, 2000.0, 3000.0])

    report = fulltext.fetch_bodies(conn, FEEDS, lambda u: FED_PAGE, now=NOW, sleep=lambda s: None, max_seconds=10.0,
                                   clock=lambda: next(ticks))

    assert report["fetched"] == 1                                                   # les deux autres attendent la collecte suivante


def _refresh_feed_xml(url):
    return _rss(url)


def test_the_tone_is_computed_on_the_full_page_not_on_the_feed_sentence(conn):
    url = "https://www.federalreserve.gov/newsevents/pressreleases/monetary3.htm"

    def fetch(u):
        return FED_PAGE if u == url else _rss(url)

    report = service.refresh(conn, feeds=FEEDS[:1], fetch=fetch, now=NOW, with_gdelt=False, linker=_NoLinker())

    assert report["bodies"]["fetched"] == 1
    item = int(store.load_items(conn)["item_id"].iloc[0])
    tone = store.load_scores(conn, "cb_tone", service.TONE_VERSION).set_index("item_id").loc[item]
    assert tone["score"] > 0                                                         # « Short. » seul n'aurait donné aucun ton
    assert '"full_text": true' in tone["detail_json"]


def test_the_tone_waits_for_the_page_instead_of_being_computed_on_one_sentence(conn):
    item = _store_item(conn, "https://www.federalreserve.gov/newsevents/pressreleases/monetary4.htm")

    service.score_pending(conn, linker=_NoLinker())

    assert store.load_scores(conn, "cb_tone", service.TONE_VERSION).empty
    fulltext.fetch_bodies(conn, FEEDS, lambda u: FED_PAGE, now=NOW, sleep=lambda s: None)
    service.score_pending(conn, linker=_NoLinker())
    assert list(store.load_scores(conn, "cb_tone", service.TONE_VERSION)["item_id"]) == [item]


class _NoLinker:
    def link(self, text):
        return []


@pytest.mark.parametrize("text, sign", [
    ("The Committee decided to raise the target range for the federal funds rate.", 1),
    ("Three members voted to increase Bank Rate by 0.25 percentage points.", 1),
    ("The Committee voted to lower the target range for the federal funds rate.", -1),
    ("Risks to the inflation outlook are tilted to the upside.", 1),
    ("Underlying disinflation has continued.", -1),
])
def test_the_real_fed_and_boe_phrasing_is_read(text, sign):
    assert central_bank.score_tone(text).tone == sign


def test_regulatory_tightening_and_capital_easing_are_not_monetary_stance():
    assert central_bank.score_tone("Regulators announce tightening of capital buffers and easing of reporting rules.").tone is None


def test_a_long_text_that_hardly_talks_about_monetary_policy_has_no_tone():
    filler = "The supervisory framework for large banks needs to be modernized. " * 40
    text = filler + "Some call this restrictive. Others say the process is restrictive."

    score = central_bank.score_tone(text)

    assert score.n_hawkish == 2 and score.n_monetary == 0 and score.tone is None


def test_a_long_monetary_text_with_a_single_expression_has_no_tone():
    text = ("Inflation, interest rates and monetary policy were discussed at length. " * 40) + "The stance is restrictive."

    assert central_bank.score_tone(text).tone is None
    assert central_bank.score_tone(text + " Policy remains restrictive.").tone == 1.0


def test_further_tightening_of_credit_standards_is_not_a_policy_stance():
    assert central_bank.score_tone("Banks report further tightening of credit standards and a further increase in demand.").tone is None
    assert central_bank.score_tone("The Committee anticipates further policy firming.").tone == 1.0
    assert central_bank.score_tone("A further rate increase cannot be ruled out.").tone == 1.0
