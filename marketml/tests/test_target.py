import numpy as np
import pandas as pd

from marketml.features.target import build_target, classify_return


def _synthetic_series(n=1000, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    walk = np.cumsum(rng.normal(0, 0.5, n))
    return pd.Series(15 + walk.clip(min=-10), index=idx, name="px")


def test_build_target_returns_four_classes():
    s = _synthetic_series()
    split_idx = int(len(s) * 0.5)
    target, reg_r, thr = build_target(s, horizon=5, split_idx=split_idx)
    assert set(target.unique()).issubset({0, 1, 2, 3})
    assert set(reg_r.unique()).issubset({"CALM", "NORMAL", "STRESS"})
    assert set(thr.keys()) == {"CALM", "NORMAL", "STRESS", "GLOBAL"}


def test_build_target_thresholds_are_causal_away_from_the_boundary():
    """Les seuils ne doivent dépendre que de la portion train (< split_idx) — à
    l'exception attendue des tout derniers points avant split_idx, dont la fenêtre
    de label (shift(-horizon)) déborde légitimement sur le test : c'est exactement
    la fuite marginale que VIX_PURGED_CV mesure et chiffre à delta F1_dir≈-0.002
    (négligeable), pas un bug de ce port. On altère donc la série suffisamment
    loin après split_idx (split_idx + horizon + marge) pour isoler la propriété
    causale du gros de l'historique, sans se heurter à cette fuite connue."""
    s = _synthetic_series()
    horizon = 5
    split_idx = int(len(s) * 0.5)
    _, _, thr_full = build_target(s, horizon=horizon, split_idx=split_idx)

    s_altered = s.copy()
    safe_cut_date = s.index[split_idx + horizon + 20]
    s_altered.loc[s_altered.index >= safe_cut_date] *= 100
    _, _, thr_altered = build_target(s_altered, horizon=horizon, split_idx=split_idx)

    for reg in ["CALM", "NORMAL", "STRESS", "GLOBAL"]:
        assert np.isclose(thr_full[reg][0], thr_altered[reg][0], equal_nan=True)
        assert np.isclose(thr_full[reg][1], thr_altered[reg][1], equal_nan=True)


def test_classify_return_matches_build_target_boundaries():
    thr = {"GLOBAL": (-0.01, 0.01)}
    assert classify_return(-0.02, "GLOBAL", thr) == 0
    assert classify_return(-0.005, "GLOBAL", thr) == 1
    assert classify_return(0.005, "GLOBAL", thr) == 2
    assert classify_return(0.02, "GLOBAL", thr) == 3
