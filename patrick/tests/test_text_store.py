"""Magasin de news point-in-time (`patrick.text.store`).

Règles testées :
- une news sans heure de publication est refusée, jamais devinée ;
- une date seule est lue à la fin de la journée (hypothèse la plus tardive : jamais de fuite) ;
- `known_at` = max(publication, première observation) : une news rattrapée après coup n'est pas visible avant le jour
  où on l'a vue ;
- doublons ignorés (même source + identifiant, ou même contenu).
"""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.text import store


def _item(ext="a", published="2024-03-04T15:00:00Z", **kw):
    base = {"source": "rss:test", "source_kind": "news", "external_id": ext, "published_at": published,
            "title": f"Titre {ext}", "first_seen_at": published}
    base.update(kw)
    return store.NewsItem(**base)


def test_migration_creates_the_news_tables(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"news_item", "news_score", "news_link"} <= tables


def test_item_without_publication_time_is_refused(conn):
    with pytest.raises(ValueError, match="published_at"):
        store.add_items(conn, [_item(published=None)])
    with pytest.raises(ValueError, match="published_at"):
        store.add_items(conn, [_item(published="pas une date")])


def test_date_only_is_read_at_the_end_of_the_day(conn):
    store.add_items(conn, [_item("d", published="2024-03-04", first_seen_at="2024-03-04T08:00:00Z")])
    df = store.load_items(conn)
    assert df.loc[0, "published_at"] == pd.Timestamp("2024-03-04 23:59:59", tz="UTC")
    assert bool(df.loc[0, "date_only"])


def test_known_at_is_the_later_of_publication_and_first_sight(conn):
    store.add_items(conn, [
        _item("late", published="2024-01-02T10:00:00Z", first_seen_at="2024-03-04T09:00:00Z"),
        _item("early", published="2024-03-05T10:00:00Z", first_seen_at="2024-03-04T09:00:00Z"),
    ])
    df = store.load_items(conn).set_index("external_id")
    assert df.loc["late", "known_at"] == pd.Timestamp("2024-03-04 09:00:00", tz="UTC")
    assert df.loc["early", "known_at"] == pd.Timestamp("2024-03-05 10:00:00", tz="UTC")


def test_naive_and_offset_timestamps_are_normalised_to_utc(conn):
    store.add_items(conn, [_item("n", published="2024-03-04 15:00:00", first_seen_at="2024-03-04 15:00:00"),
                           _item("o", published="2024-03-04T10:00:00-05:00", first_seen_at="2024-03-04T10:00:00-05:00")])
    df = store.load_items(conn).set_index("external_id")
    assert df.loc["n", "published_at"] == pd.Timestamp("2024-03-04 15:00:00", tz="UTC")
    assert df.loc["o", "published_at"] == pd.Timestamp("2024-03-04 15:00:00", tz="UTC")


def test_duplicates_are_ignored(conn):
    assert store.add_items(conn, [_item("a"), _item("a")]) == 1
    assert store.add_items(conn, [_item("a")]) == 0
    # même contenu republié sous un autre identifiant par la même source : un seul exemplaire
    assert store.add_items(conn, [_item("b", title="Titre a")]) == 0
    assert len(store.load_items(conn)) == 1


def test_load_filters_by_window_and_kind(conn):
    store.add_items(conn, [_item("a", published="2024-03-04T10:00:00Z"),
                           _item("b", published="2024-03-06T10:00:00Z", source_kind="central_bank")])
    assert list(store.load_items(conn, kinds=["central_bank"])["external_id"]) == ["b"]
    assert list(store.load_items(conn, end="2024-03-05")["external_id"]) == ["a"]
    assert list(store.load_items(conn, start="2024-03-05")["external_id"]) == ["b"]


def test_scores_and_links_roundtrip(conn):
    store.add_items(conn, [_item("a"), _item("b")])
    ids = list(store.load_items(conn)["item_id"])
    store.save_scores(conn, "lexicon", "1", {ids[0]: (0.5, {"pos": 3})})
    assert store.unscored_item_ids(conn, "lexicon", "1") == [ids[1]]
    store.save_scores(conn, "lexicon", "1", {ids[0]: (0.7, {"pos": 4})})        # réécriture, pas de doublon
    df = store.load_scores(conn, "lexicon", "1")
    assert df.loc[df.item_id == ids[0], "score"].iloc[0] == pytest.approx(0.7)
    store.save_links(conn, [(ids[0], "AAPL", "cashtag"), (ids[0], "AAPL", "alias")])
    links = store.load_links(conn)
    assert len(links) == 1 and links.loc[0, "symbol"] == "AAPL"


def test_a_story_seen_long_after_its_publication_is_marked_stale_and_filterable(conn):
    store.add_items(conn, [
        _item("fresh", published="2024-03-04T15:00:00Z", first_seen_at="2024-03-04T15:20:00Z"),
        _item("old", published="2023-01-02T09:00:00Z", first_seen_at="2024-03-04T15:20:00Z"),
    ])
    df = store.load_items(conn).set_index("external_id")
    assert df.loc["fresh", "lag_hours"] == pytest.approx(1 / 3, abs=1e-3)
    assert df.loc["old", "lag_hours"] > 24 * 365
    assert list(store.load_items(conn, max_lag_hours=72)["external_id"]) == ["fresh"]
    assert len(store.load_items(conn)) == 2                            # sans filtre, rien n'est perdu
