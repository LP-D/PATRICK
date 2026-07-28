import numpy as np
import pandas as pd

from patrick.data.ingest import _apply_session_lag
from patrick.config.schema import ObjectiveConfig
from patrick.data.session_calendar import classify_asset_class, session_lag_days


def test_classify_asset_class_by_suffix():
    assert classify_asset_class("BTC-USD") == "crypto"
    assert classify_asset_class("EURUSD=X") == "fx"
    assert classify_asset_class("GC=F") == "futures"
    assert classify_asset_class("BNP.PA") == "equities_europe"
    assert classify_asset_class("7203.T") == "equities_asia_pacific"
    assert classify_asset_class("AAPL") == "equities_us"
    assert classify_asset_class("^GSPC") == "equities_us"
    assert classify_asset_class("^FCHI") == "equities_europe"
    assert classify_asset_class("^HSI") == "equities_asia_pacific"


def test_classify_unknown_symbol_falls_back_to_conservative_other():
    assert classify_asset_class("SOME_WEIRD_TICKER.XYZ") == "other"


def test_session_lag_between_later_and_earlier_closing_markets():
    # feature US (clôture ~20h UTC) utilisée pour une cible asiatique (clôture
    # ~8h UTC, déjà passée) -> la feature "du jour" n'était pas encore connue.
    assert session_lag_days("AAPL", "yfinance", "^HSI", "yfinance") == 1
    # l'inverse : cible US, feature asiatique déjà connue au moment de la
    # clôture US -> pas de décalage nécessaire.
    assert session_lag_days("^HSI", "yfinance", "AAPL", "yfinance") == 0
    # même classe d'actif -> pas de décalage.
    assert session_lag_days("MSFT", "yfinance", "AAPL", "yfinance") == 0


def test_session_lag_is_zero_for_non_yfinance_target():
    # la correction temporelle d'une cible FRED relève de la Phase 0.5 (vintages
    # de publication), pas de cette classification par session de marché.
    assert session_lag_days("AAPL", "yfinance", "CPIAUCSL", "fred") == 0


def test_apply_session_lag_shifts_later_closing_columns():
    idx = pd.bdate_range("2020-01-01", periods=10)
    yf_df = pd.DataFrame({"AAPL": np.arange(10, dtype=float),
                           "IDX_HSI": np.arange(100, 110, dtype=float)}, index=idx)
    objective = ObjectiveConfig(target_symbol="^HSI", target_source="yfinance")
    out = _apply_session_lag(yf_df, ["AAPL", "^HSI"], objective)

    # AAPL (clôture US, après HSI) doit être décalé d'une barre : out["AAPL"][1]
    # doit valoir la valeur originale à la position 0.
    assert out["AAPL"].iloc[1] == yf_df["AAPL"].iloc[0]
    assert np.isnan(out["AAPL"].iloc[0])
    # IDX_HSI (colonne nettoyée de "^HSI", même symbole que la cible) : même
    # classe d'actif que la cible -> pas de décalage, valeurs inchangées.
    pd.testing.assert_series_equal(out["IDX_HSI"], yf_df["IDX_HSI"])
