"""Agrégation du sentiment par actif et par horizon, garde-fou contre la fuite des LLM, event study textuel."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.text import aggregate, llm_guard, store

DAYS = pd.bdate_range("2024-01-01", periods=400)


def _items(rows):
    """rows : [(horodatage UTC, score)]"""
    return pd.DataFrame({"known_at": [pd.Timestamp(t, tz="UTC") for t, _ in rows], "score": [s for _, s in rows]})


# 15:00 UTC = 10:00 à New York (avant la clôture) ; 23:00 UTC = 18:00 à New York (après la clôture)
BEFORE = "2024-01-10 15:00"
AFTER = "2024-01-10 23:00"


def test_an_item_enters_the_session_it_was_known_before_the_close():
    f = aggregate.sentiment_features(_items([(BEFORE, 0.5)]), DAYS, horizons=(1,))
    assert f.loc["2024-01-10", "news_sent_mean_1d"] == pytest.approx(0.5)
    assert f.loc["2024-01-09", "news_sent_mean_1d"] != f.loc["2024-01-09", "news_sent_mean_1d"]   # NaN


def test_an_item_after_the_close_enters_the_next_session():
    f = aggregate.sentiment_features(_items([(AFTER, -0.4)]), DAYS, horizons=(1,))
    assert np.isnan(f.loc["2024-01-10", "news_sent_mean_1d"])
    assert f.loc["2024-01-11", "news_sent_mean_1d"] == pytest.approx(-0.4)


def test_window_mean_per_horizon_and_missing_when_no_news():
    f = aggregate.sentiment_features(_items([(BEFORE, 0.6), ("2024-01-12 15:00", -0.2)]), DAYS, horizons=(1, 5))
    assert f.loc["2024-01-12", "news_sent_mean_5d"] == pytest.approx(0.2)
    assert f.loc["2024-01-12", "news_sent_mean_1d"] == pytest.approx(-0.2)
    assert np.isnan(f.loc["2024-01-11", "news_sent_mean_1d"])        # pas de news n'est pas « neutre »
    assert np.isnan(f.loc["2024-02-20", "news_sent_mean_5d"])


def test_unscored_items_count_for_attention_but_not_for_the_mean():
    f = aggregate.sentiment_features(_items([(BEFORE, 0.5), ("2024-01-10 16:00", np.nan)]), DAYS, horizons=(1,))
    assert f.loc["2024-01-10", "news_count_1d"] == 2
    assert f.loc["2024-01-10", "news_sent_mean_1d"] == pytest.approx(0.5)


def test_exponential_average_decays_toward_recent_news():
    f = aggregate.sentiment_features(_items([(BEFORE, 1.0), ("2024-01-17 15:00", -1.0)]), DAYS, horizons=(5,))
    later = f.loc["2024-01-17", "news_sent_ewm_5d"]
    assert -1.0 < later < 0.0                                          # le récent domine mais l'ancien pèse encore
    assert f.loc["2024-01-12", "news_sent_ewm_5d"] == pytest.approx(1.0)   # un seul item : sa valeur, quel que soit son âge


def test_novelty_weighted_mean_downweights_recycled_stories():
    items = _items([(BEFORE, 1.0), ("2024-01-10 16:00", -1.0)])
    items["novelty"] = [1.0, 0.0]
    f = aggregate.sentiment_features(items, DAYS, horizons=(1,))
    assert f.loc["2024-01-10", "news_sent_nov_1d"] == pytest.approx(1.0)
    assert f.loc["2024-01-10", "news_sent_mean_1d"] == pytest.approx(0.0)


def test_attention_is_a_point_in_time_zscore():
    rng = np.random.default_rng(0)
    rows = [(d + pd.Timedelta(hours=15), 0.0) for d in DAYS[:300] for _ in range(int(rng.integers(1, 4)))]
    spike_day = DAYS[300]
    rows += [(spike_day + pd.Timedelta(hours=15), 0.0)] * 30
    items = _items([(str(t), s) for t, s in rows])
    f = aggregate.sentiment_features(items, DAYS, horizons=(1,))
    assert f.loc[spike_day, "news_attention_1d"] > 5
    assert abs(f.loc[DAYS[200], "news_attention_1d"]) < 4


def test_attention_compares_a_day_with_the_sessions_before_it_not_including_itself():
    counts = [1, 2] * 30 + [10]
    rows = [(str(DAYS[i] + pd.Timedelta(hours=15)), 0.0) for i, c in enumerate(counts) for _ in range(c)]
    f = aggregate.sentiment_features(_items(rows), DAYS, horizons=(1,), attention_lookback=252)
    prev = np.array(counts[:-1], dtype=float)
    expected = (10 - prev.mean()) / prev.std(ddof=1)
    assert f.loc[DAYS[60], "news_attention_1d"] == pytest.approx(expected)


def test_features_of_the_past_do_not_change_when_the_future_arrives():
    rows = [(f"2024-0{m}-{d:02d} 15:00", 0.1 * m - 0.3) for m in (1, 2, 3) for d in (3, 8, 15, 22)]
    full = aggregate.sentiment_features(_items(rows), DAYS, horizons=(1, 5, 20))
    cut = aggregate.sentiment_features(_items(rows[:6]), DAYS, horizons=(1, 5, 20))
    until = pd.Timestamp("2024-02-14")
    pd.testing.assert_frame_equal(full.loc[:until], cut.loc[:until])


def test_missing_known_at_is_refused():
    items = pd.DataFrame({"known_at": [pd.NaT], "score": [0.1]})
    with pytest.raises(ValueError, match="published_at|known_at"):
        aggregate.sentiment_features(items, DAYS)


def test_features_from_the_database_use_links_and_known_at(conn):
    now = "2024-01-10T15:00:00Z"
    store.add_items(conn, [
        store.NewsItem("rss:t", "news", "a", now, "Apple soars", first_seen_at=now),
        store.NewsItem("rss:t", "news", "b", now, "Gold slips", first_seen_at=now),
        # publiée le 8 mais vue le 20 : invisible avant le 20
        store.NewsItem("rss:t", "news", "c", "2024-01-08T15:00:00Z", "Apple recalls", first_seen_at="2024-01-20T15:00:00Z"),
    ])
    ids = dict(conn.execute("SELECT external_id, item_id FROM news_item"))
    store.save_scores(conn, "lexicon", "v1", {ids["a"]: (0.8, None), ids["b"]: (-0.5, None), ids["c"]: (-0.9, None)})
    store.save_links(conn, [(ids["a"], "AAPL", "name"), (ids["b"], "GC=F", "theme"), (ids["c"], "AAPL", "name")])
    f = aggregate.features_for_symbol(conn, "AAPL", DAYS, scorer="lexicon", version="v1", horizons=(1,))
    assert f.loc["2024-01-10", "news_sent_mean_1d"] == pytest.approx(0.8)
    assert f.loc["2024-01-22", "news_sent_mean_1d"] == pytest.approx(-0.9)
    assert np.isnan(f.loc["2024-01-09", "news_sent_mean_1d"])          # la news « c » n'existait pas encore
    assert f.loc["2024-01-22", "news_count_1d"] == 1
    empty = aggregate.features_for_symbol(conn, "TSLA", DAYS, scorer="lexicon", version="v1", horizons=(1,))
    assert empty["news_count_1d"].sum() == 0


# --- garde-fou contre la fuite temporelle des LLM -----------------------------------------------------------------------

def test_dates_before_the_cutoff_plus_margin_are_contaminated():
    llm_guard.register_cutoff("test-model", "2024-06-30")
    mask = llm_guard.clean_mask("test-model", ["2024-01-01", "2024-06-30", "2024-08-01", "2024-10-15"], margin_days=60)
    assert list(mask) == [False, False, False, True]


def test_unknown_model_is_refused_not_assumed_clean():
    with pytest.raises(llm_guard.UnknownModelError):
        llm_guard.knowledge_cutoff("modele-inconnu")


def test_assert_clean_lists_the_contaminated_dates():
    llm_guard.register_cutoff("test-model-2", "2024-06-30")
    with pytest.raises(llm_guard.LeakageError, match="2024-03-01"):
        llm_guard.assert_clean("test-model-2", ["2024-03-01", "2025-03-01"])
    llm_guard.assert_clean("test-model-2", ["2025-03-01"])


def test_a_documented_cutoff_ships_with_the_package():
    assert llm_guard.knowledge_cutoff("claude-sonnet-5-5") >= pd.Timestamp("2026-01-01")


# --- event study textuel ------------------------------------------------------------------------------------------------

def _prices_with_reactions(days, up_days, down_days, jump=0.03, seed=1):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0002, 0.01, len(days))
    for d in up_days:
        r[days.get_loc(d)] += jump
    for d in down_days:
        r[days.get_loc(d)] -= jump
    return pd.Series(100 * np.exp(np.cumsum(r)), index=days)


def test_textual_event_study_separates_good_and_bad_news():
    days = pd.bdate_range("2018-01-01", periods=1500)
    up = list(days[400:1400:50])
    down = [d + pd.Timedelta(days=0) for d in days[425:1425:50]]
    prices = _prices_with_reactions(days, up, down)
    bench = _prices_with_reactions(days, [], [], seed=7)
    items = pd.DataFrame({
        "known_at": [pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=14) for d in up + down],     # 09:00 à New York
        "score": [0.8] * len(up) + [-0.8] * len(down),
        "novelty": [1.0] * (len(up) + len(down)),
    })
    studies = aggregate.textual_event_study(prices, items, benchmark=bench, min_abs_score=0.5, event_window=(-2, 3))
    assert set(studies) == {"positive", "negative"}
    assert studies["positive"].tests((0, 0))["caar"] > 0.02
    assert studies["negative"].tests((0, 0))["caar"] < -0.02


def test_textual_event_study_drops_weak_and_recycled_news():
    days = pd.bdate_range("2018-01-01", periods=800)
    prices = _prices_with_reactions(days, [], [])
    items = pd.DataFrame({
        "known_at": [pd.Timestamp(days[300], tz="UTC") + pd.Timedelta(hours=14),
                     pd.Timestamp(days[400], tz="UTC") + pd.Timedelta(hours=14)],
        "score": [0.1, 0.9], "novelty": [1.0, 0.05],
    })
    studies = aggregate.textual_event_study(prices, items, benchmark=prices * 1.0, model="market_adjusted",
                                            min_abs_score=0.5, min_novelty=0.3)
    assert studies == {}
