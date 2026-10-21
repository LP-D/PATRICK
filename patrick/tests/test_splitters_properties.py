"""Propriétés des découpeurs temporels, pour des tailles quelconques (Hypothesis).

Les tests par exemple (`test_cpcv.py`, `test_purge*.py`) vérifient quelques tailles choisies à la main ; un découpeur
n'a pas le droit de se tromper pour AUCUNE taille (reste de division, groupes d'un seul point, horizon plus long qu'un
groupe...). Chaque propriété énonce ce qui ne doit jamais arriver : une ligne à la fois d'entraînement et de test, une
étiquette d'entraînement qui déborde sur le test, une coupe qui recule.
"""
from __future__ import annotations

from itertools import pairwise
from math import comb

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from patrick.validation import cpcv, embargo, purge, walkforward

PROFILE = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def groups_and_combo(draw):
    n_groups = draw(st.integers(3, 9))
    k = draw(st.integers(1, n_groups - 1))
    n_bars = draw(st.integers(n_groups, 600))
    combo = tuple(sorted(draw(st.lists(st.integers(0, n_groups - 1), min_size=k, max_size=k, unique=True))))
    return n_bars, n_groups, combo


# --- CPCV : groupes ---------------------------------------------------------------------------------------------------

@PROFILE
@given(st.integers(2, 14), st.data())
def test_groups_tile_the_history_without_gap_or_overlap(n_groups, data):
    n_bars = data.draw(st.integers(n_groups, 5000))
    groups = cpcv.build_groups(n_bars, n_groups)
    assert len(groups) == n_groups
    assert groups[0][0] == 0 and groups[-1][1] == n_bars - 1
    assert all(b[0] == a[1] + 1 for a, b in pairwise(groups))     # contigus
    sizes = [end - start + 1 for start, end in groups]
    assert max(sizes) - min(sizes) <= 1 and min(sizes) >= 1


@PROFILE
@given(st.integers(3, 9), st.data())
def test_every_path_evaluates_each_group_exactly_once(n_groups, data):
    k = data.draw(st.integers(1, n_groups - 1))
    paths = cpcv.path_assignment(n_groups, k)
    assert len(paths) == cpcv.n_paths(n_groups, k) == comb(n_groups - 1, k - 1)
    combos = cpcv.all_combinations(n_groups, k)
    for entries in paths.values():
        assert sorted(g for g, _ in entries) == list(range(n_groups))
        assert all(g in combos[ci] for g, ci in entries)       # le groupe est bien en test dans cette combinaison


# --- CPCV : séparation entraînement / test ---------------------------------------------------------------------------

@PROFILE
@given(groups_and_combo(), st.integers(1, 40), st.one_of(st.none(), st.integers(0, 40)))
def test_no_row_is_both_train_and_test_and_train_keeps_its_distance(args, horizon, embargo_bars):
    n_bars, n_groups, combo = args
    groups = cpcv.build_groups(n_bars, n_groups)
    split = cpcv.build_split(groups, combo, horizon, embargo_bars)

    assert not (split.train_mask & split.test_mask).any()
    in_test_groups = np.zeros(n_bars, dtype=bool)
    for gi in combo:
        in_test_groups[groups[gi][0]:groups[gi][1] + 1] = True
    assert not (split.test_mask & ~in_test_groups).any()       # le test ne sort jamais de ses groupes
    assert not (split.train_mask & in_test_groups).any()        # l'entraînement n'y entre jamais

    # Purge des deux côtés : aucune ligne d'entraînement à `horizon` barres ou moins d'un groupe de test.
    for gi in combo:
        start, end = groups[gi]
        near = np.zeros(n_bars, dtype=bool)
        near[max(start - horizon, 0):min(end + horizon, n_bars - 1) + 1] = True
        assert not (split.train_mask & near).any()


@PROFILE
@given(groups_and_combo(), st.integers(1, 40), st.integers(1, 40))
def test_embargo_only_trims_the_leading_rows_of_a_test_block_that_follows_train(args, horizon, embargo_bars):
    """Un bloc de test = des groupes de test contigus. L'embargo se mesure depuis la frontière entraînement -> test : il
    coupe le début du bloc (même s'il déborde sur un groupe voisin plus court que l'embargo), jamais ailleurs."""
    n_bars, n_groups, combo = args
    groups = cpcv.build_groups(n_bars, n_groups)
    split = cpcv.build_split(groups, combo, horizon, embargo_bars)
    runs, current = [], [combo[0]]
    for gi in combo[1:]:
        if gi == current[-1] + 1:
            current.append(gi)
        else:
            runs.append(current)
            current = [gi]
    runs.append(current)
    for run in runs:
        start, end = groups[run[0]][0], groups[run[-1]][1]
        kept = np.flatnonzero(split.test_mask[start:end + 1])
        length = end - start + 1
        dropped = length - len(kept)
        if run[0] == 0:                                   # rien avant : pas d'entraînement à la frontière, pas d'embargo
            assert dropped == 0
        else:
            assert dropped == min(embargo_bars, length)
            if len(kept):
                assert kept[0] == dropped and (np.diff(kept) == 1).all()     # on ne coupe que le début, d'un bloc


# --- Walk-forward -----------------------------------------------------------------------------------------------------

@PROFILE
@given(st.integers(30, 4000), st.integers(1, 12), st.floats(0.2, 0.8))
def test_walk_forward_cuts_move_forward_and_never_leave_the_history(n_obs, n_folds, min_train_frac):
    dates = pd.bdate_range("2000-01-03", periods=n_obs)
    cuts = walkforward.build_fold_cuts(dates, n_folds, min_train_frac)
    assert len(cuts) == n_folds + 1
    assert cuts[0] == int(n_obs * min_train_frac) and cuts[-1] == n_obs
    assert all(a <= b for a, b in pairwise(cuts))
    # Le premier pli s'entraîne sur au moins `min_train_frac` de l'historique, toujours avant ce qu'il teste.
    assert cuts[0] >= 1 and cuts[0] < cuts[-1]


# --- Purge et embargo (walk-forward) ---------------------------------------------------------------------------------

@PROFILE
@given(st.integers(40, 400), st.integers(1, 30), st.data())
def test_purge_leaves_no_train_label_that_reaches_the_cut(n, horizon, data):
    dates = pd.bdate_range("2010-01-04", periods=n)
    cut_pos = data.draw(st.integers(horizon + 1, n - 1))
    train_mask = np.arange(n) < cut_pos
    purged = purge.purge_mask(dates, train_mask, dates, horizon, dates[cut_pos])
    assert not (purged & ~train_mask).any()                      # ne fait que retirer
    kept = np.flatnonzero(purged)
    assert (kept + horizon < cut_pos).all()                      # l'étiquette de chaque ligne gardée finit avant la coupe
    assert purged.sum() == max(cut_pos - horizon, 0)             # et on ne retire rien de plus que nécessaire


@PROFILE
@given(st.integers(20, 300), st.integers(0, 40), st.data())
def test_embargo_drops_only_the_first_rows_after_the_cut(n, embargo_bars, data):
    dates = pd.bdate_range("2010-01-04", periods=n)
    cut_pos = data.draw(st.integers(1, n - 1))
    test_mask = np.arange(n) >= cut_pos
    out = embargo.embargo_mask(dates, test_mask, dates[cut_pos], embargo_bars)
    assert not (out & ~test_mask).any()
    kept = np.flatnonzero(out)
    expected_drop = min(embargo_bars, n - cut_pos)
    assert len(kept) == (n - cut_pos) - expected_drop
    if len(kept):
        assert kept[0] == cut_pos + expected_drop
