"""Phase 6.1 (P6.1) -- CPCV (Combinatorial Purged Cross-Validation),
`patrick/validation/cpcv.py`. Tests explicitement demandés par le rapport de
correction : aucun chemin ne contient d'observation à la fois en train et en
test, le purge est appliqué aux deux frontières de chaque groupe de test
intérieur, le nombre de chemins correspond à la formule."""
from __future__ import annotations

from math import comb

import numpy as np
import pytest

from patrick.validation.cpcv import (
    DEFAULT_K_TEST_GROUPS,
    DEFAULT_N_GROUPS,
    all_combinations,
    all_splits,
    build_groups,
    build_split,
    n_paths,
    path_assignment,
    path_performance_distribution,
)


def test_n_paths_matches_formula():
    for n_groups, k in [(6, 2), (7, 2), (8, 2), (7, 3), (10, 2)]:
        expected = comb(n_groups, k) * k // n_groups
        assert n_paths(n_groups, k) == expected
        # identité combinatoire : C(N,k)*k/N == C(N-1,k-1)
        assert n_paths(n_groups, k) == comb(n_groups - 1, k - 1)


def test_default_n_groups_k_gives_exactly_six_paths():
    """La raison d'être de P6.1 (cf. docstring module) : rendre le PBO
    satisfiable (C5, MIN_BLOCKS=6) sans calcul combinatoire superflu."""
    assert n_paths(DEFAULT_N_GROUPS, DEFAULT_K_TEST_GROUPS) == 6
    # confirmation que c'est bien le couple MINIMAL (N,k=2) atteignant 6
    assert n_paths(DEFAULT_N_GROUPS - 1, DEFAULT_K_TEST_GROUPS) < 6


def test_build_groups_covers_all_bars_contiguously_no_gap_no_overlap():
    for n_bars, n_groups in [(700, 7), (100, 6), (1000, 10), (37, 5)]:
        groups = build_groups(n_bars, n_groups)
        assert len(groups) == n_groups
        assert groups[0][0] == 0
        assert groups[-1][1] == n_bars - 1
        for (s1, e1), (s2, e2) in zip(groups, groups[1:]):
            assert e1 + 1 == s2, "groupes doivent être contigus, sans trou ni chevauchement"
        assert sum(e - s + 1 for s, e in groups) == n_bars


@pytest.mark.parametrize("n_groups,k", [(6, 2), (7, 2), (8, 2), (7, 3)])
def test_path_assignment_uses_each_group_exactly_once_per_path(n_groups, k):
    combos = all_combinations(n_groups, k)
    pa = path_assignment(n_groups, k)
    assert len(pa) == n_paths(n_groups, k)
    for path_index, entries in pa.items():
        groups_seen = [g for g, _ in entries]
        assert sorted(groups_seen) == list(range(n_groups)), (
            f"chemin {path_index} doit couvrir chaque groupe exactement une fois"
        )
        # chaque (groupe, combo) doit être une combinaison qui contient bien ce groupe en test
        for g, ci in entries:
            assert g in combos[ci]


def test_no_observation_is_both_train_and_test_in_any_split():
    """Exigence explicite du rapport de correction : aucun chemin (aucun
    split) ne doit avoir d'observation à la fois en train ET en test."""
    n_bars = 700
    splits = all_splits(n_bars, n_groups=7, k_test_groups=2, horizon=5)
    assert len(splits) == comb(7, 2)
    for split in splits:
        overlap = split.train_mask & split.test_mask
        assert not overlap.any(), f"combo {split.test_groups} : chevauchement train/test détecté"


