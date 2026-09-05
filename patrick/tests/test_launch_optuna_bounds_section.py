"""Phase 1 (feature/hyperparams-ui) -- verifie que la nouvelle section
"Bornes Optuna" est bien rendue sur `/launch` (index.html), avec un champ par
hyperparametre/algo pre-rempli avec les valeurs par defaut. Meme style que
`test_synthesis_webapp.py::test_launch_page...` : rend le vrai gabarit Jinja
via FastAPI TestClient, base vide."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.tracking import db
from patrick.webapp.app import app


def test_launch_page_renders_optuna_bounds_section(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    # Un champ par borne (low/high) pour chaque hyperparametre de chaque
    # algo -- verifie ici sur un algo representatif de chaque famille.
    assert 'name="ob__XGBoost__n_estimators__low"' in resp.text
    assert 'name="ob__XGBoost__n_estimators__high"' in resp.text
    assert 'name="ob__CatBoost__depth__low"' in resp.text


def test_launch_page_prefills_optuna_bounds_with_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    lo, hi = D.DEFAULT_OPTUNA_BOUNDS["RandomForest"]["n_estimators"]
    assert f'name="ob__RandomForest__n_estimators__low" value="{lo}"' in resp.text
    assert f'name="ob__RandomForest__n_estimators__high" value="{hi}"' in resp.text
