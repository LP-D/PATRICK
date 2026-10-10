"""Études de la page Exploration (`patrick/exploration/`) : chaque étude est testée sur des séries synthétiques dont on connaît la
vérité (lien injecté, décalage injecté, marche aléatoire...), jamais sur des données de marché : le test échoue si l'étude ne retrouve
pas ce qui a été planté, ou si elle « trouve » un lien là où il n'y en a pas."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from patrick.exploration import panel as P
from patrick.exploration import studies as S

N = 1500


def _idx(n=N, start="2015-01-01"):
    return pd.bdate_range(start, periods=n)


def _rets(**cols):
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=_idx(n))


@pytest.fixture
def rng():
    return np.random.default_rng(7)


# --------------------------------------------------------------------------- panneau


def _loader_from(series: dict):
    def load(symbol, source):
        return series.get(symbol)
    return load


def test_levels_are_aligned_before_returns_are_computed():
    # b est coté un jour sur deux de moins : les rendements de a doivent couvrir les MÊMES intervalles que ceux de b
    idx = _idx(200)
    a = pd.Series(np.exp(np.linspace(0, 1, 200)), index=idx)
    b = a.iloc[::2] * 2
    pan = P.build_panel(["A", "B"], {}, _loader_from({"A": a, "B": b}))
    assert list(pan.levels.index) == list(b.index)
    assert pan.returns.shape == (len(b) - 1, 2)
    assert np.allclose(pan.returns["A"], pan.returns["B"])          # même courbe, mêmes intervalles


def test_auto_transform_uses_log_for_prices_and_difference_for_levels_that_change_sign(rng):
    idx = _idx(120)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 120))), index=idx)
    spread = pd.Series(rng.normal(0, 1, 120).cumsum(), index=idx)       # change de signe
    pan = P.build_panel(["PX", "SP"], {}, _loader_from({"PX": price, "SP": spread}))
    assert pan.transforms == {"PX": "log", "SP": "diff"}
    assert any("Transformations mélangées" in w for w in pan.warnings)


def test_a_log_request_falls_back_to_difference_on_a_non_positive_level(rng):
    idx = _idx(80)
    s = pd.Series(rng.normal(0, 1, 80).cumsum(), index=idx)
    pan = P.build_panel(["S", "T"], {}, _loader_from({"S": s, "T": s * 2}), transform="log")
    assert set(pan.transforms.values()) == {"diff"}


def test_a_monthly_series_is_excluded_from_a_daily_panel_instead_of_being_forward_filled(rng):
    idx = _idx(1200)
    daily = pd.Series(100 + rng.normal(0, 1, 1200).cumsum() + 500, index=idx)
    monthly = daily.resample("ME").last()
    pan = P.build_panel(["D", "M"], {"M": "fred"}, _loader_from({"D": daily, "M": monthly}),
                        periodicity=lambda s, src: "monthly" if s == "M" else "daily")
    assert list(pan.returns.columns) == ["D"]
    assert "M" in pan.dropped and any("Exclus" in w for w in pan.warnings)
    pan_m = P.build_panel(["D", "M"], {"M": "fred"}, _loader_from({"D": daily, "M": monthly}), freq="M",
                          periodicity=lambda s, src: "monthly" if s == "M" else "daily")
    assert list(pan_m.returns.columns) == ["D", "M"]


def test_too_few_common_dates_is_a_readable_error():
    idx = _idx(20)
    s = pd.Series(np.arange(1.0, 21.0), index=idx)
    with pytest.raises(P.PanelError, match="dates communes"):
        P.build_panel(["A"], {}, _loader_from({"A": s}))


def test_selection_limits_and_loader_failures_are_reported(rng):
    with pytest.raises(P.PanelError, match="au moins un actif"):
        P.build_panel([], {}, _loader_from({}))
    with pytest.raises(P.PanelError, match="Au plus"):
        P.build_panel([f"S{i}" for i in range(P.MAX_ASSETS + 1)], {}, _loader_from({}))

    def boom(symbol, source):
        if symbol == "BAD":
            raise RuntimeError("réseau coupé")
        return pd.Series(100 + rng.normal(0, 1, 100).cumsum() + 500, index=_idx(100))

    pan = P.build_panel(["OK", "BAD"], {}, boom)
    assert list(pan.returns.columns) == ["OK"] and "réseau coupé" in pan.dropped["BAD"]


def test_the_requested_start_trims_the_panel_and_a_late_listing_is_flagged(rng):
    idx = _idx(600)
    old = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 600))), index=idx)
    new = old.iloc[300:] * 1.5
    pan = P.build_panel(["OLD", "NEW"], {}, _loader_from({"OLD": old, "NEW": new}), start="2015-01-01")
    assert pan.levels.index[0] == new.index[0]
    assert any("Période commune réduite" in w and "NEW" in w for w in pan.warnings)


# --------------------------------------------------------------------------- corrélations


def test_correlation_recovers_a_planted_link_and_finds_none_between_independent_series(rng):
    x = rng.normal(size=N)
    df = _rets(A=x, B=0.8 * x + 0.6 * rng.normal(size=N), C=rng.normal(size=N), D=rng.normal(size=N))
    out = S.correlation(df, "pearson")
    labels = out["labels"]
    mat = np.array(out["matrix"], dtype=float)
    ia, ib = labels.index("A"), labels.index("B")
    assert mat[ia, ib] == pytest.approx(0.8, abs=0.05)
    sig = out["significant"]
    assert sig[ia][ib] is True
    ic, id_ = labels.index("C"), labels.index("D")
    assert sig[ic][id_] is False                              # indépendants : pas de faux positif après correction
    assert out["n_tests"] == 6 and out["n_obs"] == N
    json.dumps(out)                                           # sortie sérialisable


def test_correlation_orders_correlated_assets_next_to_each_other(rng):
    f1, f2 = rng.normal(size=N), rng.normal(size=N)
    cols = {"X1": f1 + 0.3 * rng.normal(size=N), "Y1": f2 + 0.3 * rng.normal(size=N),
            "X2": f1 + 0.3 * rng.normal(size=N), "Y2": f2 + 0.3 * rng.normal(size=N)}
    order = S.correlation(_rets(**cols))["labels"]
    pos = {k: order.index(k) for k in cols}
    assert abs(pos["X1"] - pos["X2"]) == 1 and abs(pos["Y1"] - pos["Y2"]) == 1


@pytest.mark.parametrize("method", ["spearman", "kendall"])
def test_rank_correlations_resist_an_outlier(method, rng):
    x = rng.normal(size=300)
    y = x + 0.5 * rng.normal(size=300)
    y[0] = 1e6                                                # une valeur aberrante détruit Pearson, pas les rangs
    df = _rets(A=x, B=y)
    assert abs(S.correlation(df, "pearson")["matrix"][0][1]) < 0.2
    assert S.correlation(df, method)["matrix"][0][1] > 0.6


def test_unknown_correlation_method_is_refused(rng):
    with pytest.raises(ValueError, match="méthode inconnue"):
        S.correlation(_rets(A=rng.normal(size=60), B=rng.normal(size=60)), "cosine")


def test_rolling_correlation_tracks_a_regime_change(rng):
    x = rng.normal(size=N)
    noise = rng.normal(size=N)
    y = np.where(np.arange(N) < N // 2, noise, x + 0.2 * noise)        # corrélés seulement en seconde moitié
    out = S.rolling_correlation(_rets(A=x, B=y), "A", "B", window=60)
    assert out["first_half_mean"] < 0.2 and out["second_half_mean"] > 0.7
    assert out["noise_band"] == pytest.approx(1 / math.sqrt(60))
    with pytest.raises(ValueError):
        S.rolling_correlation(_rets(A=x, B=y), "A", "A")
    with pytest.raises(ValueError):
        S.rolling_correlation(_rets(A=x, B=y), "A", "B", window=5000)


# --------------------------------------------------------------------------- distribution


def test_describe_rejects_normality_for_fat_tails_only(rng):
    n = 3000
    df = _rets(NORM=rng.normal(0, 0.01, n), FAT=rng.standard_t(3, n) * 0.01)
    lv = np.exp(df.cumsum())
    rows = {r["symbol"]: r for r in S.describe(df, lv, 252)["rows"]}
    assert rows["NORM"]["normal_rejected"] is False and rows["FAT"]["normal_rejected"] is True
    assert rows["FAT"]["excess_kurtosis"] > 3 > rows["NORM"]["excess_kurtosis"]
    for r in rows.values():
        assert r["var99"] <= r["var95"] <= 0 and r["es95"] <= r["var95"] and r["es99"] <= r["var99"]
        assert -1 < r["max_drawdown"] <= 0
        assert r["vol_ann"] == pytest.approx(np.std(df[r["symbol"]], ddof=1) * math.sqrt(252))


def test_describe_skips_the_drawdown_of_a_difference_series(rng):
    df = _rets(RATE=rng.normal(0, 0.05, 300))
    lv = df.cumsum() + 3
    row = S.describe(df, lv, 252, {"RATE": "diff"})["rows"][0]
    assert row["max_drawdown"] is None and row["transform"] == "diff"


# --------------------------------------------------------------------------- mémoire et stationnarité


def test_random_walks_keep_their_unit_root_while_their_returns_are_stationary(rng):
    # Un test à 5 % rejette à tort 1 marche aléatoire sur 20 : on juge sur un lot, pas sur un tirage.
    verdicts = []
    for _ in range(30):
        steps = rng.normal(0, 0.01, 1500)
        lv = pd.DataFrame({"RW": 100 * np.exp(np.cumsum(steps))}, index=_idx(1500))
        ret = pd.DataFrame({"RW": steps[1:]}, index=lv.index[1:])
        row = S.stationarity(lv, ret)["rows"][0]
        verdicts.append(row)
    assert sum(1 for r in verdicts if r["return_stationary"]) >= 26
    kept = sum(1 for r in verdicts if r["adf_level_p"] > 0.05)
    assert kept >= 26
    assert float(np.median([r["hurst"] for r in verdicts])) == pytest.approx(0.5, abs=0.1)
    assert {r["hurst_label"] for r in verdicts} <= {"random_walk", "mean_reverting", "trending"}


def test_a_mean_reverting_series_is_flagged_stationary_with_a_low_hurst(rng):
    x = np.zeros(2000)
    for t in range(1, 2000):
        x[t] = 0.7 * x[t - 1] + rng.normal()
    lv = pd.DataFrame({"AR": 100 + x}, index=_idx(2000))
    ret = lv.diff().dropna()
    row = S.stationarity(lv, ret)["rows"][0]
    assert row["adf_level_p"] < 0.01
    assert row["hurst"] < 0.45 and row["hurst_label"] == "mean_reverting"


def test_a_trending_series_has_a_high_hurst(rng):
    inc = np.zeros(3000)
    for t in range(1, 3000):
        inc[t] = 0.6 * inc[t - 1] + rng.normal()           # incréments persistants
    h = S.hurst_exponent(pd.Series(np.cumsum(inc)))
    assert h > 0.55


def test_memory_detects_autocorrelation_and_volatility_clustering(rng):
    n = 3000
    iid = pd.Series(rng.normal(size=n), index=_idx(n))
    out_iid = S.memory(iid, nlags=10)
    assert out_iid["returns_autocorrelated"] is False and out_iid["volatility_clustering"] is False

    ar = np.zeros(n)
    for t in range(1, n):
        ar[t] = 0.3 * ar[t - 1] + rng.normal()
    out_ar = S.memory(pd.Series(ar, index=_idx(n)), nlags=10)
    assert out_ar["returns_autocorrelated"] is True and out_ar["acf"][0] == pytest.approx(0.3, abs=0.06)
    assert abs(out_ar["pacf"][1]) < out_ar["band"] * 2          # AR(1) : la PACF s'éteint après le décalage 1

    vol = np.ones(n)
    eps = rng.normal(size=n)
    r = np.zeros(n)
    for t in range(1, n):
        vol[t] = math.sqrt(0.1 + 0.85 * r[t - 1] ** 2)           # ARCH(1) fort
        r[t] = vol[t] * eps[t]
    out_arch = S.memory(pd.Series(r, index=_idx(n)), nlags=10)
    assert out_arch["volatility_clustering"] is True and out_arch["arch_lm_p"] < 0.01


def test_memory_needs_enough_observations(rng):
    with pytest.raises(ValueError, match="minimum 30"):
        S.memory(pd.Series(rng.normal(size=10)))


# --------------------------------------------------------------------------- liens entre deux actifs


def test_cross_correlation_finds_the_planted_lead(rng):
    b = rng.normal(size=N)
    a = np.roll(b, 3) + 0.5 * rng.normal(size=N)              # a[t] suit b[t-3]
    out = S.cross_correlation(_rets(A=a, B=b), "A", "B", maxlag=8)
    assert out["best_lag"] == 3 and out["best_value"] > 0.7
    assert out["significant"][out["lags"].index(3)] is True
    assert abs(out["contemporaneous"]) < 0.15


def test_granger_is_one_directional_when_only_one_direction_exists(rng):
    n = 2000
    b = rng.normal(size=n)
    a = np.zeros(n)
    for t in range(1, n):
        a[t] = 0.6 * b[t - 1] + rng.normal(0, 0.5)
    out = S.granger(_rets(A=a, B=b), "A", "B", maxlag=3)
    assert out["b_to_a"]["predictive"] is True and out["b_to_a"]["best_lag"] == 1
    assert out["a_to_b"]["predictive"] is False


def test_cointegration_separates_a_shared_trend_from_two_independent_walks(rng):
    n = 1500
    trend = np.cumsum(rng.normal(0, 0.01, n))
    gap = np.zeros(n)
    for t in range(1, n):
        gap[t] = 0.9 * gap[t - 1] + rng.normal(0, 0.01)     # écart persistant mais stationnaire : demi-vie ≈ 6,6 périodes
    pa = pd.Series(np.exp(trend + gap), index=_idx(n))
    pb = pd.Series(np.exp(0.5 * trend), index=_idx(n))
    lv = pd.DataFrame({"A": pa, "B": pb})
    out = S.cointegration(lv, "A", "B")
    assert out["cointegrated"] is True and out["hedge_ratio"] == pytest.approx(2.0, abs=0.3)
    assert 3 < out["half_life_periods"] < 15

    w1 = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=_idx(n))
    w2 = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=_idx(n))
    assert S.cointegration(pd.DataFrame({"A": w1, "B": w2}), "A", "B")["cointegrated"] is False


def test_cointegration_refuses_non_positive_levels(rng):
    lv = pd.DataFrame({"A": rng.normal(size=200).cumsum(), "B": rng.normal(size=200).cumsum() + 500}, index=_idx(200))
    with pytest.raises(ValueError, match="≤ 0"):
        S.cointegration(lv, "A", "B")


def test_pair_studies_refuse_the_same_asset_twice(rng):
    df = _rets(A=rng.normal(size=200), B=rng.normal(size=200))
    for fn in (S.cross_correlation, S.granger, S.tail_dependence):
        with pytest.raises(ValueError, match="différents"):
            fn(df, "A", "A")


# --------------------------------------------------------------------------- structure


def test_pca_finds_a_common_market_factor(rng):
    f = rng.normal(size=N)
    df = _rets(**{f"S{i}": 0.8 * f + 0.6 * rng.normal(size=N) for i in range(6)})
    out = S.pca(df, 3)
    assert out["first_factor_share"] > 0.55
    first = out["components"][0]
    assert all(w["loading"] > 0 for w in first["loadings"])
    assert out["cumulative"][-1] <= 1.0 + 1e-9 and out["n_for_80pct"] >= 1
    independent = S.pca(_rets(**{f"S{i}": rng.normal(size=N) for i in range(6)}), 3)
    assert independent["first_factor_share"] < 0.25


def test_pca_needs_two_assets(rng):
    with pytest.raises(ValueError, match="au moins deux"):
        S.pca(_rets(A=rng.normal(size=100)))


def test_beta_and_alpha_are_recovered(rng):
    x = rng.normal(0, 0.01, N)
    y = 0.0004 + 1.5 * x + rng.normal(0, 0.004, N)
    out = S.beta_alpha(_rets(Y=y, X=x), "Y", "X", window=60, periods_per_year=252)
    assert out["beta"] == pytest.approx(1.5, abs=0.05)
    assert out["alpha_per_period"] == pytest.approx(0.0004, abs=0.0004)
    assert out["alpha_annualized"] == pytest.approx(out["alpha_per_period"] * 252)
    assert out["r2"] > 0.8 and out["beta_p"] < 1e-6
    assert 1.0 < out["rolling_beta_min"] < out["rolling_beta_max"] < 2.0


def test_tail_dependence_sees_joint_crashes_that_correlation_hides(rng):
    n = 20000
    crash = rng.random(n) < 0.03                                # 3 % de jours de krach commun
    a = rng.normal(0, 0.01, n) - 0.08 * crash
    b = rng.normal(0, 0.01, n) - 0.08 * crash
    out = S.tail_dependence(_rets(A=a, B=b), "A", "B", q=0.05)
    assert out["lower_ratio"] > 4 and out["upper_ratio"] < 2
    indep = S.tail_dependence(_rets(A=rng.normal(size=n), B=rng.normal(size=n)), "A", "B", q=0.05)
    assert indep["lower_ratio"] == pytest.approx(1.0, abs=0.35)
    with pytest.raises(ValueError, match="Quantile"):
        S.tail_dependence(_rets(A=a, B=b), "A", "B", q=0.5)


# --------------------------------------------------------------------------- saisonnalité


def test_seasonality_finds_a_planted_monday_effect_after_correction(rng):
    n = 4000
    idx = _idx(n)
    r = pd.Series(rng.normal(0, 0.01, n), index=idx)
    r[idx.weekday == 0] += 0.004                                # +0,4 % chaque lundi
    out = S.seasonality(r, "D")
    rows = {row["key"]: row for row in out["rows"]}
    assert rows["wd:Lun"]["significant"] is True
    strongest = max(out["rows"], key=lambda r: abs(r["excess"]))
    assert strongest["key"] == "wd:Lun" and rows["wd:Lun"]["p_adj"] < 1e-6
    # les autres jours « baissent » seulement par contraste avec le lundi : bien plus faibles que l'effet planté
    assert all(abs(r["excess"]) < 0.5 * abs(rows["wd:Lun"]["excess"]) for r in out["rows"] if r["key"] != "wd:Lun")
    assert out["omnibus_p"]["weekday"] < 1e-6 and out["omnibus_p"]["month"] > 0.01
    assert out["n_tests"] == len(out["rows"]) and out["n_tests"] >= 17


def test_seasonality_of_pure_noise_has_no_significant_group(rng):
    r = pd.Series(rng.normal(0, 0.01, 4000), index=_idx(4000))
    out = S.seasonality(r, "D")
    assert not any(row["significant"] for row in out["rows"])


def test_monthly_seasonality_has_no_weekday_rows(rng):
    r = pd.Series(rng.normal(0, 0.03, 240), index=pd.date_range("2005-01-31", periods=240, freq="ME"))
    out = S.seasonality(r, "M")
    assert all(row["kind"] == "mo" for row in out["rows"])


def test_outputs_never_contain_nan_or_numpy_types(rng):
    df = _rets(A=rng.normal(size=300), B=rng.normal(size=300))
    for out in (S.correlation(df), S.describe(df, np.exp(df.cumsum()), 252), S.seasonality(df["A"], "D")):
        json.dumps(out, allow_nan=False)
