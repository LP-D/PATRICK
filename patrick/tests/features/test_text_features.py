"""Variables texte dans l'entraînement (A4) : porte des 250 séances, colonnes point-in-time, drapeau hors du hachage."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import FeaturesConfig, ObjectiveConfig, RunConfig
from patrick.features import text_features as tf
from patrick.text import readiness, service, store
from patrick.tracking import db as trackdb


def _seed(conn, days: pd.DatetimeIndex, symbol="AAPL"):
    rng = np.random.default_rng(0)
    items = []
    for i, d in enumerate(days):
        when = (d + pd.Timedelta(hours=14)).tz_localize("UTC")
        items.append(store.NewsItem("press", "news", f"n{i}", when, f"Apple update {i}", first_seen_at=when))
        if i % 5 == 0:
            items.append(store.NewsItem("rss:fed_monetary", "central_bank", f"c{i}", when, f"FOMC note {i}", first_seen_at=when))
    store.add_items(conn, items)
    rows = conn.execute("SELECT item_id, source_kind FROM news_item").fetchall()
    store.save_scores(conn, service.LEXICON, service.lexicon_version(),
                      {i: (float(rng.uniform(-1, 1)), None) for i, k in rows if k == "news"})
    store.save_scores(conn, service.TONE, service.TONE_VERSION, {i: (float(rng.uniform(-1, 1)), None) for i, k in rows if k == "central_bank"})
    store.save_links(conn, [(i, symbol, "test") for i, k in rows if k == "news"])


@pytest.fixture
def conn(tmp_path):
    c = trackdb.connect(tmp_path / "t.db")
    yield c
    c.close()


def test_gate_refuses_a_short_history(conn):
    days = pd.bdate_range("2026-01-05", periods=40)
    _seed(conn, days)
    with pytest.raises(readiness.NewsHistoryTooShort):
        tf.build_text_features(days, "AAPL", conn=conn)


def test_columns_are_point_in_time(conn):
    days = pd.bdate_range("2025-01-06", periods=280)
    _seed(conn, days)
    out = tf.build_text_features(days, "AAPL", conn=conn)
    assert {"news_sent_mean_5d", "news_attention_20d", "cb_sent_mean_20d", "cb_days_since"} <= set(out.columns)
    assert out.index.equals(days) and out["news_sent_mean_1d"].notna().sum() > 200
    # une nouvelle publiée après la clôture du jour t n'atteint que la séance suivante : retirer la fin du magasin ne change pas le passé
    cut = days[200]
    conn.execute("DELETE FROM news_item WHERE published_at >= ?", (cut.strftime("%Y-%m-%d"),))
    conn.commit()
    trimmed = tf.aggregate.features_for_symbol(conn, "AAPL", days, service.LEXICON, service.lexicon_version(), horizons=tf.HORIZONS)
    pd.testing.assert_series_equal(out["news_sent_mean_5d"].iloc[:200], trimmed["news_sent_mean_5d"].iloc[:200].set_axis(days[:200]),
                                   check_names=False)


def test_flag_is_off_by_default_and_outside_the_hash_until_switched_on():
    from patrick.pipeline.engine import _config_hash

    assert FeaturesConfig().enable_text_features is False

    def cfg(on: bool) -> RunConfig:
        return RunConfig(objective=ObjectiveConfig(target_symbol="^GSPC"), features=FeaturesConfig(enable_text_features=on))
    assert _config_hash(cfg(False)) == _config_hash(RunConfig(objective=ObjectiveConfig(target_symbol="^GSPC")))
    assert _config_hash(cfg(True)) != _config_hash(cfg(False))


def test_the_pool_builds_text_columns_only_with_the_flag(monkeypatch):
    from patrick.pipeline import engine

    idx = pd.bdate_range("2024-01-01", periods=300)
    raw = pd.DataFrame({"^GSPC": np.linspace(100, 130, 300)}, index=idx)
    calls = []
    monkeypatch.setattr(tf, "build_text_features",
                        lambda index, symbol, conn=None: calls.append(symbol) or pd.DataFrame({"news_sent_mean_1d": 0.1}, index=index))

    def pool(on):
        cfg = RunConfig(objective=ObjectiveConfig(target_symbol="^GSPC"), features=FeaturesConfig(families=["spike"], enable_text_features=on))
        return engine._build_base_feature_pool(raw, cfg, "^GSPC")
    off, on = pool(False), pool(True)
    assert "news_sent_mean_1d" not in off.columns and "news_sent_mean_1d" in on.columns and calls == ["^GSPC"]
