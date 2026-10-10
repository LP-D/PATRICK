"""Classes d'actifs : chaque groupe de cibles a une page, chaque cible de l'univers est visible quelque part, et le module Equity
remplace l'ancienne page « Actions individuelles »."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from patrick.config import asset_classes
from patrick.config import defaults as D
from patrick.config import universe_extension as UX
from patrick.tracking import class_overview
from patrick.tracking import db as trackdb
from patrick.webapp import forms, nav_registry
from patrick.webapp.app import app

CLASS_PAGES = [c for c in asset_classes.ASSET_CLASSES if c.key != "macro"]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    import numpy as np
    import pandas as pd

    from patrick.data.sources import fundamentals_source
    from patrick.validation import equity_sufficiency
    monkeypatch.setattr(equity_sufficiency.yfinance_source, "download_one",
                        lambda symbol, start: pd.Series(np.arange(100, dtype=float)))
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals",
                        lambda symbol: pd.DataFrame(columns=["fiscalDateEnding", "metric", "value"]))


def test_every_target_group_belongs_to_exactly_one_asset_class():
    for group in forms.TARGET_GROUPS:
        assert asset_classes.class_of_group(group), f"groupe sans classe d'actifs : {group!r}"
    owners = [g for c in asset_classes.ASSET_CLASSES for g in c.groups]
    assert len(owners) == len(set(owners)), "un groupe appartient à deux classes"


def test_every_class_with_a_page_is_in_the_navigation():
    nav_urls = {e.url for e in nav_registry.NAV_ENTRIES}
    for cls in asset_classes.ASSET_CLASSES:
        assert cls.url in nav_urls, cls.key
    assert "/equity" in nav_urls and "/equities" not in nav_urls


def test_equity_replaces_the_individual_stocks_page():
    client = TestClient(app)
    redirect = client.get("/equities", follow_redirects=False)
    assert redirect.status_code == 308 and redirect.headers["location"] == "/equity"
    html = client.get("/equity").text
    assert "Equity" in html and "Actions suivies en détail" in html


@pytest.mark.parametrize("cls", CLASS_PAGES, ids=lambda c: c.key)
def test_every_class_page_lists_all_its_targets(cls):
    html = TestClient(app).get(cls.url).text
    for group in cls.groups:
        for symbol, _label in forms.TARGET_GROUPS.get(group, []):
            assert f'data-symbol="{symbol}"' in html, (cls.key, symbol)


def test_the_whole_selectable_universe_is_reachable_from_a_class_page():
    reachable = {sym for cls in asset_classes.ASSET_CLASSES for g in cls.groups for sym, _ in forms.TARGET_GROUPS.get(g, [])}
    assert reachable == {sym for items in forms.TARGET_GROUPS.values() for sym, _ in items}


def test_the_feature_pool_symbols_are_all_known_targets_or_declared_training_only():
    """Univers de données : tout ce qui alimente les modèles est visible ; seules les séries FRED d'entraînement ne sont pas
    des cibles (elles ont leur badge dans la page Macro)."""
    targets = set(forms.TARGET_SOURCE_BY_SYMBOL)
    hidden_yf = [t for t in D.DEFAULT_UNIVERSE_YF_TICKERS if t not in targets]
    assert hidden_yf == [], f"tickers du pool de features absents des pages : {hidden_yf}"
    hidden_ext = [t for t in UX.extended_candidate_yf_tickers() if t not in targets and t not in D.BAD_TICKERS]
    assert hidden_ext == [], f"candidats étendus absents des pages : {hidden_ext}"
    macro_page = {sid for _, series in D.macro_page_sections() for sid, _ in series}
    fred_ids = set(D.DEFAULT_UNIVERSE_FRED_SERIES.values()) | set(D.MACRO_ONLY_FRED_SERIES.values())
    assert fred_ids - macro_page == set(), f"séries FRED absentes de la page Macro : {fred_ids - macro_page}"


def _run(conn, run_id, target, status="done", f1=0.52, auc=0.55, started="2026-10-01 10:00:00"):
    trackdb.upsert_snapshot(conn, "s1", "h1", None, None, None)
    trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="s1", config_json="{}", config_hash="h",
                       git_sha="g", seed=1)
    with conn:
        conn.execute("UPDATE run SET status = ?, started_at = ? WHERE run_id = ?", (status, started, run_id))
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 5, "shap")
    trackdb.mark_best_trial(conn, tid, artifact_path=None)
    with conn:
        for metric, value in (("F1_dir", f1), ("AUC_ovr_4cls", auc)):
            conn.execute("INSERT INTO fold_metric VALUES (?, 0, 'test', ?, ?)", (tid, metric, value))
    return tid


def test_class_overview_separates_directional_and_alpha_and_never_credits_a_suspect_score(tmp_path):
    conn = trackdb.connect(str(tmp_path / "p.db"))
    _run(conn, "a", "BTC-USD", f1=0.51, auc=0.54)
    _run(conn, "b", "BTC-USD", f1=0.99, auc=0.60)                  # suspect : ignoré comme « meilleur »
    _run(conn, "c", "ETH-USD__alpha_BTC-USD", f1=0.53, auc=0.56)
    stats = class_overview.model_stats_by_asset(conn)
    assert stats["BTC-USD"]["directional"]["n_done"] == 2 and stats["BTC-USD"]["directional"]["best_f1"] == pytest.approx(0.51)
    assert stats["BTC-USD"]["suspects"] == 1
    assert stats["ETH-USD"]["alpha"]["n_done"] == 1 and stats["ETH-USD"]["directional"]["n_done"] == 0
    page = class_overview.class_page(conn, "crypto", forms.TARGET_GROUPS, 10)
    rows = {r["symbol"]: r for g in page["groups"] for r in g["rows"]}
    assert rows["BTC-USD"]["n_dir"] == 2 and rows["BTC-USD"]["f1"] == pytest.approx(0.51) and rows["BTC-USD"]["suspects"] == 1
    assert rows["ETH-USD"]["n_alpha"] == 1 and rows["ETH-USD"]["n_dir"] == 0
    assert page["kpi"]["n_alpha"] == 1 and page["kpi"]["n_suspect"] == 1


def test_class_page_shows_short_history_against_the_threshold():
    html = TestClient(app).get("/crypto?min_history_years=10").text
    assert "Historique court" in html
    assert 'data-short="1"' in html            # ETH-USD (2017) sous 10 ans
    assert TestClient(app).get("/crypto?min_history_years=1").status_code == 400


def test_the_launch_link_of_a_class_page_preselects_the_target():
    html = TestClient(app).get("/ml?target=ETH-USD").text
    assert '<option value="ETH-USD"' in html and 'data-first="' in html
    assert 'value="ETH-USD" data-first="2017-11-09" selected' in html
