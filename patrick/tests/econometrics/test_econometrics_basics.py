"""Économétrie d'une série, partie 1 : processus simulés, transformations, racine unitaire, dépendance.

Tout est calculé sur des séries simulées à paramètres connus (graine fixe) : on vérifie que les tests retrouvent ce qu'on y a mis,
jamais un chiffre « qui a l'air plausible ». Aucun accès au réseau ni à la base."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.econometrics import serial as SE
from patrick.econometrics import simulate as SIM
from patrick.econometrics import transforms as T
from patrick.econometrics import unitroot as U


# ---------------------------------------------------------------- processus simulés
def test_garch11_simulation_has_the_theoretical_unconditional_variance():
    omega, alpha, beta = 0.2, 0.1, 0.8                      # variance inconditionnelle = omega / (1 - alpha - beta) = 2
    x = SIM.garch11(60000, omega, alpha, beta, seed=1)
    assert abs(x.var() - 2.0) / 2.0 < 0.1


def test_garch11_simulation_clusters_volatility_but_not_returns():
    x = SIM.garch11(6000, 0.05, 0.1, 0.85, seed=2)
    r1 = x.autocorr(1)
    sq1 = (x ** 2).autocorr(1)
    assert abs(r1) < 0.06 and sq1 > 0.1


def test_simulations_are_reproducible_for_a_given_seed():
    a = SIM.arma(300, ar=(0.5,), seed=7)
    b = SIM.arma(300, ar=(0.5,), seed=7)
    pd.testing.assert_series_equal(a, b)
    assert not np.allclose(a.to_numpy(), SIM.arma(300, ar=(0.5,), seed=8).to_numpy())


# ---------------------------------------------------------------- transformations
def _prices(n=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx, name="X")


def _ohlc(close):
    rng = np.random.default_rng(4)
    o = close.shift(1).fillna(close.iloc[0])
    spread = np.abs(rng.normal(0, 0.006, len(close))) * close
    return pd.DataFrame({"Open": o, "High": np.maximum(o, close) + spread, "Low": np.minimum(o, close) - spread, "Close": close})


def test_log_return_is_the_difference_of_logs_and_loses_one_row():
    p = _prices()
    x, info = T.apply_transform(p, "logret")
    assert len(x) == len(p) - 1
    np.testing.assert_allclose(x.to_numpy(), np.log(p).diff().dropna().to_numpy())
    assert info["kind"] == "logret" and info["fallback"] is False


def test_log_return_falls_back_to_a_difference_when_the_level_is_not_positive():
    s = pd.Series([1.0, 0.5, -0.2, 0.3, 0.1] * 20, index=pd.bdate_range("2020-01-01", periods=100))
    x, info = T.apply_transform(s, "logret")
    np.testing.assert_allclose(x.to_numpy(), s.diff().dropna().to_numpy())
    assert info["kind"] == "diff" and info["fallback"] is True


def test_squared_return_is_the_square_of_the_log_return():
    p = _prices()
    x, _ = T.apply_transform(p, "sqret")
    np.testing.assert_allclose(x.to_numpy(), np.log(p).diff().dropna().to_numpy() ** 2)


def test_parkinson_variance_matches_the_formula():
    # ln(H/L) = 1  =>  (ln(H/L))^2 / (4 ln 2)
    high = pd.Series([np.e], index=pd.to_datetime(["2020-01-02"]))
    low = pd.Series([1.0], index=high.index)
    np.testing.assert_allclose(T.parkinson_variance(high, low).iloc[0], 1.0 / (4 * np.log(2)))


def test_garman_klass_variance_matches_the_formula():
    # ln(H/L) = 1, ln(C/O) = 0  =>  0.5
    idx = pd.to_datetime(["2020-01-02"])
    gk = T.garman_klass_variance(pd.Series([1.0], idx), pd.Series([np.e], idx), pd.Series([1.0], idx), pd.Series([1.0], idx))
    np.testing.assert_allclose(gk.iloc[0], 0.5)


def test_range_based_variance_needs_ohlc_and_says_so():
    with pytest.raises(ValueError, match="OHLC"):
        T.apply_transform(_prices(), "parkinson")


def test_parkinson_transform_returns_positive_variances_from_ohlc():
    p = _prices()
    x, info = T.apply_transform(p, "parkinson", ohlc=_ohlc(p))
    assert (x > 0).all() and info["kind"] == "parkinson"


def test_fractional_difference_is_causal():
    p = _prices(500)
    full, _ = T.apply_transform(p, "fracdiff", d=0.4)
    cut, _ = T.apply_transform(p.iloc[:400], "fracdiff", d=0.4)
    common = cut.index
    np.testing.assert_allclose(full.loc[common].to_numpy(), cut.to_numpy())


def test_unknown_transform_is_refused():
    with pytest.raises(ValueError, match="inconnue"):
        T.apply_transform(_prices(), "cubic")


# ---------------------------------------------------------------- racine unitaire
def test_random_walks_are_read_as_unit_roots_and_noise_as_stationary_on_most_draws():
    # Un test à 5 % se trompe une fois sur vingt par construction : on vérifie la fréquence sur 20 tirages, pas un tirage chanceux.
    rw = [U.unit_root_tests(SIM.random_walk(800, seed=s))["verdict"] for s in range(20)]
    wn = [U.unit_root_tests(SIM.arma(800, seed=100 + s))["verdict"] for s in range(20)]
    assert rw.count("unit_root") >= 14 and rw.count("stationary") == 0
    assert wn.count("stationary") >= 17


def test_ar1_with_moderate_persistence_is_stationary():
    assert U.unit_root_tests(SIM.arma(1500, ar=(0.5,), seed=13))["verdict"] == "stationary"


@pytest.mark.parametrize("adf_p,kpss_p,expected", [
    (0.001, 0.50, "stationary"),
    (0.60, 0.01, "unit_root"),
    (0.001, 0.01, "contradictory"),
    (0.60, 0.50, "inconclusive"),
])
def test_cross_reading_of_adf_and_kpss(adf_p, kpss_p, expected):
    assert U.cross_verdict(adf_p, kpss_p, alpha=0.05) == expected


def test_every_test_reports_statistic_pvalue_and_its_null_hypothesis():
    res = U.unit_root_tests(SIM.arma(800, ar=(0.4,), seed=14))
    for name in ("adf", "kpss", "pp", "dfgls"):
        t = res["tests"][name]
        assert {"stat", "pvalue", "lags", "null"} <= set(t) and 0 <= t["pvalue"] <= 1
    assert res["tests"]["adf"]["null"] != res["tests"]["kpss"]["null"]


def test_zivot_andrews_locates_a_level_shift():
    rng = np.random.default_rng(15)
    n = 1000
    x = pd.Series(rng.normal(0, 1, n) + 4.0 * (np.arange(n) > n // 2), index=pd.bdate_range("2012-01-02", periods=n))
    za = U.zivot_andrews(x)
    assert abs(za["break_index"] - n // 2) < 0.05 * n
    assert za["pvalue"] < 0.05 and za["break_date"] == x.index[za["break_index"]].strftime("%Y-%m-%d")


def test_unit_root_tests_refuse_a_series_that_is_too_short():
    with pytest.raises(ValueError, match="minimum"):
        U.unit_root_tests(pd.Series(np.arange(20.0)))


# ---------------------------------------------------------------- dépendance
def test_dependence_summary_sees_clustering_in_garch_but_not_in_noise():
    arch = SE.dependence_summary(SIM.garch11(3000, 0.05, 0.12, 0.83, seed=21), nlags=20)
    iid = SE.dependence_summary(SIM.arma(3000, seed=22), nlags=20)
    assert arch["arch_lm_p"] < 0.001 and arch["ljung_box_squared_p"]["10"] < 0.001
    assert iid["arch_lm_p"] > 0.01 and iid["ljung_box_squared_p"]["10"] > 0.01
    assert len(arch["acf"]) == 20 and arch["band"] == pytest.approx(1.96 / np.sqrt(3000))


def test_bds_rejects_a_deterministic_chaotic_series_and_not_noise():
    n = 800
    x = np.empty(n)
    x[0] = 0.3
    for i in range(1, n):
        x[i] = 3.9 * x[i - 1] * (1 - x[i - 1])              # carte logistique : déterministe, non linéaire, sans autocorrélation simple
    chaos = SE.bds_test(pd.Series(x))
    noise = SE.bds_test(pd.Series(np.random.default_rng(23).normal(size=n)))
    assert min(r["pvalue"] for r in chaos["rows"]) < 1e-6
    assert min(r["pvalue"] for r in noise["rows"]) > 0.001


def test_bds_on_arch_residuals_that_are_still_dependent_is_flagged():
    res = SE.bds_test(SIM.garch11(2500, 0.05, 0.15, 0.80, seed=24))
    assert res["rejects_iid"] is True
