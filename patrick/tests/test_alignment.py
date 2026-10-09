"""Garde anti-fuite temporelle (`data/alignment.py`).

Les trois cas réels qui ont produit des F1 de 0,95 à 1,00 : une cible FRED quotidienne publiée à J+1 (SP500 contre ^GSPC,
corrélation 1,000), un taux (DGS10 contre ^TNX, 0,97), et un horodatage fournisseur décalé (EURUSD=X contre DX-Y.NYB,
-0,40). Les données sont synthétiques : un marché qui fait une marche aléatoire, une cible qui en est l'écho.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import AlignmentSpec, ObjectiveConfig, UniverseConfig
from patrick.data import alignment, publication_lag
from patrick.validation import suspicion


def _walk(n, seed, vol=0.01):
    rng = np.random.default_rng(seed)
    return np.exp(np.cumsum(rng.normal(0, vol, n)))


def _market(n=1500, seed=0):
    idx = pd.bdate_range("2015-01-01", periods=n)
    return idx, pd.Series(100 * _walk(n, seed), index=idx)


def _frame_fred_target():
    """Le marché `IDX_GSPC` ; la cible FRED `SP500` = le même prix mais publiée à J+1 (F01)."""
    idx, price = _market()
    return pd.DataFrame({"SP500": price.shift(1), "IDX_GSPC": price, "OTHER": 50 * _walk(len(idx), 3)}, index=idx)


def _objective(symbol, source, **kw):
    return ObjectiveConfig(target_symbol=symbol, target_source=source, **kw)


def _label_corr(df, target_col, feature_col):
    """Corrélation entre le label (variation future de la cible) et la variation du jour de la feature."""
    label = df[target_col].shift(-1) - df[target_col]
    return label.corr(df[feature_col].diff())


def test_the_published_fred_target_is_an_echo_of_the_market_before_the_guard():
    df = _frame_fred_target()
    assert _label_corr(df, "SP500", "IDX_GSPC") > 0.99


def test_a_fred_target_delays_every_market_series_by_its_publication_delay():
    df = _frame_fred_target()
    spec = alignment.decide(df, _objective("SP500", "fred"), UniverseConfig(yf_tickers=["^GSPC", "OTHER"]), 15)
    assert spec.version == alignment.ALIGNMENT_VERSION
    assert spec.column_lags == {"IDX_GSPC": 1, "OTHER": 1}
    out = alignment.apply_spec(df, spec)
    assert abs(_label_corr(out, "SP500", "IDX_GSPC")) < 0.1
    assert out["SP500"].equals(df["SP500"])     # la cible n'est jamais touchée


def test_the_delay_follows_the_series_publication_calendar():
    daily = pd.bdate_range("2020-01-01", periods=300)
    assert publication_lag.publication_delay_bars("DGS10", daily) == 1
    assert publication_lag.publication_delay_bars("DCOILWTICO", daily) == 7          # EIA, hebdomadaire
    assert publication_lag.publication_delay_bars("NFCI", daily) == 5                # hebdo, +7 jours
    assert publication_lag.publication_delay_bars("CPIAUCSL", daily) == 14           # +20 jours calendaires
    assert publication_lag.publication_delay_bars("GDP", daily) == 21                # +30 jours


def test_the_reference_date_audit_mode_gets_no_publication_delay():
    idx, price = _market()
    df = pd.DataFrame({"SP500": price, "IDX_GSPC": price * 1.01 + _walk(len(idx), 4)}, index=idx)
    uni = UniverseConfig(yf_tickers=["^GSPC"], fred_point_in_time="reference_date")
    spec = alignment.decide(df, _objective("SP500", "fred"), uni, 15)
    assert not spec.column_lags


def test_a_provider_timestamp_shift_is_found_and_lagged_by_the_audit():
    """DX-Y.NYB daté J contient le mouvement d'EURUSD=X daté J+1 (cas réel, corrélation -0,40)."""
    idx, price = _market(seed=5)
    dxy = 10000 / price.shift(-1)          # DXY(J) = information de J+1 de la cible, en sens inverse
    noise = pd.Series(_walk(len(idx), 9), index=idx)
    df = pd.DataFrame({"EURUSD=X": price, "DX_Y.NYB": dxy, "NOISE": noise}, index=idx).dropna()
    obj = _objective("EURUSD=X", "yfinance")
    uni = UniverseConfig(yf_tickers=["DX-Y.NYB", "NOISE"])

    spec = alignment.decide(df, obj, uni, 15)

    assert spec.column_lags == {"DX_Y.NYB": 1}
    assert "NOISE" not in spec.column_lags
    assert "corrélation de rang" in spec.reasons["DX_Y.NYB"]
    assert abs(_label_corr(alignment.apply_spec(df, spec), "EURUSD=X", "DX_Y.NYB")) < 0.2


