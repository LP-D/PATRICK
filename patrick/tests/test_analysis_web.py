"""Pages et API d'analyse (`webapp/analysis_routes.py`) sur un run synthétique : le cadre s'affiche tout de suite, les sections arrivent par
l'API JSON, les identifiants inconnus répondent 404, les textes JS existent dans les deux langues."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import registry
from patrick.webapp import analysis_routes
from patrick.webapp.app import app
from patrick.webapp.i18n import STRINGS, js_strings

STATIC = Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "static"


@pytest.fixture
def client(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    conn.close()
    yield TestClient(app), info
    registry.clear_cache()


def test_analysis_page_renders_frame_with_every_section_mount(client):
    c, info = client
    r = c.get(f"/runs/{info['run_id']}/analyse")
    assert r.status_code == 200
    html = r.text
    assert 'id="ra-root"' in html and f'data-run-id="{info["run_id"]}"' in html
    for name in analysis_routes.ml_sections_for(is_cpcv=False):
        assert f'data-ra-mount="{name}"' in html, name
    assert 'data-ra-mount="paths"' not in html                    # pas de CPCV : pas de section chemins
    for script in ("analysis_kit.js", "analysis_loader.js", "run_analysis.js", "run_analysis_more.js"):
        assert f"/static/{script}" in html
    assert "/static/rl_analysis.js" not in html


def test_analysis_page_cpcv_has_paths_section(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, scheme="cpcv", live=0)
    conn.close()
    html = TestClient(app).get(f"/runs/{info['run_id']}/analyse").text
    assert 'data-ra-mount="paths"' in html
    registry.clear_cache()


def test_unknown_run_is_404_page_and_api(client):
    c, _ = client
    assert c.get("/runs/nope/analyse").status_code == 404
    assert c.get("/api/runs/nope/analysis/overview").status_code == 404


def test_api_serves_sections_and_rejects_unknown_section(client):
    c, info = client
    for section in analysis_routes.ML_SECTIONS:
        r = c.get(f"/api/runs/{info['run_id']}/analysis/{section}")
        assert r.status_code == 200, section
        assert isinstance(r.json(), dict)
    assert c.get(f"/api/runs/{info['run_id']}/analysis/nope").status_code == 404


def test_api_forwards_query_parameters(client):
    c, info = client
    r = c.get(f"/api/runs/{info['run_id']}/analysis/rolling?window=60")
    assert r.json()["window"] == 60
    r = c.get(f"/api/runs/{info['run_id']}/analysis/equity?cost_bps=25")
    assert r.json()["cost_bps"] == 25
    r = c.get(f"/api/runs/{info['run_id']}/analysis/timeline?start=2099-01-01")
    assert r.json()["available"] is False


def test_nav_entry_and_utility_pages_are_registered(client):
    c, _ = client
    assert c.get("/analyses").status_code == 200
    # la palette de commandes et la barre latérale proposent la page
    assert 'href="/analyses"' in c.get("/").text


def test_js_strings_ship_on_analysis_pages_only(client):
    _, info = client
    on_page = js_strings("fr", f"/runs/{info['run_id']}/analyse")
    assert on_page["ra_cls3"] == "Forte hausse"
    assert "ra_cls3" not in js_strings("fr", "/runs")
    assert js_strings("en", "/analyses")["ra_cls3"] == "Strong up"


def _used_keys(source: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'\bT\(\s*"((?:ra|ah|ac|ag|av|ad|am|aj|cn|dg)_[A-Za-z0-9_]+)"', source)}


def _dynamic_prefixes(source: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'\bT\(\s*"((?:ra|ah|ac|ag|av|ad|am|aj|cn|dg)_[A-Za-z0-9_]*_)"\s*\+', source)}


@pytest.mark.parametrize("script", ["analysis_loader.js", "run_analysis.js", "run_analysis_more.js", "analysis_kit.js", "rl_analysis.js", "analyses_hub.js", "analyses_compare.js", "guardrails.js", "variables.js", "drift_monitor.js", "model_registry.js", "journal.js", "carnet.js", "diagnostics.js"])
def test_every_text_key_used_by_scripts_exists_in_both_languages(script):
    source = (STATIC / script).read_text(encoding="utf-8")
    missing = [k for k in _used_keys(source) if k not in STRINGS and not k.endswith("_")]
    assert not missing, f"{script}: clés absentes {missing}"
    for prefix in _dynamic_prefixes(source):
        assert any(k.startswith(prefix) for k in STRINGS), f"{script}: aucune clé pour le préfixe {prefix}"


def test_dynamic_keys_cover_every_value_the_server_can_send():
    from patrick.analysis.sec_meta import _FAMILIES
    fams = {name for name, _ in _FAMILIES} | {"level_other"}
    assert {f for f in fams if f"ra_fam_{f}" not in STRINGS} == set()
    for k in ("vol_low", "vol_mid", "vol_high", "trend_up", "trend_down", "dd_normal", "dd_stress", "mom_up", "mom_down"):
        assert f"ra_rg_{k}" in STRINGS
    for k in range(1, 13):
        assert f"ra_mo_{k}" in STRINGS
    for k in range(7):
        assert f"ra_wd_{k}" in STRINGS
    for k in ("acc_vs_majority", "one_sided", "holdout_drop", "auc", "calibration", "folds", "ic", "equity", "dsr", "trials", "too_good"):
        assert f"ra_g_{k}" in STRINGS
    for name in analysis_routes.ML_SECTIONS:
        assert f"ra_s_{name}" in STRINGS and f"ra_h_{name}" in STRINGS
    for reason in ("no_predictions", "empty_window", "not_enough", "no_returns", "no_probabilities", "not_cpcv", "no_paths"):
        assert f"ra_reason_{reason}" in STRINGS


def test_guide_parameters_are_all_formatted_by_the_script(client):
    """Chaque champ `{x}` d'un texte de lecture guidée est fourni par le serveur sous ce nom."""
    c, info = client
    items = c.get(f"/api/runs/{info['run_id']}/analysis/guide").json()["items"]
    fields = lambda text: set(re.findall(r"\{(\w+)\}", text))
    for it in items:
        if it["key"] == "note":
            continue
        assert fields(STRINGS[f"ra_g_{it['key']}"]["fr"]) <= set(it["params"]), it["key"]


