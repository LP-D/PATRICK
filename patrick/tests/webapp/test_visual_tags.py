"""Couleur fixe par famille de modèle (VI21) et badge de classe d'actifs (VI22), du 26/11."""
from __future__ import annotations

import pytest

from patrick.webapp.visual_tags import algo_key, algo_tag, asset_class_key, iclass


@pytest.mark.parametrize(("name", "key"), [("XGBoost", "xgboost"), ("LightGBM", "lightgbm"), ("RandomForest", "forest"), ("GRU", "rnn"),
                                           ("LSTM", "rnn"), ("Transformer", "transformer"), ("PPO", "rl"), ("Inconnu", "other")])
def test_every_family_has_one_fixed_key(name, key):
    assert algo_key(name) == key


def test_the_tag_escapes_the_name_and_carries_its_family():
    assert str(algo_tag("XGBoost")) == '<span class="algo-tag" data-algo="xgboost">XGBoost</span>'
    assert "&lt;b&gt;" in str(algo_tag("<b>")) and str(algo_tag(None)) == "—"


@pytest.mark.parametrize(("symbol", "key"), [("EURUSD=X", "fx"), ("BTC-USD", "crypto"), ("GC=F", "futures"), ("^VIX", "volatility_index"),
                                             ("^GSPC", "index"), ("AAPL", "equity"), ("MC.PA", "equity")])
def test_asset_class_badges(symbol, key):
    assert asset_class_key(symbol) == key
    assert f'data-ac="{key}"' in str(iclass(symbol))


def test_unknown_symbols_get_no_badge():
    assert str(iclass(None)) == ""
