import numpy as np
import pandas as pd

from marketml.validation.purge import compute_would_purge, purge_mask


def test_compute_would_purge_flags_rows_near_cut():
    all_dates = pd.bdate_range("2020-01-01", periods=30)
    cut_date = all_dates[20]
    # dates juste avant la coupure : leur fenêtre à horizon=5 dépasse cut_date
    base_index = all_dates[15:20]
    would_purge = compute_would_purge(all_dates, base_index, horizon=5, cut_date=cut_date)
    assert would_purge.iloc[-1]  # date 19 + 5 = 24 >= 20 -> True
    assert would_purge.iloc[0]  # date 15 + 5 = 20 -> déjà >= 20 -> True aussi
    # date bien avant la coupure : sa fenêtre ne l'atteint pas -> ne doit pas être purgée
    early_index = all_dates[0:2]
    would_purge_early = compute_would_purge(all_dates, early_index, horizon=5, cut_date=cut_date)
    assert not would_purge_early.any()


def test_purge_mask_only_removes_true_positions():
    all_dates = pd.bdate_range("2020-01-01", periods=30)
    cut_date = all_dates[20]
    train_mask = np.array([d < cut_date for d in all_dates])
    out = purge_mask(all_dates, train_mask, all_dates, horizon=5, cut_date=cut_date)
    assert out.sum() <= train_mask.sum()
    # les positions déjà à False restent à False
    assert not out[~train_mask].any()
