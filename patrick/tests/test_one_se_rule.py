"""Règle de parcimonie « une erreur-type » (audit externe du 2026-10-19, point 2).

`Leaderboard.best` prend la configuration de plus haute moyenne sur les plis ; avec des centaines de candidats aux
scores presque égaux, ce maximum est du bruit (le départage actuel ne joue que sur des égalités EXACTES). La règle
classique : parmi les configurations dont la moyenne est à moins d'une erreur-type de la meilleure, prendre la plus
simple (le moins de variables). Optionnelle (`selection.one_se_rule`, désactivée par défaut : elle change le gagnant,
donc les résultats de référence).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from patrick.config.schema import RunConfig
from patrick.pipeline import engine
from patrick.pipeline.leaderboard import Leaderboard


def _board(scores_by_n: dict[int, list[float]], algo: str = "XGBoost", horizon: int = 5) -> Leaderboard:
    board = Leaderboard()
    for n_feat, scores in scores_by_n.items():
        for fold, value in enumerate(scores, start=1):
            board.add(horizon=horizon, regime="GLOBAL", N=n_feat, sampler="none", algo=algo, fold=fold, F1_dir=value)
    return board


def test_without_the_rule_the_highest_mean_wins():
    board = _board({3: [0.50] * 4, 5: [0.60, 0.59, 0.60, 0.59], 12: [0.62, 0.58, 0.60, 0.60]})
    assert board.best(metric="F1_dir")["N"] == 12


def test_the_simplest_configuration_within_one_standard_error_wins():
    # N=12 : moyenne 0,600, erreur-type ~0,0082. N=5 : 0,595 -> dans l'erreur-type, et plus simple. N=3 : 0,50, hors.
    board = _board({3: [0.50] * 4, 5: [0.60, 0.59, 0.60, 0.59], 12: [0.62, 0.58, 0.60, 0.60]})
    chosen = board.best(metric="F1_dir", one_se=True)
    assert chosen["N"] == 5
    assert chosen["F1_dir"] == pytest.approx(0.595)


def test_a_clear_winner_outside_the_standard_error_is_kept():
    board = _board({3: [0.50] * 4, 5: [0.55] * 4, 12: [0.62, 0.58, 0.60, 0.60]})
    assert board.best(metric="F1_dir", one_se=True)["N"] == 12


def test_among_equally_simple_candidates_the_better_mean_wins():
    board = Leaderboard()
    for algo, scores in (("RandomForest", [0.60, 0.60, 0.60, 0.60]), ("XGBoost", [0.61, 0.60, 0.61, 0.60])):
        for fold, value in enumerate(scores, start=1):
            board.add(horizon=5, regime="GLOBAL", N=5, sampler="none", algo=algo, fold=fold, F1_dir=value)
    assert board.best(metric="F1_dir", one_se=True)["algo"] == "XGBoost"


def test_the_rule_needs_several_folds_to_have_a_standard_error():
    board = _board({3: [0.59], 12: [0.60]})
    assert board.best(metric="F1_dir", one_se=True)["N"] == 12          # une seule valeur par essai : pas d'erreur-type


def test_the_returned_row_has_the_same_shape_with_or_without_the_rule():
    board = _board({3: [0.50] * 4, 5: [0.60, 0.59, 0.60, 0.59], 12: [0.62, 0.58, 0.60, 0.60]})
    assert set(board.best(metric="F1_dir")) == set(board.best(metric="F1_dir", one_se=True))


def _state(one_se_rule: bool, board: Leaderboard):
    config = RunConfig.model_validate({
        "name": "t", "objective": {"target_symbol": "X", "horizons": [5]}, "output": {"dir": "out"},
        "selection": {"one_se_rule": one_se_rule}})
    return SimpleNamespace(config=config, board=board)


def test_the_final_selection_follows_the_configuration_flag():
    import pandas as pd

    board = _board({3: [0.50] * 4, 5: [0.60, 0.59, 0.60, 0.59], 12: [0.62, 0.58, 0.60, 0.60]})
    for flag, expected_n in ((False, 12), (True, 5)):
        st = _state(flag, board)
        _final, by_horizon = engine._select_finals(st, board.best(metric="F1_dir", one_se=flag), pd.DataFrame())
        assert by_horizon[5]["N"] == expected_n


def test_the_rule_is_off_by_default():
    assert RunConfig.model_validate({"name": "t", "objective": {"target_symbol": "X"},
                                     "output": {"dir": "out"}}).selection.one_se_rule is False


def test_enabling_the_rule_changes_the_config_hash_and_disabling_it_keeps_the_historic_one():
    """Une config dont la règle est désactivée garde le hachage d'avant le champ (reprise des runs, noms d'études Optuna) ;
    l'activer change les résultats, donc le hachage."""
    base = {"name": "t", "objective": {"target_symbol": "X"}, "output": {"dir": "out"}}
    off = RunConfig.model_validate({**base, "selection": {"one_se_rule": False}})
    on = RunConfig.model_validate({**base, "selection": {"one_se_rule": True}})
    assert engine._config_hash(off) == engine._config_hash(RunConfig.model_validate(base))
    assert engine._config_hash(off) != engine._config_hash(on)
