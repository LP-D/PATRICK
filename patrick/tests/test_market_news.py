"""`market_data.latest_news` on real-world Yahoo payload shapes: an item
whose `content` is null (observed live on ^VIX, 2026-09-25) used to raise
AttributeError and turn `/api/news/{symbol}` into a 500."""
from __future__ import annotations

from patrick.webapp import market_data


class _Ticker:
    def __init__(self, news):
        self.news = news


def test_items_with_null_content_are_skipped_not_crashing(monkeypatch):
    news = [
        {"id": "a", "content": None},
        {"id": "b", "content": {"title": "Fed holds", "provider": None,
                                "canonicalUrl": {"url": "https://x/1"}, "pubDate": "2026-09-25"}},
        "garbage",
        {"title": "legacy flat item", "provider": {"displayName": "Reuters"}},
    ]
    monkeypatch.setattr(market_data.yf, "Ticker", lambda symbol: _Ticker(news))
    out = market_data.latest_news("^VIX")
    assert [n["title"] for n in out] == ["Fed holds", "legacy flat item"]
    assert out[0]["link"] == "https://x/1" and out[0]["publisher"] == ""
    assert out[1]["publisher"] == "Reuters"


def test_news_items_with_string_provider_and_url_are_tolerated(monkeypatch):
    news = [{
        "content": {
            "title": "Oil climbs",
            "provider": "Reuters",
            "canonicalUrl": "https://x/2",
            "clickThroughUrl": "https://x/3",
            "pubDate": "2026-09-26",
        }
    }]
    monkeypatch.setattr(market_data.yf, "Ticker", lambda symbol: _Ticker(news))
    out = market_data.latest_news("^VIX")
    assert out[0]["title"] == "Oil climbs"
    assert out[0]["publisher"] == "Reuters"
    assert out[0]["link"] == "https://x/2"