def test_overview_json_has_no_nan(client):
    c, info = client
    body = c.get(f"/api/runs/{info['run_id']}/analysis/overview").text
    assert "NaN" not in body and json.loads(body)["run"]["name"] == "TST_test"


def test_exports_predictions_and_equity_csv(client):
    c, info = client
    r = c.get(f"/api/runs/{info['run_id']}/export/predictions.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().split("\n")
    assert lines[0].startswith("date,split,fold,path,true_class")
    from patrick.analysis import frames
    from patrick.tracking import db as trackdb
    conn = trackdb.connect()
    n = len(frames.load_frame(conn, info["run_id"], with_levels=False).df)
    conn.close()
    assert len(lines) == n + 1
    first = dict(zip(lines[0].split(","), lines[1].split(","), strict=True))
    assert first["split"] == "test" and first["forward_return"] != "" and first["correct"] in ("0", "1")
    eq = c.get(f"/api/runs/{info['run_id']}/export/equity.csv?cost_bps=10")
    assert eq.status_code == 200 and eq.text.split("\n")[0].startswith("date,long_short_gross")
    assert c.get("/api/runs/nope/export/predictions.csv").status_code == 404


def test_standalone_report_embeds_every_section_and_no_script_breakout(client):
    c, info = client
    r = c.get(f"/runs/{info['run_id']}/analyse/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    html = r.text
    m = re.search(r'<script id="ra-embed" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert m
    data = json.loads(m.group(1).replace(r"<\/", "</"))
    assert {"overview", "timeline", "confusion", "equity", "guide"} <= set(data)
    assert "paths" not in data and data["overview"]["run"]["run_id"] == info["run_id"]
    assert "/static/" not in html.split("</head>")[1].replace("/static/analysis", "")        # rien à charger : styles et scripts sont inclus
    assert html.count("</script>") == html.count("<script")                                    # aucun « </script » dans les données ou le code
