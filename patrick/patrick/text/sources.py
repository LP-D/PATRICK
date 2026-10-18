"""Sources de news : flux RSS/Atom (presse, banques centrales, rapports énergie), GDELT, Yahoo.

Règle d'horodatage point-in-time (voir `store.py`) :
- flux RSS/Atom et Yahoo : `first_seen_at` = heure de la collecte. Une relecture du flux un mois plus tard ne rend jamais une
  news visible dans le passé ;
- GDELT : la date « vue » (`seendate`) est l'heure à laquelle GDELT a détecté l'article. Elle sert à la fois de publication
  et de première observation : c'est la seule source ici qui permette de **reconstituer** un historique sans fuite.
Une entrée sans date est écartée et comptée (`skipped_without_date`), jamais datée par nous.

Les flux par défaut sont ceux qui répondaient en lecture le 2026-10-18. Ne répondaient pas : BCE (certificat refusé par
Python sur ce poste), USDA et OPEP (403 aux requêtes automatiques), AIE (404). Ajoutables via le réglage
`news_extra_feeds` de `~/.patrick/settings.json` (https uniquement).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import pandas as pd

from patrick.text.store import NewsItem

USER_AGENT = "Mozilla/5.0 (PATRICK research reader)"
MAX_BYTES = 5_000_000
KINDS = ("news", "central_bank", "commodity_report")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


class FeedError(ValueError):
    """Flux illisible ou refusé."""


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    kind: str
    language: str = "en"


DEFAULT_FEEDS: tuple[Feed, ...] = (
    Feed("fed_monetary", "https://www.federalreserve.gov/feeds/press_monetary.xml", "central_bank"),
    Feed("fed_speeches", "https://www.federalreserve.gov/feeds/speeches.xml", "central_bank"),
    Feed("boe_news", "https://www.bankofengland.co.uk/rss/news", "central_bank"),
    Feed("eia_today", "https://www.eia.gov/rss/todayinenergy.xml", "commodity_report"),
    Feed("eia_press", "https://www.eia.gov/rss/press_rss.xml", "commodity_report"),
    Feed("ft_markets", "https://www.ft.com/markets?format=rss", "news"),
    Feed("bbc_business", "https://feeds.bbci.co.uk/news/business/rss.xml", "news"),
    Feed("cnbc_markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "news"),
    Feed("marketwatch", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "news"),
)

DEFAULT_GDELT_QUERIES: tuple[str, ...] = (
    '"federal reserve" OR "central bank" OR inflation',
    "oil OR OPEC OR crude",
    "gold OR silver OR copper",
    "bitcoin OR ethereum",
    '"stock market" OR "S&P 500" OR "wall street"',
    "sanctions OR strike OR drought OR hurricane",
)

_GDELT_LANG = {"English": "en", "French": "fr", "German": "de", "Spanish": "es", "Italian": "it", "Portuguese": "pt",
               "Dutch": "nl", "Chinese": "zh", "Japanese": "ja"}


@dataclass
class ParsedFeed:
    items: list[NewsItem] = field(default_factory=list)
    skipped_without_date: int = 0
    hints: dict[str, list[str]] = field(default_factory=dict)       # identifiant -> symboles connus d'avance (Yahoo)


@dataclass
class Collected:
    items: list[NewsItem] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped_without_date: int = 0
    hints: dict[str, list[str]] = field(default_factory=dict)


def _clean(text: str | None) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", html.unescape(text or "")))).strip()


def _utc_iso(value: str | None) -> str | None:
    """Date d'un flux -> ISO UTC, ou `None` si absente/illisible (jamais devinée)."""
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        ts = pd.Timestamp(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        try:
            ts = pd.Timestamp(value)
        except (ValueError, TypeError):
            return None
    if pd.isna(ts):
        return None
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ET.Element, *names: str) -> str | None:
    for child in node:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text
    return None


