"""Refonte du 2026-10-09 : vocabulaire, aide statistique (p-values), métriques par fold repliables, famille alpha /
directionnelle de l'historique."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jinja2 import DictLoader, Environment

from patrick.tracking import db as trackdb
from patrick.tracking import history as trackhistory
from patrick.webapp import stats_help
from patrick.webapp.app import app
from patrick.webapp.glossary import GLOSSARY
from patrick.webapp.glossary_extra import CATEGORIES, TERM_CATEGORY
from patrick.webapp.i18n import STRINGS


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    path = str(tmp_path / "p.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    conn = trackdb.connect(path)
    trackdb.upsert_snapshot(conn, "s1", "h1", None, None, None)
    ids = {}
    for run_id, target in (("XLI_1_h1_a", "XLI"), ("MC_1_h1_b", "MC.PA__alpha_^STOXX50E")):
        trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="s1", config_json='{"name": "' + run_id + '"}',
                           config_hash="h", git_sha="g", seed=1)
        with conn:
            conn.execute("UPDATE run SET status = 'done' WHERE run_id = ?", (run_id,))
        tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 5, "shap")
        trackdb.mark_best_trial(conn, tid, artifact_path=None)
        ids[run_id] = tid
        with conn:
            for fold in range(7):
                for metric, value in (("AUC_ovr_4cls", 0.55 + fold / 100), ("F1_dir", 0.5 + fold / 100), ("Acc_dir", 0.5)):
                    conn.execute("INSERT INTO fold_metric VALUES (?, ?, 'test', ?, ?)", (tid, fold, metric, value))
            conn.execute("INSERT INTO fold_metric VALUES (?, 0, 'holdout', 'F1_dir', 0.52)", (tid,))
            conn.execute("INSERT INTO fold_metric VALUES (?, 0, 'holdout', 'AUC_ovr_4cls', 0.51)", (tid,))
    conn.close()
    return ids


def test_every_term_has_a_category_a_translation_and_a_page_entry():
    cats = {key for key, _, _ in CATEGORIES}
    for term, entry in GLOSSARY.items():
        assert TERM_CATEGORY.get(term, "app") in cats, term
        assert entry["fr"].strip() and entry["en"].strip(), term


@pytest.mark.parametrize("lang, needle", [("fr", "AUC (aire sous la courbe ROC)"), ("en", "AUC (area under the ROC curve)")])
def test_the_vocabulary_page_lists_every_term_in_both_languages(lang, needle):
    client = TestClient(app)
    client.cookies.set("patrick_lang", lang)
    html = client.get("/vocabulary").text
    assert needle in html
    assert len(re.findall(r'class="vocab-term"', html)) == len(GLOSSARY)
    assert 'id="term-p_value"' in html and 'id="term-data_leak"' in html


def test_the_glossary_popover_links_to_the_vocabulary_page():
    assert 'id="glossary-popover-link"' in TestClient(app).get("/vocabulary").text


def test_the_vocabulary_is_in_the_navigation_and_the_command_palette():
    html = TestClient(app).get("/vocabulary").text
    assert 'href="/vocabulary"' in html and '"url": "/vocabulary"' in html


def _detail(**over):
    base = {"is_cpcv": False, "dm_result": {"p_value": 0.012, "baseline": "BASELINE_persistence", "sample": "holdout", "n_obs": 240},
            "target_fdr": {"adjusted_p_value": 0.08, "significant": True, "rank": 2}, "fdr_result": {"alpha": 0.10, "n_tested": 40},
            "holdout_diag": {"rho": 0.31, "p_value": 0.04, "n_trials": 30},
            "pbo": {"pbo": 0.31, "reliability": {"ok": True, "ci_low": 0.2, "ci_high": 0.45, "n_combinations": 70}},
            "cumulative_trials": 120, "trials": [1, 2, 3], "run": {"snapshot_id": "snap"},
            "config": {"validation": {"n_wf_folds": 5, "min_train_frac": 0.4, "holdout_months": 15, "embargo_enabled": True},
                       "objective": {"alignment": {"column_lags": {"IDX_GSPC": 1}, "dropped": []}}}}
    base.update(over)
    return base


def test_pvalue_items_read_the_values_of_the_run():
    items = {i["key"]: i for i in stats_help.pvalue_items(_detail())}
    assert items["dm"]["state"] == "ok" and items["dm"]["reading"] == "sh_dm_significant"
    assert items["bh"]["state"] == "ok" and items["bh"]["args"]["n"] == 40
    assert items["spearman"]["value"] == "0.310" and items["pbo"]["state"] == "ok"
    assert items["trials"]["value"] == "120"


def test_a_selection_fold_pvalue_is_flagged_biased_never_significant():
    items = {i["key"]: i for i in stats_help.pvalue_items(_detail(dm_result={"p_value": 0.001, "baseline": "B", "sample": "last_wf_fold"}))}
    assert items["dm"]["state"] == "warning" and items["dm"]["reading"] == "sh_dm_biased"


def test_missing_results_are_explained_not_hidden():
    items = {i["key"]: i for i in stats_help.pvalue_items(_detail(dm_result=None, target_fdr=None, holdout_diag={"n_trials": 1}, pbo={}))}
    assert {k: items[k]["state"] for k in ("dm", "bh", "spearman", "pbo")} == {"dm": "disabled", "bh": "disabled", "spearman": "disabled", "pbo": "disabled"}


def test_the_procedure_names_the_applied_steps():
    steps = {s["key"]: s["args"] for s in stats_help.procedure_steps(_detail())}
    assert steps["data"]["shifted"] == 1 and steps["scheme_wf"]["folds"] == 5 and steps["scheme_wf"]["train"] == "40"
    assert steps["holdout"]["months"] == 15 and steps["dm"]["baseline"] == "BASELINE_persistence"
    assert steps["bh"]["n"] == 40
    assert "scheme_cpcv" in {s["key"] for s in stats_help.procedure_steps(_detail(is_cpcv=True))}


def test_every_stats_help_key_is_translated():
    keys = {f"sh_title_{k}" for k in ("dm", "bh", "spearman", "pbo", "trials")} | {f"sh_what_{k}" for k in ("dm", "bh", "spearman", "pbo", "trials")}
    for detail in (_detail(), _detail(dm_result=None, target_fdr=None, pbo={}, holdout_diag={}), _detail(is_cpcv=True)):
        keys |= {i["reading"] for i in stats_help.pvalue_items(detail) if i["reading"]}
        keys |= {f"sp_{s['key']}" for s in stats_help.procedure_steps(detail)}
    assert not [k for k in keys if k not in STRINGS], [k for k in keys if k not in STRINGS]


def test_the_stats_help_fragment_explains_a_run(seeded):
    client = TestClient(app)
    general = client.get("/api/stats-help")
    assert general.status_code == 200 and "Comprendre" not in general.text and "Diebold-Mariano" in general.text
    run = client.get("/api/stats-help?run_id=XLI_1_h1_a")
    assert run.status_code == 200 and "Run de référence" in run.text and "Procédure appliquée" in run.text
    assert client.get("/api/stats-help?run_id=nope").status_code == 404
    assert client.get("/api/stats-help?dm_alpha=2").status_code == 400
    runs = client.get("/api/stats-help/runs").json()["runs"]
    assert {r["run_id"] for r in runs} == {"XLI_1_h1_a", "MC_1_h1_b"}


def test_the_bar_is_on_every_page_except_the_launch_bar_page(seeded):
    client = TestClient(app)
    for path in ("/", "/runs", "/predictions", "/runs/XLI_1_h1_a/detail", "/vocabulary"):
        assert 'id="stats-bar"' in client.get(path).text, path
    assert 'id="stats-bar"' not in client.get("/launch").text
    assert 'data-run-id="XLI_1_h1_a"' in client.get("/runs/XLI_1_h1_a/detail").text


def test_headline_metrics_come_first_and_folds_are_collapsed_after_five(seeded):
    detail = trackhistory.run_detail(trackdb.connect(), "XLI_1_h1_a")
    assert detail["headline"]["test"]["AUC_ovr_4cls"] == pytest.approx(0.58)
    test_block = detail["fold_metrics"][0]
    assert test_block["split"] == "test" and test_block["metrics"][:2] == ["AUC_ovr_4cls", "F1_dir"]
    html = TestClient(app).get("/runs/XLI_1_h1_a/detail").text
    assert html.index("headline-metrics") < html.index('id="resume"') < html.index('id="folds"')
    assert html.count("data-extra hidden") >= 2           # 7 folds : 5 visibles, 2 repliés
    assert "2 de plus" in html


def test_collapsible_rows_only_when_they_are_worth_hiding():
    components = Path("patrick/webapp/templates/_components.html").read_text(encoding="utf-8")
    env = Environment(loader=DictLoader({"c.html": components}))
    tpl = env.from_string('{% from "c.html" import data_table %}{{ data_table(h, rows, collapse_after=5) }}')
    few = tpl.render(h=["a"], rows=[[i] for i in range(6)])
    many = tpl.render(h=["a"], rows=[[i] for i in range(9)])
    assert "data-rows-toggle" not in few and "data-extra" not in few      # 6 lignes : un repli de 1 ligne n'a pas de sens
    assert many.count("data-extra") == 4 and "4 de plus" in many


def test_the_history_separates_alpha_and_directional_models(seeded):
    rows = {r["run_id"]: r for r in trackdb.list_all_runs(trackdb.connect())}
    assert rows["XLI_1_h1_a"]["kind"] == "directional" and rows["MC_1_h1_b"]["kind"] == "alpha"
    client = TestClient(app)
    alpha = client.get("/runs?kind=alpha").text
    assert "MC_1_h1_b" in alpha and "XLI_1_h1_a" not in alpha
    directional = client.get("/runs?kind=directional").text
    assert "XLI_1_h1_a" in directional and "MC_1_h1_b" not in directional
    both = client.get("/runs").text
    assert "XLI_1_h1_a" in both and "MC_1_h1_b" in both and "kind-badge kind-alpha" in both


def test_the_history_table_leads_with_auc_then_f1(seeded):
    html = TestClient(app).get("/runs").text
    head = re.search(r"<thead>.*?</thead>", html, re.DOTALL).group(0)
    assert head.index(">AUC<") < head.index(">F1<") < head.index("DM p")


def test_a_perfect_score_is_flagged_in_the_history(seeded):
    conn = trackdb.connect()
    with conn:
        conn.execute("UPDATE fold_metric SET value = 0.99 WHERE metric = 'F1_dir' AND split = 'holdout'")
    conn.close()
    html = TestClient(app).get("/runs").text
    assert "tag-suspect" in html
