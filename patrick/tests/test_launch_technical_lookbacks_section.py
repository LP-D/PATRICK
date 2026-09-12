"""Phase 3 (feature/hyperparams-lookbacks) -- verifie que la nouvelle
section "Lookbacks technical" est bien rendue sur `/launch` (index.html),
avec un champ par fonction (returns/zscore/ma_ratio/rolling_vol/ohlc_vol)
pre-rempli avec les lookbacks par defaut (identiques aux anciens defauts de
fonction codes en dur dans `features/technical.py`). Meme style que
`test_launch_optuna_bounds_section.py` : rend le vrai gabarit Jinja via
FastAPI TestClient, base vide."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.tracking import db
from patrick.webapp.app import app


def test_launch_page_renders_technical_lookbacks_section(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    assert 'name="tl__returns_windows"' in resp.text
    assert 'name="tl__zscore_windows"' in resp.text
    assert 'name="tl__ma_ratio_windows"' in resp.text
    assert 'name="tl__rolling_vol_windows"' in resp.text
    assert 'name="tl__ohlc_vol_windows"' in resp.text


def test_launch_page_prefills_technical_lookbacks_with_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    expected = ",".join(str(w) for w in D.DEFAULT_RETURNS_WINDOWS)
    assert f'name="tl__returns_windows" value="{expected}"' in resp.text
    expected_ohlc = ",".join(str(w) for w in D.DEFAULT_OHLC_VOL_WINDOWS)
    assert f'name="tl__ohlc_vol_windows" value="{expected_ohlc}"' in resp.text
