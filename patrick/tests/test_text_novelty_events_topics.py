"""Nouveauté d'une news, extraction d'événements, thèmes et plongements : tout est point-in-time ou ajusté sur l'entraînement."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.text import events, novelty, topics

T0 = pd.Timestamp("2024-03-04 09:00", tz="UTC")


def _times(*hours):
    return pd.DatetimeIndex([T0 + pd.Timedelta(hours=h) for h in hours])


# --- nouveauté ---------------------------------------------------------------------------------------------------------

def test_a_repeated_story_is_not_novel_and_an_unrelated_one_is():
    texts = ["Fed holds rates steady, signals patience", "Oil jumps after pipeline outage in Libya",
             "Fed holds rates steady and signals patience"]
    out = novelty.novelty_scores(texts, _times(0, 1, 2))
    assert out.iloc[0] == 1.0
    assert out.iloc[1] > 0.9
    assert out.iloc[2] < 0.2


def test_novelty_ignores_stories_older_than_the_window():
    texts = ["Fed holds rates steady", "Fed holds rates steady"]
    assert novelty.novelty_scores(texts, _times(0, 24 * 10), window_days=7).iloc[1] == 1.0
    assert novelty.novelty_scores(texts, _times(0, 24 * 3), window_days=7).iloc[1] < 0.1


def test_novelty_never_looks_at_the_future():
    texts = ["Fed holds rates steady", "Gold rallies on safe haven demand"]
    alone = novelty.novelty_scores(texts[:1], _times(0)).iloc[0]
    later_twin = novelty.novelty_scores(texts[:1] + ["Fed holds rates steady"], _times(0, 5)).iloc[0]
    assert alone == later_twin == 1.0


def test_simultaneous_stories_do_not_see_each_other():
    out = novelty.novelty_scores(["Fed holds rates", "Fed holds rates"], _times(0, 0))
    assert list(out) == [1.0, 1.0]


def test_novelty_keeps_the_input_order_and_index():
    idx = pd.Index([10, 20, 30])
    out = novelty.novelty_scores(["gold rallies hard", "fed holds rates", "gold rallies hard"], _times(5, 1, 6), index=idx)
    assert list(out.index) == [10, 20, 30]
    assert out.loc[20] == 1.0                      # la plus ancienne
    assert out.loc[30] == pytest.approx(0.0, abs=1e-9)   # même texte que 10, paru une heure plus tôt
    assert out.loc[10] > out.loc[30]


# --- événements ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("OPEC+ agrees to a production cut as pipeline outage hits supply", {"supply_shock"}),
    ("US imposes new sanctions on Russian oil exporters", {"sanction"}),
    ("Dockworkers go on strike at major ports", {"strike"}),
    ("Hurricane threatens Gulf of Mexico refineries", {"weather"}),
    ("Sécheresse historique : la récolte de blé menacée", {"weather"}),
    ("Grève des mineurs au Chili, la production de cuivre à l'arrêt", {"strike"}),
    ("Refinery fire after hurricane, sanctions loom", {"supply_shock", "weather", "sanction"}),
])
def test_event_tags(text, expected):
    assert set(events.extract_events(text)) == expected


def test_ordinary_uses_of_strike_are_not_events():
    for text in ("Apple strikes a deal with Disney", "options with a strike price of 150", "airstrike reported"):
        assert events.extract_events(text) == []


# --- thèmes et plongements ------------------------------------------------------------------------------------------------

OIL = ["crude oil prices rise as OPEC cuts output", "oil supply pipeline refinery outage", "Brent crude barrel exports fall",
       "OPEC oil output cut lifts crude barrel", "refinery crude pipeline oil exports"] * 4
BANK = ["central bank raises interest rates inflation", "Fed policy rate decision inflation committee",
        "ECB governing council rate hike inflation", "interest rate decision committee inflation target",
        "central bank committee policy inflation rates"] * 4


def test_topics_separate_two_vocabularies_and_rows_sum_to_one():
    model = topics.fit_topics(OIL + BANK, n_topics=2, seed=0)
    dist = model.transform(["crude oil barrel refinery", "central bank rate inflation committee"])
    assert dist.shape == (2, 2)
    assert np.allclose(dist.sum(axis=1), 1.0)
    assert dist[0].argmax() != dist[1].argmax()
    words = {w for topic in model.top_words(5) for w in topic}
    assert {"oil", "inflation"} <= words


def test_topic_model_is_reproducible():
    a = topics.fit_topics(OIL + BANK, n_topics=2, seed=3).transform(["oil refinery"])
    b = topics.fit_topics(OIL + BANK, n_topics=2, seed=3).transform(["oil refinery"])
    assert np.allclose(a, b)


def test_lsa_embedding_places_similar_stories_close():
    emb = topics.fit_embedder(OIL + BANK, n_components=4, seed=0)
    v = emb.transform(["crude oil barrel exports", "oil refinery pipeline output", "central bank interest rate inflation"])
    cos = lambda a, b: float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    assert cos(v[0], v[1]) > cos(v[0], v[2])
    assert v.shape == (3, 4)


def test_embedder_is_fitted_on_the_training_texts_only():
    emb = topics.fit_embedder(OIL, n_components=2, seed=0)
    v = emb.transform(["bitcoin halving"])           # vocabulaire jamais vu : vecteur nul, pas d'erreur
    assert np.allclose(v, 0.0)
