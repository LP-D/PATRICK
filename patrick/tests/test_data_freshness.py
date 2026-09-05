"""TDD (Phase 5 -- dashboard de fraîcheur des données) : le calcul de
fraîcheur/retard par ticker/série AVANT toute implémentation.

`patrick.data.freshness` ne doit lire QUE le data lake local
(`data/store.py` / `_index.json`) -- jamais d'appel réseau yfinance/FRED
depuis ce module. Le seuil d'alerte dépend de la périodicité de publication
propre à chaque source :
  - yfinance (marchés, quotidien) : >2 jours ouvrés de retard = alerte.
  - FRED : la fréquence est propre à chaque série (quotidienne pour les
    taux, hebdomadaire pour NFCI/STLFSI4, mensuelle pour CPI/UNRATE/...,
    trimestrielle pour GDP) -- un seuil unique appliquerait une fausse
    alerte permanente aux 2/3 de l'univers macro (mensuel/trimestriel).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from patrick.data import freshness
from patrick.data.store import DataStore


# ---------------------------------------------------------------------------
# Table de correspondance périodicité FRED (préfixe/pattern -> fréquence)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("series_id, expected", [
    # Quotidiennes -- taux/spreads/vol publiés chaque jour ouvré.
    ("DGS10", "daily"),
    ("DGS1", "daily"),
    ("DTB3", "daily"),
    ("T10Y2Y", "daily"),
    ("T10YIE", "daily"),
    ("DFF", "daily"),
    ("EFFR", "daily"),
    ("SOFR", "daily"),
    ("VIXCLS", "daily"),
    ("BAMLH0A0HYM2", "daily"),
    # Mensuelles.
    ("CPIAUCSL", "monthly"),
    ("CPILFESL", "monthly"),
    ("PCE", "monthly"),
    ("UNRATE", "monthly"),
    ("PAYEMS", "monthly"),
    ("RSAFS", "monthly"),
    ("INDPRO", "monthly"),
    ("FEDFUNDS", "monthly"),
    ("UMCSENT", "monthly"),
    # Trimestrielle.
    ("GDP", "quarterly"),
    # Hebdomadaires.
    ("NFCI", "weekly"),
    ("STLFSI4", "weekly"),
])
def test_fred_periodicity_matches_documented_table(series_id, expected):
    assert freshness.fred_periodicity(series_id) == expected


def test_fred_periodicity_unknown_series_falls_back_to_a_conservative_default():
    # Une série FRED absente de la table (pas de préfixe reconnu) ne doit
    # jamais tomber sur le seuil "quotidien" (2 jours ouvrés) -- ce serait
    # une fausse alerte systématique si elle est en réalité mensuelle/
    # trimestrielle. Le fallback documenté est "monthly".
    assert freshness.fred_periodicity("SOME_UNKNOWN_SERIES_ID") == "monthly"


# ---------------------------------------------------------------------------
# Calcul du retard en jours ouvrés
# ---------------------------------------------------------------------------

def test_business_days_late_one_business_day():
    # Mercredi 31/01/2024, dernière donnée mardi 30/01/2024 -> 1 jour ouvré.
    assert freshness.business_days_late(date(2024, 1, 30), as_of=date(2024, 1, 31)) == 1


def test_business_days_late_five_business_days():
    # Mercredi 24/01/2024 -> mercredi 31/01/2024 = 5 jours ouvrés (24,25,26,29,30).
    assert freshness.business_days_late(date(2024, 1, 24), as_of=date(2024, 1, 31)) == 5


def test_business_days_late_is_zero_when_data_is_from_today_or_future():
    assert freshness.business_days_late(date(2024, 1, 31), as_of=date(2024, 1, 31)) == 0
    assert freshness.business_days_late(date(2024, 2, 5), as_of=date(2024, 1, 31)) == 0


def test_business_days_late_ignores_weekends():
    # Vendredi -> lundi suivant = 1 jour ouvré (le week-end ne compte pas).
    assert freshness.business_days_late(date(2024, 1, 26), as_of=date(2024, 1, 29)) == 1


# ---------------------------------------------------------------------------
# États : ok / warning selon la périodicité -- exemples donnés par la tâche.
# ---------------------------------------------------------------------------

def test_daily_series_one_business_day_late_is_ok():
    result = freshness.classify_freshness("daily", business_days_late=1)
    assert result == "ok"


def test_daily_series_five_business_days_late_is_warning():
    result = freshness.classify_freshness("daily", business_days_late=5)
    assert result == "warning"


def test_monthly_series_twenty_days_late_is_ok():
    # ~20 jours (calendaires) de retard reste dans la fenêtre normale de
    # publication d'une série mensuelle (cycle ~30 jours) -- ne doit PAS
    # déclencher d'alerte.
    late_bdays = freshness.business_days_late(date(2024, 1, 11), as_of=date(2024, 1, 31))
    result = freshness.classify_freshness("monthly", business_days_late=late_bdays)
    assert result == "ok"


def test_monthly_series_far_past_its_publication_window_is_warning():
    # ~70 jours calendaires (plus de deux cycles mensuels) : la série n'a
    # clairement pas été republiée dans sa fenêtre normale.
    late_bdays = freshness.business_days_late(date(2023, 11, 22), as_of=date(2024, 1, 31))
    result = freshness.classify_freshness("monthly", business_days_late=late_bdays)
    assert result == "warning"


def test_quarterly_series_within_one_quarter_is_ok():
    late_bdays = freshness.business_days_late(date(2024, 8, 1), as_of=date(2024, 10, 15))
    result = freshness.classify_freshness("quarterly", business_days_late=late_bdays)
    assert result == "ok"


def test_quarterly_series_two_quarters_late_is_warning():
    late_bdays = freshness.business_days_late(date(2024, 1, 1), as_of=date(2024, 10, 15))
    result = freshness.classify_freshness("quarterly", business_days_late=late_bdays)
    assert result == "warning"


def test_weekly_series_a_few_days_late_is_ok():
    late_bdays = freshness.business_days_late(date(2024, 1, 25), as_of=date(2024, 1, 31))
    result = freshness.classify_freshness("weekly", business_days_late=late_bdays)
    assert result == "ok"


def test_weekly_series_a_month_late_is_warning():
    late_bdays = freshness.business_days_late(date(2023, 12, 20), as_of=date(2024, 1, 31))
    result = freshness.classify_freshness("weekly", business_days_late=late_bdays)
    assert result == "warning"


# ---------------------------------------------------------------------------
# compute_freshness() : intégration avec le DataStore réel (lecture locale
# uniquement, jamais de réseau).
# ---------------------------------------------------------------------------

def _df_ending(end: str, n: int = 400) -> pd.DataFrame:
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(0)
    return pd.DataFrame({"x": rng.normal(0, 1, n)}, index=idx)


def test_compute_freshness_never_cached_ticker_is_disabled_not_an_error(tmp_path):
    store = DataStore(root=str(tmp_path))
    result = freshness.compute_freshness("GC=F", "Gold_Futures", "yfinance", store=store,
                                          as_of=date(2024, 1, 31))
    assert result.cached is False
    assert result.state == "disabled"
    assert result.date_max is None
    assert result.business_days_late is None


def test_compute_freshness_cached_yfinance_ticker_fresh_is_ok(tmp_path):
    store = DataStore(root=str(tmp_path))
    store.save("raw_^GSPC", _df_ending("2024-01-30"))
    result = freshness.compute_freshness("^GSPC", "SP500_Price", "yfinance", store=store,
                                          as_of=date(2024, 1, 31))
    assert result.cached is True
    assert result.periodicity == "daily"
    assert result.business_days_late == 1
    assert result.state == "ok"


def test_compute_freshness_cached_yfinance_ticker_stale_is_warning(tmp_path):
    store = DataStore(root=str(tmp_path))
    store.save("raw_^GSPC", _df_ending("2024-01-19"))  # ~8 jours ouvres avant le 31/01
    result = freshness.compute_freshness("^GSPC", "SP500_Price", "yfinance", store=store,
                                          as_of=date(2024, 1, 31))
    assert result.cached is True
    assert result.business_days_late > 2
    assert result.state == "warning"


def test_compute_freshness_fred_series_uses_its_own_periodicity(tmp_path):
    store = DataStore(root=str(tmp_path))
    # CPI : mensuelle -- dernier point il y a ~20 jours calendaires, doit
    # rester "ok" alors que la même date ferait "warning" pour une série
    # quotidienne.
    store.save("raw_CPIAUCSL", _df_ending("2024-01-11"))
    result = freshness.compute_freshness("CPIAUCSL", "CPI", "fred", store=store,
                                          as_of=date(2024, 1, 31))
    assert result.periodicity == "monthly"
    assert result.state == "ok"


def test_compute_freshness_uses_the_most_recent_snapshot_date_max(tmp_path):
    # Deux ingestions successives (contenus différents -> deux snapshots) :
    # la fraîcheur doit refléter la donnée la PLUS récente jamais vue, pas
    # le premier snapshot créé.
    store = DataStore(root=str(tmp_path))
    store.save("raw_^VIX", _df_ending("2024-01-02", n=50))
    store.save("raw_^VIX", _df_ending("2024-01-30", n=51))
    result = freshness.compute_freshness("^VIX", "VIX_Price", "yfinance", store=store,
                                          as_of=date(2024, 1, 31))
    assert result.business_days_late == 1


def test_compute_freshness_never_makes_a_network_call(tmp_path, monkeypatch):
    """Garde-fou explicite : si `yfinance_source`/`fred_source` sont
    importés/appelés par erreur depuis `compute_freshness`, ce test doit
    l'attraper en cassant l'appel réseau."""
    import patrick.data.sources.yfinance_source as yf_source
    import patrick.data.sources.fred_source as fred_src

    def _boom(*a, **k):
        raise AssertionError("compute_freshness ne doit jamais appeler le réseau")

    monkeypatch.setattr(yf_source, "download_target", _boom, raising=False)
    monkeypatch.setattr(fred_src, "download_series", _boom, raising=False)

    store = DataStore(root=str(tmp_path))
    store.save("raw_^GSPC", _df_ending("2024-01-30"))
    freshness.compute_freshness("^GSPC", "SP500_Price", "yfinance", store=store,
                                 as_of=date(2024, 1, 31))
    freshness.compute_freshness("GC=F", "Gold_Futures", "yfinance", store=store,
                                 as_of=date(2024, 1, 31))


# ---------------------------------------------------------------------------
# freshness_overview() : vue groupée (DEFAULT_TARGET_GROUPS) pour la page web.
# ---------------------------------------------------------------------------

def test_freshness_overview_covers_every_group_and_every_symbol(tmp_path):
    from patrick.config import defaults as D

    store = DataStore(root=str(tmp_path))
    overview = freshness.freshness_overview(store=store, as_of=date(2024, 1, 31))

    assert {g["group"] for g in overview} == set(D.DEFAULT_TARGET_GROUPS.keys())
    total_symbols = sum(len(v) for v in D.DEFAULT_TARGET_GROUPS.values())
    total_results = sum(len(g["results"]) for g in overview)
    assert total_results == total_symbols


def test_freshness_overview_marks_fred_group_results_as_fred_source(tmp_path):
    from patrick.config import defaults as D

    store = DataStore(root=str(tmp_path))
    overview = freshness.freshness_overview(store=store, as_of=date(2024, 1, 31))
    fred_group = next(g for g in overview if g["group"] == D.FRED_TARGET_GROUP)
    assert all(r.source == "fred" for r in fred_group["results"])
