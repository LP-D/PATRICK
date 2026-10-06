"""Cible alpha, jalon 2b : champs de configuration, benchmark résolu et enregistré, hachage des runs bruts inchangé."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from patrick.config.schema import RunConfig
from patrick.pipeline.engine import _config_hash


def _cfg(**objective) -> RunConfig:
    return RunConfig.model_validate({
        "name": "hash_probe",
        "objective": {"target_symbol": "^TEST", "horizons": [3, 5], "regimes": ["GLOBAL"], **objective},
        "universe": {"yf_tickers": ["SPX_LIKE"], "start_date": "2015-01-01"},
        "output": {"dir": "runs_probe", "seed": 42}})


def _alpha(symbol="MC.PA", **objective) -> RunConfig:
    return RunConfig.model_validate({
        "name": "alpha_probe",
        "objective": {"target_symbol": symbol, "horizons": [5], "regimes": ["GLOBAL"], "target_kind": "alpha",
                      **objective},
        "universe": {"yf_tickers": ["SPX_LIKE"], "start_date": "2015-01-01"},
        "output": {"dir": "runs_probe", "seed": 42}})


def test_raw_run_hash_is_unchanged_by_the_new_fields():
    """Valeur calculée AVANT l'ajout de target_kind/benchmark : changer ce hachage casserait la reprise des runs
    existants (noms d'études Optuna) et les empreintes de référence."""
    assert _config_hash(_cfg()) == "5197c2fe5c3a66c8"


def test_raw_is_the_default_and_leaves_the_universe_alone():
    cfg = _cfg()
    assert (cfg.objective.target_kind, cfg.objective.benchmark, cfg.objective.benchmark_source) == ("raw", None, None)
    assert cfg.universe.yf_tickers == ["SPX_LIKE"]


def test_alpha_resolves_the_benchmark_automatically_and_records_it():
    cfg = _alpha("MC.PA")
    assert cfg.objective.benchmark == "^STOXX50E" and cfg.objective.benchmark_source == "auto"
    assert "^STOXX50E" in cfg.universe.yf_tickers and "SPX_LIKE" in cfg.universe.yf_tickers   # téléchargé et décalé comme les autres


def test_alpha_keeps_a_manual_benchmark():
    cfg = _alpha("MC.PA", benchmark=" ^fchi ")
    assert (cfg.objective.benchmark, cfg.objective.benchmark_source) == ("^FCHI", "manual")
    assert "^FCHI" in cfg.universe.yf_tickers


def test_alpha_does_not_duplicate_a_benchmark_already_in_the_universe():
    cfg = RunConfig.model_validate({
        "objective": {"target_symbol": "AAPL", "horizons": [5], "target_kind": "alpha"},
        "universe": {"yf_tickers": ["^GSPC", "GC=F"], "start_date": "2015-01-01"}})
    assert cfg.universe.yf_tickers.count("^GSPC") == 1


def test_a_stored_alpha_config_revalidates_to_the_same_config():
    """Un run relancé ou repris relit `config_json` : le benchmark enregistré (et sa provenance) ne bouge pas."""
    cfg = _alpha("MC.PA")
    again = RunConfig.model_validate(json.loads(cfg.model_dump_json()))
    assert again.model_dump() == cfg.model_dump()
    assert again.objective.benchmark_source == "auto"
    assert _config_hash(again) == _config_hash(cfg)


def test_alpha_hash_differs_from_the_raw_hash_and_from_another_benchmark():
    raw, alpha, other = _cfg(), _alpha("^TEST"), _alpha("^TEST", benchmark="URTH")
    assert len({_config_hash(raw), _config_hash(alpha), _config_hash(other)}) == 3


@pytest.mark.parametrize("symbol, objective, message", [
    ("BTC-USD", {}, "manuel"),                                       # aucun benchmark automatique
    ("^VIX", {}, "manuel"),
    ("AAPL", {"benchmark": "aapl"}, "lui-même"),
    ("AAPL", {"benchmark": "a b"}, "invalide"),
    ("DGS10", {"target_source": "fred"}, "FRED"),
])
def test_alpha_without_a_usable_benchmark_is_refused_with_an_explanation(symbol, objective, message):
    with pytest.raises(ValidationError, match=message):
        _alpha(symbol, **objective)


def test_a_benchmark_without_alpha_is_refused():
    with pytest.raises(ValidationError, match="alpha"):
        _cfg(benchmark="^GSPC")


def test_btc_can_be_alpha_with_a_manual_benchmark():
    cfg = _alpha("BTC-USD", benchmark="^GSPC")
    assert cfg.objective.benchmark == "^GSPC"