def parse_feed(xml_text: str, feed: Feed, fetched_at) -> ParsedFeed:
    if re.search(r"<!(?:DOCTYPE|ENTITY)", xml_text[:4096], re.IGNORECASE) or "<!ENTITY" in xml_text:
        raise FeedError("flux refusé : déclaration DOCTYPE/ENTITY (risque d'expansion d'entités)")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedError(f"XML illisible : {exc}") from exc
    seen = pd.Timestamp(fetched_at)
    seen = seen.tz_localize("UTC") if seen.tzinfo is None else seen.tz_convert("UTC")
    out = ParsedFeed()
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _clean(_child_text(node, "title"))
        if not title:
            continue
        published = _utc_iso(_child_text(node, "pubDate", "published", "date")) or _utc_iso(_child_text(node, "updated"))
        if published is None:
            out.skipped_without_date += 1
            continue
        link = _child_text(node, "link")
        if link is None:
            for child in node:
                if _local(child.tag) == "link" and child.get("href") and child.get("rel", "alternate") == "alternate":
                    link = child.get("href")
                    break
        ident = (_child_text(node, "guid", "id") or link or title).strip()
        summary = _clean(_child_text(node, "description", "summary", "content")) or None
        out.items.append(NewsItem(source=f"rss:{feed.name}", source_kind=feed.kind, external_id=ident,
                                  published_at=published, title=title, summary=summary, url=(link or "").strip() or None,
                                  language=feed.language, first_seen_at=seen.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return out


def parse_gdelt(payload) -> ParsedFeed:
    data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    out = ParsedFeed()
    for art in (data or {}).get("articles", []) or []:
        title = _clean(art.get("title"))
        url = (art.get("url") or "").strip()
        seen = art.get("seendate") or ""
        try:
            ts = pd.to_datetime(seen, format="%Y%m%dT%H%M%SZ", utc=True)
        except (ValueError, TypeError):
            ts = pd.NaT
        if not title or not url:
            continue
        if pd.isna(ts):
            out.skipped_without_date += 1
            continue
        iso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.items.append(NewsItem(source="gdelt", source_kind="news", external_id=url, published_at=iso, title=title,
                                  url=url, language=_GDELT_LANG.get(art.get("language") or ""), first_seen_at=iso))
    return out


def gdelt_url(query: str, timespan: str = "1d", maxrecords: int = 100) -> str:
    q = query.strip()
    if not q.startswith("("):
        q = f"({q})"
    params = {"query": q, "mode": "artlist", "format": "json", "maxrecords": max(1, min(int(maxrecords), 250)),
              "timespan": timespan, "sort": "datedesc"}
    return "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)


def parse_yahoo(symbol: str, raw: list[dict], fetched_at) -> ParsedFeed:
    seen = pd.Timestamp(fetched_at)
    seen = seen.tz_localize("UTC") if seen.tzinfo is None else seen.tz_convert("UTC")
    out = ParsedFeed()
    for r in raw or []:
        title = _clean(r.get("title"))
        if not title:
            continue
        published = _utc_iso(r.get("published"))
        if published is None:
            out.skipped_without_date += 1
            continue
        ident = (r.get("link") or "").strip() or f"{symbol}:{title}"
        out.items.append(NewsItem(source="yahoo", source_kind="news", external_id=ident, published_at=published,
                                  title=title, url=(r.get("link") or "").strip() or None, language="en",
                                  first_seen_at=seen.strftime("%Y-%m-%dT%H:%M:%SZ")))
        out.hints.setdefault(ident, []).append(symbol)
    return out


def fetch_url(url: str, timeout: float = 20.0) -> str:
    if not url.lower().startswith("https://"):
        raise OSError(f"URL non https refusée : {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_BYTES).decode("utf-8", "replace")


def collect_feeds(feeds, fetch=fetch_url, now=None) -> Collected:
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    result = Collected()
    for feed in feeds:
        try:
            parsed = parse_feed(fetch(feed.url), feed, now)
        except (OSError, urllib.error.URLError, FeedError) as exc:
            result.errors.append((feed.name, str(exc)))
            continue
        result.items.extend(parsed.items)
        result.skipped_without_date += parsed.skipped_without_date
    return result


def collect_gdelt(queries=DEFAULT_GDELT_QUERIES, fetch=fetch_url, timespan: str = "1d", maxrecords: int = 100,
                  pause_s: float = 5.5, sleep=time.sleep) -> Collected:
    """Une requête toutes les ~5 s (limite demandée par GDELT). Un refus (429) arrête la série : insister l'aggrave."""
    result = Collected()
    for i, query in enumerate(queries):
        if i:
            sleep(pause_s)
        try:
            parsed = parse_gdelt(fetch(gdelt_url(query, timespan, maxrecords)))
        except urllib.error.HTTPError as exc:
            result.errors.append(("gdelt", f"HTTP {exc.code}"))
            if exc.code == 429:
                break
            continue
        except (OSError, urllib.error.URLError, ValueError) as exc:
            result.errors.append(("gdelt", str(exc)))
            continue
        result.items.extend(parsed.items)
        result.skipped_without_date += parsed.skipped_without_date
    return result


def feeds_from_settings(settings: dict) -> list[Feed]:
    """Flux par défaut + `news_extra_feeds` du fichier de réglages (https uniquement, nom unique, type connu)."""
    feeds = list(DEFAULT_FEEDS)
    names = {f.name for f in feeds}
    for raw in settings.get("news_extra_feeds") or []:
        if not isinstance(raw, dict):
            continue
        name, url, kind = raw.get("name"), raw.get("url"), raw.get("kind", "news")
        if not (isinstance(name, str) and isinstance(url, str) and name and url.startswith("https://")):
            continue
        if kind not in KINDS or name in names:
            continue
        names.add(name)
        feeds.append(Feed(name, url, kind, str(raw.get("language") or "en")))
    return feeds
