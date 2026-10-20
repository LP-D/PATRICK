"""Règle de parcimonie « une erreur-type » (audit externe du 2026-10-19, point 2).

`Leaderboard.best` prend la configuration de plus haute moyenne sur les plis ; avec des centaines de candidats aux
scores presque égaux, ce maximum est du bruit (le départage actuel ne joue que sur des égalités EXACTES). La règle
classique : parmi les configurations dont la moyenne est à moins d'une erreur-type de la meilleure, prendre la plus
simple (le moins de variables). Activée par défaut (`selection.one_se_rule`, décision du 2026-10-20) ; désactivable, et une
configuration qui la désactive garde le hachage d'avant le champ.
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


def test_the_rule_is_on_by_default():
    assert RunConfig.model_validate({"name": "t", "objective": {"target_symbol": "X"},
                                     "output": {"dir": "out"}}).selection.one_se_rule is True


def _hashed_payload(config, monkeypatch) -> bytes:
    """Ce que `_config_hash` donne réellement à SHA-256 (capturé, pas recalculé)."""
    seen: list[bytes] = []
    real = engine.hashlib.sha256
    monkeypatch.setattr(engine.hashlib, "sha256", lambda data=b"": (seen.append(data), real(data))[1])
    engine._config_hash(config)
    return seen[0]


def test_disabling_the_rule_keeps_the_historic_hash_and_the_default_changes_it(monkeypatch):
    """Une config dont la règle est désactivée garde la charge utile d'avant le champ (reprise des runs, noms d'études Optuna) ;
    la règle active (défaut) change les résultats, donc le hachage."""
    base = {"name": "t", "objective": {"target_symbol": "X"}, "output": {"dir": "out"}}
    off = RunConfig.model_validate({**base, "selection": {"one_se_rule": False}})
    on = RunConfig.model_validate(base)
    assert b"one_se_rule" not in _hashed_payload(off, monkeypatch)
    assert b'"one_se_rule":true' in _hashed_payload(on, monkeypatch)
    assert engine._config_hash(off) != engine._config_hash(on)


# --- La règle doit gouverner le gagnant FINAL, pas seulement le classement du scan -----------------------------------------
# Constaté sur le golden de la CI (2026-10-20) : le candidat réglé par Optuna était le maximum simple du scan, puis
# `_select_finals` comparait le candidat simple du scan à ce candidat réglé (qui gagne presque toujours) : la règle était
# neutralisée sans bruit dès que le réglage est actif. Elle s'applique donc aussi au choix des candidats à régler, au choix
# parmi les configurations réglées, et à la stabilité mesurée sur le gagnant.

def _config(flag: bool, *, top_k: int = 1) -> RunConfig:
    return RunConfig.model_validate({
        "name": "t", "objective": {"target_symbol": "X", "horizons": [5]}, "output": {"dir": "out"},
        "selection": {"one_se_rule": flag}, "tuning": {"top_k": top_k}})


SCAN = {3: [0.50] * 4, 5: [0.60, 0.59, 0.60, 0.59], 12: [0.62, 0.58, 0.60, 0.60]}       # N=12 : maximum ; N=5 : à une erreur-type


def test_the_configuration_sent_to_optuna_is_the_rules_choice():
    for flag, expected_n in ((False, 12), (True, 5)):
        candidates = engine._tuning_candidates(SimpleNamespace(config=_config(flag), board=_board(SCAN)))
        assert [c["N"] for c in candidates] == [expected_n]


def test_with_several_candidates_the_rules_choice_leads_and_the_rest_follow_by_mean():
    candidates = engine._tuning_candidates(SimpleNamespace(config=_config(True, top_k=2), board=_board(SCAN)))
    assert [c["N"] for c in candidates] == [5, 12]
    off = engine._tuning_candidates(SimpleNamespace(config=_config(False, top_k=2), board=_board(SCAN)))
    assert [c["N"] for c in off] == [12, 5]


def _tuned(scores_by_n: dict[int, list[float]], horizon: int = 5):
    import pandas as pd

    return pd.DataFrame([{"horizon": horizon, "fold": fold, "regime": "GLOBAL", "N": n_feat, "sampler": "none",
                          "algo": "XGBoost", "best_params": "{'depth': 3}", "F1_dir": value}
                         for n_feat, scores in scores_by_n.items() for fold, value in enumerate(scores, start=1)])


def test_the_final_model_is_chosen_among_tuned_configurations_by_the_rule_too():
    tuned = _tuned({5: [0.65, 0.64, 0.65, 0.64], 12: [0.67, 0.63, 0.65, 0.65]})        # N=12 : 0,650 ; N=5 : 0,645 (dans l'erreur-type)
    for flag, expected_n in ((False, 12), (True, 5)):
        st = SimpleNamespace(config=_config(flag), board=_board(SCAN))
        final, by_horizon = engine._select_finals(st, st.board.best(metric="F1_dir", one_se=flag), tuned)
        assert by_horizon[5]["N"] == expected_n and final["N"] == expected_n
        assert "best_params" in by_horizon[5]                                           # c'est bien la configuration RÉGLÉE


def test_a_tuned_configuration_still_has_to_beat_the_scan_choice_to_replace_it():
    tuned = _tuned({5: [0.50] * 4})                                                      # le réglage n'aide pas
    st = SimpleNamespace(config=_config(True), board=_board(SCAN))
    _final, by_horizon = engine._select_finals(st, st.board.best(metric="F1_dir", one_se=True), tuned)
    assert by_horizon[5]["N"] == 5 and "best_params" not in by_horizon[5]               # le candidat du scan reste


def test_feature_stability_is_measured_on_the_rules_winner(monkeypatch):
    board = Leaderboard()
    for n_feat, scores in ((5, [0.60, 0.59, 0.60, 0.59]), (12, [0.62, 0.58, 0.60, 0.60])):
        for fold, value in enumerate(scores, start=1):
            board.add(horizon=5, regime="GLOBAL", N=n_feat, sampler="none", algo="XGBoost", fold=fold, F1_dir=value,
                      features="|".join(f"f{i}" for i in range(n_feat)))
    seen = {}
    monkeypatch.setattr(engine.trackdb, "save_feature_stability",
                        lambda conn, run_id, mean_jaccard, n_folds, freq: seen.update(n_features=len(freq)))
    monkeypatch.setattr(engine.trackdb, "record_phase_timing", lambda *args, **kwargs: None)
    for flag, expected in ((False, 12), (True, 5)):
        config = _config(flag)
        st = SimpleNamespace(config=config, board=board, is_walkforward=True, run_ids={5: "r5"}, conn=None)
        engine._track_stability(st)
        assert seen["n_features"] == expected
