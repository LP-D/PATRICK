"""Les séries macro (FRED) ne sont plus des cibles (2026-10-31) : elles restent des variables d'entraînement et la page Macro.

Raison : sur 341 runs à cible FRED, l'audit anti-fuite ne contrôlait pas les colonnes FRED dérivées du même taux (T10Y3M, T10Y2Y, T10YIE...),
et le F1 moyen de l'application était gonflé par des scores impossibles (DGS10 à 1 jour : AUC 0,95 ; SP500 : 1,00)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.tracking import db
from patrick.validation import suspicion
from patrick.webapp import forms, run_manager
from patrick.webapp.app import app

FRED_SYMBOLS = [sym for sym, _ in D.DEFAULT_TARGET_GROUPS[D.FRED_TARGET_GROUP]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    return TestClient(app)


def _form(**overrides) -> FormData:
    base = {"horizons": ["1"], "regimes": "GLOBAL", "families": ["technical"], "n_features_grid": "5",
            "sampler_candidates": ["SMOTE"], "algos": ["RandomForest"]}
    base.update(overrides)
    items = []
    for key, value in base.items():
        items.extend((key, x) for x in value) if isinstance(value, list) else items.append((key, value))
    return FormData(items)


# ---------------------------------------------------------------- le choix de cible

def test_the_target_picker_no_longer_offers_macro_series_but_the_catalogue_keeps_them():
    assert D.FRED_TARGET_GROUP not in forms.TARGET_GROUPS
    assert D.FRED_TARGET_GROUP in forms.CATALOGUE_GROUPS                    # exploration et page Macro
    offered = {sym for items in forms.TARGET_GROUPS.values() for sym, *_ in items}
    assert not offered & set(FRED_SYMBOLS)
    assert "^GSPC" in offered and "GC=F" in offered


@pytest.mark.parametrize("path", ["/ml", "/dl", "/rl"])
def test_launch_pages_do_not_list_any_macro_series(client, path):
    html = client.get(path).text
    for symbol in ("DGS10", "NFCI", "CPIAUCSL", "T10Y3M"):
        assert f'value="{symbol}"' not in html
    assert 'optgroup label="Macro (FRED)"' not in html and 'optgroup label="Macro' not in html


def test_a_macro_series_is_refused_as_a_target_by_the_launch_form(client):
    _config, errors = forms.build_config_dict(_form(), target_symbol="DGS10", name="DGS10_1")
    assert any("variables" in e and "cible" in e for e in errors)


def test_run_pipeline_refuses_a_macro_target_before_any_download():
    config = RunConfig.model_validate({"objective": {"target_symbol": "DGS10", "target_source": "fred"}})
    with pytest.raises(ValueError, match="macro"):
        from patrick.config.targets import refuse_non_target

        refuse_non_target(config, resumed=False)
    from patrick.config.targets import refuse_non_target

    refuse_non_target(config, resumed=True)                                  # un run déjà commencé peut être repris
    refuse_non_target(RunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}}), resumed=False)


def test_start_run_refuses_a_macro_target(client):
    config = RunConfig.model_validate({"objective": {"target_symbol": "DGS10", "target_source": "fred"}})
    with pytest.raises(ValueError, match="macro"):
        run_manager.start_run(config)


# ---------------------------------------------------------------- l'historique : plus rien de crédible

def test_legacy_macro_runs_are_flagged_suspect_and_so_are_kept_out_of_the_averages(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    cfg = {"objective": {"target_symbol": "DGS10", "target_source": "fred"}}
    assert suspicion.alignment_reason("DGS10", cfg)
    assert "macro" in suspicion.alignment_reason("DGS10", cfg)
    assert suspicion.alignment_reason("^GSPC", {"objective": {"target_symbol": "^GSPC", "target_source": "yfinance"}}) is None

    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap", "h", 1, 1, "api")
    db.create_run(conn, "r_macro", "DGS10", 1, "snap", json.dumps({"name": "r", **cfg}), "c", "sha", 1)
    db.create_run(conn, "r_ok", "^GSPC", 1, "snap", json.dumps({"name": "r2", "objective": {"target_symbol": "^GSPC"}}), "c", "sha", 1)
    conn.commit()
    suspects = {r["run_id"]: bool(r["suspect"]) for r in db.list_all_runs(conn)}
    assert suspects == {"r_macro": True, "r_ok": False}
    assert db.alignment_reasons(conn, ["r_macro", "r_ok"]).keys() == {"r_macro"}
    conn.close()


# ---------------------------------------------------------------- ce qui reste

def test_macro_series_stay_in_the_feature_universe_unchanged():
    assert "US10Y_Rate" in D.DEFAULT_UNIVERSE_FRED_SERIES and D.DEFAULT_UNIVERSE_FRED_SERIES["US10Y_Rate"] == "DGS10"
    assert "NFCI" in D.DEFAULT_UNIVERSE_FRED_SERIES.values()


def test_the_macro_page_is_still_there_and_every_series_is_marked_training_only(client):
    response = client.get("/macro")
    assert response.status_code == 200
    from patrick.webapp.app import _macro_sections_view
    from patrick.webapp.i18n import translator

    sections = _macro_sections_view(translator("fr"))
    assets = [a for s in sections for a in s["assets"]]
    assert len(assets) > 100 and all(a["training_only"] for a in assets)


def test_exploration_still_offers_macro_series(client):
    response = client.get("/api/exploration/catalog")
    assert response.status_code == 200
    symbols = {item["symbol"] for g in response.json()["groups"] for item in g["items"]}
    assert {"DGS10", "NFCI"} <= symbols


def test_predictions_and_portfolio_no_longer_list_macro_rows(client):
    from patrick.webapp.app import _directional_prediction_groups

    conn = db.connect()
    groups = _directional_prediction_groups(conn)
    conn.close()
    assert D.FRED_TARGET_GROUP not in groups
    assert client.get("/predictions").status_code == 200
    assert client.get("/portfolio").status_code == 200
