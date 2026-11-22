"""Moteur d'event study et tests de significativité sur données synthétiques (vérité connue)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from earnings_support import bench_frame, make_series, market_returns

from patrick.earnings import engine, signif
from patrick.earnings.config import EarningsConfig

N = 1500


@pytest.fixture(scope="module")
def rm():
    return market_returns(1, N)


def _sp(seed, rm, **kw):
    df = make_series(seed, n=N, market=rm, **kw)
    bench = bench_frame(rm)
    return engine.SymbolPrices(df, bench["Close"], bench["Open"]), df


def test_an_injected_reaction_is_recovered_and_the_gap_is_overnight(rm):
    sp, df = _sp(3, rm, shocks={600: 0.06}, gap_share=0.9)
    ev, why = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig())
    assert ev is not None, why
    ar0 = ev["ar"][engine.rel_index(0)]
    assert 0.045 < ar0 < 0.075
    assert ev["day0"] == str(df.index[600].date())
    assert abs(ev["on"][engine.rel_index(0)]) > abs(ev["id"][engine.rel_index(0)])        # le gros du mouvement est à l'ouverture
    stats0 = engine.reaction_stats(ev, EarningsConfig())
    assert stats0["window"] == (0, 0) and stats0["z"] > 3


def test_amc_shifts_the_reaction_to_the_next_session(rm):
    sp, df = _sp(3, rm, shocks={601: 0.06})
    ev, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="AMC", uncertain=False, cfg=EarningsConfig())
    assert ev["day0"] == str(df.index[601].date()) and ev["ar"][engine.rel_index(0)] > 0.04
    # même annonce lue comme « avant l'ouverture » : la réaction serait cherchée la veille, où il ne se passe rien
    wrong, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig())
    assert abs(wrong["ar"][engine.rel_index(0)]) < 0.03
    assert wrong["ar"][engine.rel_index(1)] > 0.04


def test_timing_diagnostic_flags_a_reaction_found_on_the_other_day(rm):
    sp, df = _sp(3, rm, shocks={601: 0.08})
    wrong, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig())
    right, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="AMC", uncertain=False, cfg=EarningsConfig())
    assert wrong["timing_suspect"] is True and right["timing_suspect"] is False


def test_other_announcements_are_kept_out_of_the_estimation_window(rm):
    shocks = {400: 0.15, 401: -0.12, 450: 0.14, 700: 0.05}
    sp, df = _sp(5, rm, shocks=shocks)
    others = [df.index[400], df.index[450]]
    with_excl, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[700], timing="BMO", uncertain=False,
                                        cfg=EarningsConfig(), other_days=others)
    without, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[700], timing="BMO", uncertain=False, cfg=EarningsConfig())
    assert with_excl["sigma"] < without["sigma"] * 0.85                  # sinon la variance résiduelle est gonflée
    assert with_excl["n_est"] < without["n_est"]


def test_events_without_enough_history_or_in_the_future_are_skipped(rm):
    sp, df = _sp(3, rm)
    cfg = EarningsConfig()
    assert engine.compute_event(sp, symbol="T", ann_date=df.index[40], timing="BMO", uncertain=False, cfg=cfg)[0] is None
    none, why = engine.compute_event(sp, symbol="T", ann_date=df.index[-1] + pd.Timedelta(days=10), timing="BMO", uncertain=False, cfg=cfg)
    assert none is None and "à venir" in why


def test_models_agree_in_sign_and_fall_back_when_data_is_missing(rm):
    sp, df = _sp(3, rm, shocks={600: 0.06})
    for model in ("market", "market_adjusted", "sector"):
        ev, why = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False,
                                       cfg=EarningsConfig(model=model))
        assert ev is not None, why
        assert ev["ar"][engine.rel_index(0)] > 0.04
    # le modèle à facteurs sans données de facteurs retombe sur le marché, et le dit
    ev, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig(model="factor"))
    assert ev["model_used"] == "market"


def test_factor_model_with_data_and_fallback_when_factors_are_stale(rm):
    idx = pd.bdate_range("2019-01-02", periods=N)
    rng = np.random.default_rng(4)
    factors = pd.DataFrame({"Mkt_RF": rm, "SMB": rng.normal(0, 0.003, N), "HML": rng.normal(0, 0.003, N),
                            "MOM": rng.normal(0, 0.004, N), "RF": 0.0001}, index=idx)
    df = make_series(8, n=N, market=rm, shocks={600: 0.06, 1400: 0.06})
    bench = bench_frame(rm)
    stale = factors.iloc[:1300]                                              # facteurs publiés avec retard : rien après la séance 1300
    sp = engine.SymbolPrices(df, bench["Close"], factors=stale)
    cfg = EarningsConfig(model="factor")
    ev, why = engine.compute_event(sp, symbol="T", ann_date=idx[600], timing="BMO", uncertain=False, cfg=cfg)
    assert ev["model_used"] == "factor" and ev["k"] == 5 and ev["ar"][engine.rel_index(0)] > 0.04, why
    late, _ = engine.compute_event(sp, symbol="T", ann_date=idx[1400], timing="BMO", uncertain=False, cfg=cfg)
    assert late["model_used"] == "market" and late["model_fallback"] is True and late["model_req"] == "factor"


def test_car_variance_matches_sigma_squared_times_length_plus_a_small_correction(rm):
    sp, df = _sp(3, rm, shocks={600: 0.06})
    ev, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig())
    v1, v5 = engine.car_variance(ev, 0, 0), engine.car_variance(ev, 0, 4)
    assert ev["sigma"] ** 2 <= v1 < ev["sigma"] ** 2 * 1.1
    assert v5 > 4.5 * ev["sigma"] ** 2


def test_window_helpers_and_bhar(rm):
    sp, df = _sp(3, rm, shocks={600: 0.06})
    ev, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig())
    ar = engine.arr(ev, "ar")
    assert engine.window_sum(ar, 0, 1) == pytest.approx(ar[engine.rel_index(0)] + ar[engine.rel_index(1)])
    assert engine.bhar(ev, 0, 20) == pytest.approx(engine.window_compound(engine.arr(ev, "ret"), 0, 20)
                                                   - engine.window_compound(engine.arr(ev, "er"), 0, 20))
    with pytest.raises(ValueError):
        engine.window_sum(ar, -20, 5)


def test_volume_and_liquidity_react_on_the_event_day(rm):
    sp, df = _sp(3, rm, shocks={600: 0.06}, volume_event_days=[600])
    ev, _ = engine.compute_event(sp, symbol="T", ann_date=df.index[600], timing="BMO", uncertain=False, cfg=EarningsConfig())
    assert ev["vol_ratio"][engine.rel_index(0)] > 1.5
    assert ev["vol_ratio"][engine.rel_index(-5)] < 1.5
    assert np.isfinite(ev["amihud_est"]) and ev["cs_est"] >= 0


def test_corwin_schultz_is_zero_for_a_flat_market_and_positive_with_wide_ranges():
    flat = engine.corwin_schultz(np.full(10, 100.0), np.full(10, 100.0))
    assert np.nanmax(flat[:-1]) == pytest.approx(0.0, abs=1e-9)
    rng = np.random.default_rng(0)
    low = 100 * (1 - rng.uniform(0.005, 0.03, 200))
    wide = engine.corwin_schultz(np.full(200, 100.0) * (1 + rng.uniform(0.0, 0.01, 200)), low)
    assert np.nanmean(wide) > 0


# ------------------------------------------------------------------------------------------------ tests de significativité

def _events(rm, n_events, shock, seed0=100, jitter=0.0):
    rows = []
    for k in range(n_events):
        pos = 400 + 17 * k
        sp, df = _sp(seed0 + k, rm, shocks={pos: shock + np.random.default_rng(k).normal(0, jitter)})
        ev, _ = engine.compute_event(sp, symbol=f"T{k}", ann_date=df.index[pos], timing="BMO", uncertain=False, cfg=EarningsConfig())
        rows.append(ev)
    return rows


def test_every_test_rejects_a_real_effect(rm):
    rows = _events(rm, 30, 0.04, jitter=0.01)
    out = signif.run_tests(rows, 0, 0, n_boot=500)
    assert out["n"] == 30 and out["caar"] > 0.03
    for name in ("cross", "patell", "bmp", "kp", "corrado", "sign", "bootstrap"):
        assert out["tests"][name]["p"] < 0.01, name


def test_no_test_rejects_pure_noise_too_often(rm):
    rejections = {name: 0 for name in ("bmp", "patell", "corrado", "sign", "bootstrap")}
    trials = 24
    for t in range(trials):
        rows = _events(rm, 20, 0.0, seed0=1000 + 40 * t)
        out = signif.run_tests(rows, 0, 0, n_boot=300)
        for name in rejections:
            rejections[name] += out["tests"][name]["p"] < 0.05
    for name, count in rejections.items():
        assert count / trials < 0.25, (name, count)        # taille nominale 5 % ; 24 essais => on tolère le bruit d'échantillonnage


def test_kolari_pynnonen_shrinks_the_statistic_when_events_share_non_market_shocks(rm):
    common = np.random.default_rng(77).normal(0, 0.010, N)         # choc sectoriel commun, que le modèle de marché ne retire pas
    rows = []
    for k in range(30):                                            # 30 annonces la même semaine, même secteur
        pos = 600 + (k % 3)
        sp, df = _sp(500 + k, rm, shocks={pos: 0.012}, common=common)
        ev, _ = engine.compute_event(sp, symbol=f"T{k}", ann_date=df.index[pos], timing="BMO", uncertain=False, cfg=EarningsConfig())
        rows.append(ev)
    out = signif.run_tests(rows, 0, 0, n_boot=200)
    assert out["rbar"] > 0.1                                       # corrélation transversale réelle
    assert abs(out["tests"]["kp"]["stat"]) < abs(out["tests"]["bmp"]["stat"])
    assert out["n_weeks"] == 1                                     # un seul bloc de dates : le bootstrap par blocs refuse de conclure
    assert out["tests"]["bootstrap"]["p"] is None


def test_abs_move_test_detects_large_reactions_of_either_sign(rm):
    rows = []
    for k in range(24):
        pos = 400 + 17 * k
        sign = 1 if k % 2 == 0 else -1
        sp, df = _sp(300 + k, rm, shocks={pos: sign * 0.05})
        ev, _ = engine.compute_event(sp, symbol=f"T{k}", ann_date=df.index[pos], timing="BMO", uncertain=False, cfg=EarningsConfig())
        rows.append(ev)
    signed = signif.run_tests(rows, 0, 0, n_boot=200)
    unsigned = signif.abs_move_test(rows, 0, 0)
    assert signed["tests"]["bmp"]["p"] > 0.2               # hausses et baisses s'annulent dans le CAAR
    assert unsigned["p_rank"] < 0.01 and unsigned["p_var"] < 0.01


def test_too_few_events_are_reported_not_tested(rm):
    out = signif.run_tests(_events(rm, 3, 0.04), 0, 0)
    assert out["tests"] == {} and "insuffisant" in out["note"]
