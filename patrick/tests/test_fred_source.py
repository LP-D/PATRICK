"""FRED est passé par deux chemins : l'API officielle (authentifiée par clé,
utilisée si FRED_API_KEY est défini) ou le scrape CSV public de
pandas_datareader (repli sans clé). Constaté en conditions réelles : le repli
CSV peut se mettre à échouer systématiquement (blocage/format côté
fred.stlouisfed.org) sans lever d'exception qui remonte — `download_series`
l'avale et retourne None, une série à la fois. Ces tests vérifient que les deux
chemins produisent une Series exploitable et qu'un échec reste local.
"""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.data.sources import fred_source


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_download_series_uses_api_when_key_present(monkeypatch):
    monkeypatch.setenv(fred_source.FRED_API_KEY_ENV, "fake-key")

    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _FakeResponse({
            "observations": [
                {"date": "2020-01-01", "value": "1.5"},
                {"date": "2020-01-02", "value": "."},  # valeur manquante FRED
                {"date": "2020-01-03", "value": "1.7"},
            ]
        })

    monkeypatch.setattr(fred_source.requests, "get", fake_get)

    s = fred_source.download_series("T10Y2Y", "T10Y2Y", "2020-01-01")

    assert captured["params"]["api_key"] == "fake-key"
    assert s.name == "T10Y2Y"
    assert len(s) == 2  # la valeur "." a bien été exclue
    assert s.iloc[0] == pytest.approx(1.5)


def test_download_series_falls_back_to_pandas_datareader_without_key(monkeypatch):
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)

    def fake_data_reader(series_id, source, start):
        assert source == "fred"
        return pd.Series([1.0, 2.0], index=pd.bdate_range("2020-01-01", periods=2))

    monkeypatch.setattr(fred_source.web, "DataReader", fake_data_reader)

    s = fred_source.download_series("EFFR", "EFFR", "2020-01-01")

    assert s.name == "EFFR"
    assert len(s) == 2


def test_download_series_returns_none_on_failure_without_raising(monkeypatch):
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)

    def broken_data_reader(*args, **kwargs):
        raise RuntimeError("simulated FRED outage")

    monkeypatch.setattr(fred_source.web, "DataReader", broken_data_reader)

    assert fred_source.download_series("EFFR", "EFFR", "2020-01-01") is None


def test_download_series_with_realtime_date_requests_alfred_vintage(monkeypatch):
    """Phase 0.5 : `realtime_date` doit se traduire en realtime_start/realtime_end
    dans la requête FRED — c'est ce qui bascule l'API sur le vintage ALFRED
    (valeur telle que connue à cette date) plutôt que la révision actuelle."""
    monkeypatch.setenv(fred_source.FRED_API_KEY_ENV, "fake-key")
    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _FakeResponse({"observations": [{"date": "2020-01-01", "value": "1.5"}]})

    monkeypatch.setattr(fred_source.requests, "get", fake_get)

    fred_source.download_series("CPI", "CPIAUCSL", "2020-01-01", realtime_date="2020-02-15")

    assert captured["params"]["realtime_start"] == "2020-02-15"
    assert captured["params"]["realtime_end"] == "2020-02-15"


def test_download_series_without_realtime_date_omits_vintage_params(monkeypatch):
    """Sans `realtime_date`, comportement inchangé (revient à "aujourd'hui" côté
    FRED, celui déjà utilisé avant la Phase 0.5) — pas de régression."""
    monkeypatch.setenv(fred_source.FRED_API_KEY_ENV, "fake-key")
    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _FakeResponse({"observations": [{"date": "2020-01-01", "value": "1.5"}]})

    monkeypatch.setattr(fred_source.requests, "get", fake_get)

    fred_source.download_series("CPI", "CPIAUCSL", "2020-01-01")

    assert "realtime_start" not in captured["params"]
    assert "realtime_end" not in captured["params"]


def test_download_fred_universe_warns_when_falling_back_to_scrape(monkeypatch, capsys):
    """Exigence explicite de la Phase 0.5 : le repli scrape (sans FRED_API_KEY)
    ne peut pas faire de vintage -> doit prévenir que les features macro sont
    potentiellement en avance sur l'information réellement disponible."""
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)

    def fake_data_reader(series_id, source, start):
        return pd.Series([1.0, 2.0], index=pd.bdate_range("2020-01-01", periods=2))

    monkeypatch.setattr(fred_source.web, "DataReader", fake_data_reader)

    fred_source.download_fred_universe({"EFFR": "EFFR"}, "2020-01-01")

    out = capsys.readouterr().out
    assert "FRED_API_KEY" in out and "vintage" in out.lower()


def test_download_fred_universe_does_not_warn_when_api_key_present(monkeypatch, capsys):
    monkeypatch.setenv(fred_source.FRED_API_KEY_ENV, "fake-key")

    def fake_get(url, params, timeout):
        return _FakeResponse({"observations": [{"date": "2020-01-01", "value": "1.5"}]})

    monkeypatch.setattr(fred_source.requests, "get", fake_get)

    fred_source.download_fred_universe({"EFFR": "EFFR"}, "2020-01-01")

    out = capsys.readouterr().out
    assert "FRED_API_KEY non défini" not in out
