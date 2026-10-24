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


def test_the_analyses_page_is_now_a_view_of_the_history(client):
    c, info = client
    # l'ancienne adresse redirige (liens et marque-pages conservés) vers la vue « Analyses » de l'Historique
    moved = c.get("/analyses", follow_redirects=False)
    assert moved.status_code == 308 and moved.headers["location"] == "/runs?vue=analyses"
    page = c.get("/runs?vue=analyses")
    assert page.status_code == 200
    for anchor in ('id="carte"', 'id="algos"', 'id="rl"'):
        assert anchor in page.text, anchor
    assert 'src="/static/analyses_hub.js' in page.text and 'history-table' not in page.text   # ni liste ni script de la liste
    # la page porte les deux onglets de vue, « Analyses » actif, et les textes du navigateur des pages d'analyse
    assert re.search(r'class="kind-tab active"[^>]*>\s*Analyses', page.text) or 'href="/runs?vue=analyses" class="kind-tab active"' in page.text
    assert "ra_cls3" in page.text
    # la barre latérale n'a plus d'entrée « Analyses » : Historique reste allumé, sur la vue comme sur l'analyse d'un run
    for path in ("/runs?vue=analyses", f"/runs/{info['run_id']}/analyse"):
        html = c.get(path).text
        side = re.search(r'<nav class="sidebar-nav".*?</nav>', html, re.DOTALL).group(0)
        assert 'href="/analyses"' not in side
        assert re.search(r'<a href="/runs"[^>]*aria-current="page"', side), path
    from patrick.webapp import nav_registry
    runs_entry = next(e for e in nav_registry.NAV_ENTRIES if e.slug == "runs")
    assert nav_registry.is_active(runs_entry, "/analyses/comparer")          # la comparaison détaillée dépend aussi de l'Historique
    assert not any(e.slug == "analyses" for e in nav_registry.NAV_ENTRIES)


def test_each_finished_run_of_the_list_links_to_its_detailed_analysis(client):
    c, info = client
    html = c.get("/runs").text
    assert f'href="/runs/{info["run_id"]}/analyse"' in html
    assert 'href="/runs?vue=analyses"' in html      # l'autre vue de la page


def test_js_strings_ship_on_analysis_pages_only(client):
    _, info = client
    on_page = js_strings("fr", f"/runs/{info['run_id']}/analyse")
    assert on_page["ra_cls3"] == "Forte hausse"
    assert "ra_cls3" not in js_strings("fr", "/runs")
    assert js_strings("en", "/analyses")["ra_cls3"] == "Strong up"


def _used_keys(source: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'\bT\(\s*"((?:ra|ah|ac|ag|av|ad|am|aj|cn|dg|rk|dx|nt)_[A-Za-z0-9_]+)"', source)}


def _dynamic_prefixes(source: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'\bT\(\s*"((?:ra|ah|ac|ag|av|ad|am|aj|cn|dg|rk|dx|nt)_[A-Za-z0-9_]*_)"\s*\+', source)}


@pytest.mark.parametrize("script", ["analysis_loader.js", "run_analysis.js", "run_analysis_more.js", "analysis_kit.js", "rl_analysis.js", "analyses_hub.js", "analyses_compare.js", "guardrails.js", "variables.js", "drift_monitor.js", "model_registry.js", "journal.js", "carnet.js", "diagnostics.js", "risque.js", "donnees.js", "run_notify.js"])
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


def test_standalone_report_survives_a_hostile_run_name(client):
    from patrick.tracking import db as trackdb
    hostile = "x</script><script>alert(1)</script><!-- &amp;"
    conn = trackdb.connect()
    with conn:
        conn.execute("UPDATE run SET config_json = json_set(config_json, '$.name', ?) WHERE run_id = ?", (hostile, client[1]["run_id"]))
    conn.close()
    html = client[0].get(f"/runs/{client[1]['run_id']}/analyse/export").text
    assert "<script>alert(1)" not in html and html.count("</script>") == html.count("<script")
    m = re.search(r'<script id="ra-embed" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert "<!--" not in m.group(1) and json.loads(m.group(1))["overview"]["run"]["name"] == hostile


def test_heavy_overviews_are_cached_for_a_minute_per_database(client, monkeypatch):
    from patrick.analysis import guardrails
    from patrick.webapp import analysis_routes
    analysis_routes._cache.clear()
    calls = []
    real = guardrails.summary
    monkeypatch.setattr(guardrails, "summary", lambda conn: calls.append(1) or real(conn))
    c, _ = client
    first = c.get("/api/garde-fous/summary").json()
    assert c.get("/api/garde-fous/summary").json() == first and len(calls) == 1
    key = next(iter(analysis_routes._cache))
    analysis_routes._cache[key] = (analysis_routes._cache[key][0] - 61.0, analysis_routes._cache[key][1])        # entrée périmée
    c.get("/api/garde-fous/summary")
    assert len(calls) == 2
    analysis_routes._cache.clear()