def test_a_leak_that_delays_cannot_fix_is_dropped_after_two_extra_bars(monkeypatch):
    idx, price = _market(seed=1)
    df = pd.DataFrame({"T": price, "STUBBORN": price * 2}, index=idx)
    monkeypatch.setattr(alignment, "leaking_columns",
                        lambda frame, target, cols, cutoff=None, threshold=0.3: {"STUBBORN": 0.9} if "STUBBORN" in cols else {})
    spec = alignment.decide(df, _objective("T", "yfinance"), UniverseConfig(yf_tickers=["STUBBORN"]), 15)
    assert spec.dropped == ["STUBBORN"] and "STUBBORN" not in spec.column_lags
    assert "retirée" in spec.reasons["STUBBORN"]
    assert "STUBBORN" not in alignment.apply_spec(df, spec).columns


def test_an_honest_market_is_left_alone():
    idx, price = _market(seed=2)
    other = pd.Series(_walk(len(idx), 8), index=idx)
    df = pd.DataFrame({"T": price, "A": other, "B": other * 2 + 1}, index=idx)
    spec = alignment.decide(df, _objective("T", "yfinance"), UniverseConfig(yf_tickers=["A", "B"]), 15)
    assert not spec.column_lags and not spec.dropped


def test_the_holdout_never_influences_the_audit():
    idx, price = _market(seed=4)
    other = pd.Series(_walk(len(idx), 6), index=idx)
    leak_in_holdout = other.copy()
    cut = idx[-300]
    # la fuite n'existe que dans les 300 dernières barres (≈ le holdout de 15 mois) : l'audit ne doit pas la voir
    leak_in_holdout.loc[cut:] = price.shift(-1).loc[cut:].values
    df = pd.DataFrame({"T": price, "H": leak_in_holdout}, index=idx).dropna()
    spec = alignment.decide(df, _objective("T", "yfinance"), UniverseConfig(yf_tickers=["H"]), 15)
    assert not spec.column_lags


def test_the_alpha_benchmark_and_the_target_keep_their_calendar():
    df = _frame_fred_target().rename(columns={"OTHER": "BENCH"})
    obj = ObjectiveConfig(target_symbol="^GSPC", target_source="yfinance", target_kind="alpha", benchmark="BENCH")
    spec = alignment.decide(df, obj, UniverseConfig(yf_tickers=["BENCH", "^GSPC"]), 15)
    assert "BENCH" not in spec.column_lags and "IDX_GSPC" not in spec.column_lags


def test_a_run_without_alignment_keeps_its_original_inputs():
    df = _frame_fred_target()
    assert alignment.apply_spec(df, AlignmentSpec()) is df
    assert alignment.apply_spec(df, None) is df


def test_the_spec_roundtrips_through_the_run_config():
    spec = AlignmentSpec(version=1, column_lags={"IDX_GSPC": 1}, dropped=["X"], reasons={"IDX_GSPC": "r"})
    obj = ObjectiveConfig(target_symbol="SP500", target_source="fred", alignment=spec)
    again = ObjectiveConfig.model_validate_json(obj.model_dump_json())
    assert again.alignment == spec
    legacy = ObjectiveConfig.model_validate({"target_symbol": "SP500", "target_source": "fred"})
    assert legacy.alignment.version == 0 and legacy.leak_guard is True


def test_describe_lists_one_data_quality_row_per_touched_column():
    spec = AlignmentSpec(version=1, column_lags={"A": 2}, dropped=["B"], reasons={"A": "x", "B": "y"})
    rows = alignment.describe(spec)
    assert [(r["series"], r["reason"]) for r in rows] == [("A", "alignement_temporel"), ("B", "alignement_temporel")]
    assert "retardée de 2" in rows[0]["detail"] and "retirée" in rows[1]["detail"]


@pytest.mark.parametrize("metrics, expected", [
    ({"F1_dir": 0.99}, True), ({"F1_dir": 0.80}, True), ({"F1_dir": 0.62, "AUC_ovr_4cls": 0.9}, True),
    ({"F1_dir": 0.62, "AUC_ovr_4cls": 0.60}, False), ({}, False), (None, False), ({"F1_dir": float("nan")}, False),
])
def test_suspicion_thresholds(metrics, expected):
    assert bool(suspicion.suspect_reason(metrics)) is expected