def test_purge_applied_at_both_boundaries_of_interior_test_group():
    """Exigence explicite du rapport de correction : purge aux DEUX
    frontières d'un groupe de test intérieur (train des deux côtés) --
    contrairement au walk-forward qui n'a qu'une seule frontière."""
    n_bars = 700
    horizon = 8
    groups = build_groups(n_bars, 7)
    # groupe 3 : intérieur (groupes 0-2 avant, 4-6 après) -- combo (3,) seul en test
    # (k=1 ponctuel pour isoler proprement les deux frontières d'un seul groupe)
    split = build_split(groups, (3,), horizon=horizon)
    g3_start, g3_end = groups[3]

    # frontière AVANT : les `horizon` dernières positions de train avant le
    # groupe de test doivent être purgées.
    assert not split.train_mask[g3_start - horizon:g3_start].any(), (
        "frontière avant non purgée"
    )
    # frontière APRÈS : les `horizon` premières positions de train après le
    # groupe de test doivent être purgées.
    assert not split.train_mask[g3_end + 1:g3_end + 1 + horizon].any(), (
        "frontière après non purgée"
    )
    # au-delà de la marge de purge des deux côtés, le train doit réapparaître
    assert split.train_mask[g3_start - horizon - 5:g3_start - horizon].any(), (
        "purge trop large : mange du train au-delà de la marge attendue côté avant"
    )
    assert split.train_mask[g3_end + 1 + horizon:g3_end + 1 + horizon + 5].any(), (
        "purge trop large : mange du train au-delà de la marge attendue côté après"
    )


def test_edge_test_group_only_purged_on_its_single_train_side():
    """Un groupe de test en bord d'historique (le tout premier ou le tout
    dernier) n'a du train que d'UN côté -- la purge ne doit agir que là."""
    n_bars = 700
    horizon = 8
    groups = build_groups(n_bars, 7)
    split_first = build_split(groups, (0,), horizon=horizon)
    g0_start, g0_end = groups[0]
    assert g0_start == 0  # rien avant -- pas de frontière "avant" à purger
    assert not split_first.train_mask[g0_end + 1:g0_end + 1 + horizon].any()

    split_last = build_split(groups, (6,), horizon=horizon)
    g6_start, g6_end = groups[6]
    assert g6_end == n_bars - 1  # rien après -- pas de frontière "après" à purger
    assert not split_last.train_mask[g6_start - horizon:g6_start].any()


def test_two_adjacent_test_groups_need_no_purge_between_them():
    """Deux groupes de test ADJACENTS dans la même combinaison n'ont pas de
    train entre eux : rien à purger à LEUR frontière commune (test-test).
    Le groupe 3 a lui-même un embargo en tête, côté groupe 2 (train) --
    attendu, non testé ici ; seule la jonction interne 3|4 est vérifiée."""
    n_bars = 700
    horizon = 8
    groups = build_groups(n_bars, 7)
    split = build_split(groups, (3, 4), horizon=horizon)
    g3_start, g3_end = groups[3]
    g4_start, g4_end = groups[4]
    # autour de la jonction 3|4 (à distance de l'embargo de tête du groupe 3) :
    # entièrement en test, aucun trou.
    assert split.test_mask[g3_start + horizon + 1:g4_end + 1].all()
    assert split.test_mask[g3_end - 5:g3_end + 1].all()
    assert split.test_mask[g4_start:g4_start + 5].all()


def test_embargo_removes_leading_test_rows_after_train_boundary():
    n_bars = 700
    horizon = 5
    embargo_bars = 3
    groups = build_groups(n_bars, 7)
    split = build_split(groups, (3,), horizon=horizon, embargo_bars=embargo_bars)
    g3_start, _ = groups[3]
    assert not split.test_mask[g3_start:g3_start + embargo_bars].any()
    assert split.test_mask[g3_start + embargo_bars]


def test_path_performance_distribution_reports_median_quantiles_std_not_a_point():
    values = {i: v for i, v in enumerate([0.40, 0.45, 0.50, 0.55, 0.60, 0.65])}
    dist = path_performance_distribution(values)
    assert dist["n_paths"] == 6
    assert dist["median"] == pytest.approx(0.525)
    assert dist["q05"] < dist["median"] < dist["q95"]
    assert dist["std"] > 0.0


def test_path_performance_distribution_handles_nans_and_empty():
    dist_nan = path_performance_distribution({0: float("nan"), 1: 0.5})
    assert dist_nan["n_paths"] == 1
    dist_empty = path_performance_distribution({})
    assert dist_empty["n_paths"] == 0
    assert dist_empty["median"] != dist_empty["median"]  # NaN
