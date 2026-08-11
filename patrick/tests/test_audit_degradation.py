"""Rapport de correction, C7 -- validation de `patrick audit degradation` sans
accès réseau (sandbox sans réseau sortant) : sources monkeypatchées au niveau
`yfinance.download`/`requests.get` (pas `ingest()` lui-même), pour que le VRAI
`ingest()`/`_attach_snapshot_context` tourne -- seul moyen de vérifier que
`snapshot.fred_source` est bien peuplé sur ce chemin, pas contourné par un
`ingest()` monkeypatché comme dans les autres tests de fumée du pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick import audit as audit_module
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore
from conftest import OLD_ENOUGH_START

N_DAYS = 700
START = OLD_ENOUGH_START  # relative, not absolute -- see tests/conftest.py


def _fake_yf_download(tickers, start=None, auto_adjust=True, progress=False):
    idx = pd.bdate_range(start or START, periods=N_DAYS)
    is_batch = isinstance(tickers, list)
    syms = tickers if is_batch else [tickers]
    rng = np.random.default_rng(abs(hash(tuple(syms))) % (2**32))
    cols = {}
    for field in ("Open", "High", "Low", "Close"):
        for s in syms:
            base = 100 + np.cumsum(rng.normal(0, 1, N_DAYS))
            cols[(field, s)] = base + rng.normal(0, 0.1, N_DAYS)
    df = pd.DataFrame(cols, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    if not is_batch:
        # yfinance renvoie des colonnes plates pour un unique ticker (`download_one`/
        # `download_ohlc` -- cf. patrick/data/sources/yfinance_source.py -- indexent
        # directement `["Close"]`/`df[cols]` sans niveau MultiIndex à retirer).
        flat = df.copy()
        flat.columns = [c[0] for c in df.columns]
        return flat
    return df


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_requests_get(url, params=None, timeout=30):
    idx = pd.bdate_range(params["observation_start"], periods=N_DAYS)
    rng = np.random.default_rng(abs(hash(params["series_id"])) % (2**32))
    values = 1.0 + np.cumsum(rng.normal(0, 0.01, N_DAYS))
    observations = [{"date": str(d.date()), "value": f"{v:.4f}"} for d, v in zip(idx, values)]
    return _FakeResp({"observations": observations})


@pytest.fixture(autouse=True)
def _mock_data_sources(monkeypatch):
    monkeypatch.setattr(yfinance_source.yf, "download", _fake_yf_download)
    monkeypatch.setattr(fred_source.requests, "get", _fake_requests_get)


_ONE_TARGET = [{
    "label": "indice_us_test", "target_symbol": "^GSPC", "target_source": "yfinance",
    "yf_tickers": ["^VIX"], "fred_series": {"NFCI": "NFCI"}, "start_date": START,
}]


def test_audit_degradation_fails_explicitly_without_fred_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        audit_module.run_degradation_audit(
            targets=_ONE_TARGET, output_dir=str(tmp_path / "audit"),
            db_path=str(tmp_path / "patrick.db"), store=DataStore(root=str(tmp_path / "store")))


@pytest.mark.slow  # pipeline réel x 4 configurations, cf. rapport de correction D1/C7
def test_audit_degradation_runs_all_four_configurations_and_exports(tmp_path, monkeypatch):
    monkeypatch.setenv(fred_source.FRED_API_KEY_ENV, "test-key-1234567890")
    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))

    result = audit_module.run_degradation_audit(
        targets=_ONE_TARGET, seed=42, output_dir=str(tmp_path / "audit"),
        db_path=db_path, store=store)

    rows = result["rows"]
    assert [r["configuration"] for r in rows] == list(audit_module.CONFIGURATIONS)
    assert all(r["target"] == "indice_us_test" for r in rows)

    # Rapport d'audit initial : `fred_source` trouvé `None` en test synthétique --
    # ici `ingest()` réel tourne (sources monkeypatchées en dessous, pas `ingest()`
    # lui-même), donc doit être peuplé ("api", puisque FRED_API_KEY est défini) sur
    # les 4 configurations, pas seulement certaines.
    assert all(r["fred_source"] == "api" for r in rows), rows

    for r in rows:
        for col in audit_module.METRIC_COLUMNS:
            assert r[col] is None or 0.0 <= r[col] <= 1.0 or col == "MCC_4cls", r
        assert r["n_evaluations"] > 0

    import os
    assert os.path.isfile(result["csv_path"])
    assert os.path.isfile(result["md_path"])

    with open(result["csv_path"]) as f:
        csv_content = f.read()
    assert "configuration" in csv_content
    for configuration in audit_module.CONFIGURATIONS:
        assert configuration in csv_content

    with open(result["md_path"]) as f:
        md_content = f.read()
    assert md_content.startswith("|")
    assert "fred_source" in md_content


def test_config_for_stacks_corrections_cumulatively():
    """Les 4 configurations doivent être CUMULATIVES (chacune ajoute une
    correction à la précédente), pas 4 combinaisons indépendantes -- sinon
    l'audit ne peut pas isoler la contribution marginale de chaque correction."""
    target = _ONE_TARGET[0]
    configs = {c: audit_module._config_for(target, c, seed=1, output_dir="x") for c in audit_module.CONFIGURATIONS}

    assert configs["baseline_avant"].validation.purge is False
    assert configs["baseline_avant"].validation.embargo_enabled is False
    assert configs["baseline_avant"].universe.vintage_realtime_date is None
    assert configs["baseline_avant"].objective.disable_session_lag is True

    assert configs["+purge"].validation.purge is True
    assert configs["+purge"].validation.embargo_enabled is True
    assert configs["+purge"].universe.vintage_realtime_date is None
    assert configs["+purge"].objective.disable_session_lag is True

    assert configs["+vintages"].validation.purge is True
    assert configs["+vintages"].universe.vintage_realtime_date is not None
    assert configs["+vintages"].objective.disable_session_lag is True

    assert configs["complet"].validation.purge is True
    assert configs["complet"].universe.vintage_realtime_date is not None
    assert configs["complet"].objective.disable_session_lag is False

    # Même seed/univers de tickers/séries FRED sur les 4 configs -- seules les
    # bascules de correction doivent varier (comparaison contrôlée).
    for c in audit_module.CONFIGURATIONS:
        assert configs[c].output.seed == 1
        assert configs[c].universe.yf_tickers == target["yf_tickers"]
        assert configs[c].universe.fred_series == target["fred_series"]
