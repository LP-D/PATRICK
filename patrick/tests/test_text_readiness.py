"""Historique de nouvelles disponible : la porte vers l'entraînement reste fermée tant qu'il est trop court."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.text import aggregate, readiness, service, store

DAYS = pd.bdate_range("2025-01-01", periods=400)


def _add(conn, days, symbol="AAPL", per_day=1, lag_hours=1):
    items = []
    for d in days:
        for k in range(per_day):
            published = pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=14 + k)
            seen = published + pd.Timedelta(hours=lag_hours)
            items.append(store.NewsItem(source="rss:x", source_kind="news", external_id=f"{d.date()}-{k}",
                                        published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        first_seen_at=seen.strftime("%Y-%m-%dT%H:%M:%SZ"), title=f"Apple story {d.date()} {k}"))
    store.add_items(conn, items)
    all_ids = store.load_items(conn)["item_id"].tolist()
    store.save_links(conn, [(i, symbol, "name") for i in all_ids])


def test_an_empty_store_has_no_history(conn):
    status = readiness.measure(conn)

    assert not status.ready and status.n_items == 0 and status.span_sessions == 0 and status.ready_on is None
    with pytest.raises(readiness.NewsHistoryTooShort, match="trop court"):
        readiness.require_history(conn)


def test_two_collection_days_are_nowhere_near_enough(conn):
    _add(conn, DAYS[:2])

    status = readiness.measure(conn, "AAPL")

    assert (status.news_days, status.span_sessions, status.ready) == (2, 2, False)
    assert status.ready_on == DAYS[0] + pd.offsets.BDay(readiness.MIN_SPAN_SESSIONS - 1)
    assert "248 séance(s)" in status.missing() and "58 jour(s)" in status.missing()


def test_a_year_of_daily_news_opens_the_gate(conn):
    _add(conn, DAYS[:readiness.MIN_SPAN_SESSIONS])

    status = readiness.require_history(conn, "AAPL")

    assert status.ready and status.span_sessions == readiness.MIN_SPAN_SESSIONS and status.missing() == ""


def test_a_long_span_with_too_few_news_days_stays_closed(conn):
    _add(conn, [DAYS[0], DAYS[readiness.MIN_SPAN_SESSIONS + 10]])

    status = readiness.measure(conn, "AAPL")

    assert status.span_sessions > readiness.MIN_SPAN_SESSIONS and status.news_days == 2 and not status.ready


def test_stale_news_do_not_count_as_history(conn):
    _add(conn, DAYS[:30], lag_hours=24 * 30)                                 # vues un mois après leur parution

    assert readiness.measure(conn, "AAPL").n_items == 0


def test_history_is_measured_per_symbol(conn):
    _add(conn, DAYS[:readiness.MIN_SPAN_SESSIONS], symbol="AAPL")
    other = store.load_items(conn)["item_id"].tolist()
    store.save_links(conn, [(i, "MSFT", "name") for i in other[:3]])

    assert readiness.measure(conn, "AAPL").ready
    assert not readiness.measure(conn, "MSFT").ready
    assert readiness.measure(conn, "ZZZ").n_items == 0


def test_training_features_are_refused_until_the_history_is_long_enough(conn):
    _add(conn, DAYS[:5])

    with pytest.raises(readiness.NewsHistoryTooShort):
        aggregate.training_features_for_symbol(conn, "AAPL", DAYS, service.LEXICON, service.lexicon_version())


def test_training_features_are_built_once_the_gate_is_open_and_stay_causal(conn):
    _add(conn, DAYS[:readiness.MIN_SPAN_SESSIONS])
    ids = store.load_items(conn)["item_id"].tolist()
    store.save_scores(conn, service.LEXICON, service.lexicon_version(), {i: (0.5, None) for i in ids})

    before = aggregate.training_features_for_symbol(conn, "AAPL", DAYS, service.LEXICON, service.lexicon_version(),
                                                    horizons=(1, 5))
    late = DAYS[readiness.MIN_SPAN_SESSIONS + 20]
    _add(conn, [late])                                                       # une nouvelle FUTURE arrive après coup
    new_id = max(store.load_items(conn)["item_id"])
    store.save_scores(conn, service.LEXICON, service.lexicon_version(), {new_id: (-1.0, None)})
    after = aggregate.training_features_for_symbol(conn, "AAPL", DAYS, service.LEXICON, service.lexicon_version(),
                                                   horizons=(1, 5))

    cutoff = DAYS[readiness.MIN_SPAN_SESSIONS + 19]
    pd.testing.assert_frame_equal(before.loc[:cutoff], after.loc[:cutoff])  # aucune variable passée ne bouge
    assert before.loc[DAYS[10], "news_sent_mean_1d"] == pytest.approx(0.5)


def test_the_page_summary_carries_the_history_without_loading_the_news(conn):
    _add(conn, DAYS[:12])

    history = service.summary(conn)["history"]

    assert history == {"news_days": 12, "span_sessions": 12, "required_sessions": readiness.MIN_SPAN_SESSIONS, "ready": False}
    assert service.summary(conn)["history"]["news_days"] == readiness.measure(conn).news_days
