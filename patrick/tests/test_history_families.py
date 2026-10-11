"""Page /runs (Historique) : machine learning, deep learning et reinforcement learning y sont séparés (une section par famille, ou un onglet
à la fois) et chaque famille a ses propres colonnes. Vraies routes FastAPI et vrais gabarits sur une base pré-remplie ; aucun entraînement."""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.rl.config import RLRunConfig
from patrick.tracking import db
from patrick.tracking import jobs as jobs_db
from patrick.webapp.app import app
from patrick.webapp.forms import default_config_dict


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _add_run(conn, run_id: str, name: str, algos: list[str], target: str = "^VIX") -> None:
    config = default_config_dict()
    config["name"] = name
    config["objective"].update({"target_symbol": target, "horizons": [5], "regimes": ["GLOBAL"]})
    config["models"]["algos"] = algos
    config["sampler"]["candidates"] = ["SMOTE"]
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, run_id, target, 5, "snap1", json.dumps(config), f"cfg_{run_id}", "sha", 42)
    trial_id = db.create_trial(conn, run_id, "GLOBAL", algos[0], "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6, "AUC_ovr_4cls": 0.61})
    db.finish_run(conn, run_id, status="done", n_trials=1)


_RL_RESULT = {
    "kind": "rl", "n_folds": 4, "elapsed_s": 125.0,
    "strategy": {"sharpe": 0.8, "total_return": 0.2, "max_drawdown": -0.1},
    "baselines": {"buy_hold": {"sharpe": 0.5, "total_return": 0.12, "max_drawdown": -0.25},
                  "momentum": {"sharpe": 0.3, "total_return": 0.05, "max_drawdown": -0.2},
                  "flat": {"sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0}},
    "stats": {"psr": 0.91, "dsr": {"dsr": 0.64, "p_value": 0.36}, "n_trials": 3,
              "vs_buy_hold": {"diff": 0.3, "ci_low": -0.1, "ci_high": 0.7, "p_one_sided": 0.2}},
    "seeds": [{"seed": 1, "sharpe": 0.7}, {"seed": 2, "sharpe": 0.9}],
    "curves": {"dates": ["2021-01-04", "2024-06-28"]},
}


def _add_rl_job(conn, name: str, algo: str, status: str, target: str = "^GSPC", result: dict | None = None) -> str:
    cfg = RLRunConfig.model_validate({"name": name, "objective": {"target_symbol": target}, "rl": {"algo": algo}})
    job_id = jobs_db.enqueue_job(conn, cfg.model_dump_json())
    if status in ("done", "error"):
        jobs_db.claim_next_job(conn, 123)
        jobs_db.finish_job(conn, job_id, status, result_json=json.dumps(result) if result else None,
                           error="boom" if status == "error" else None)
    return job_id


@pytest.fixture
def seeded(env):
    conn = db.connect(db.default_db_path())
    _add_run(conn, "run_ml", "arbre_vix", ["RandomForest"])
    _add_run(conn, "run_dl", "reseau_vix", ["MLP", "GRU"])
    _add_run(conn, "run_mix", "melange_vix", ["RandomForest", "MLP"])
    ids = {"done": _add_rl_job(conn, "agent_ppo", "PPO", "done", result=_RL_RESULT),
           "error": _add_rl_job(conn, "agent_dqn", "DQN", "error"),
           "queued": _add_rl_job(conn, "agent_a2c", "A2C", "queued")}
    conn.close()
    return ids


def _sections(html: str) -> dict[str, str]:
    """Le HTML de chaque section de famille de la page."""
    parts = re.split(r'<section class="history-section" data-family="(\w+)">', html)
    return {parts[i]: parts[i + 1].split("</section>")[0] for i in range(1, len(parts), 2)}


def test_a_run_is_deep_learning_only_when_every_algorithm_is_a_network():
    assert db.run_family({"models": {"algos": ["MLP", "LSTM"]}}) == "dl"
    assert db.run_family({"models": {"algos": list(D.ALL_DL_ALGOS)}}) == "dl"
    assert db.run_family({"models": {"algos": ["RandomForest"]}}) == "ml"
    assert db.run_family({"models": {"algos": ["RandomForest", "MLP"]}}) == "ml"
    assert db.run_family({"models": {"algos": []}}) == "ml" and db.run_family({}) == "ml"


def test_list_all_runs_tags_every_run_with_its_family(seeded):
    conn = db.connect(db.default_db_path())
    try:
        families = {r["run_id"]: r["family"] for r in db.list_all_runs(conn)}
    finally:
        conn.close()
    assert families == {"run_ml": "ml", "run_dl": "dl", "run_mix": "ml"}


def test_without_a_tab_each_family_has_its_own_section(client, seeded):
    page = client.get("/runs")
    assert page.status_code == 200
    sections = _sections(page.text)
    assert list(sections) == ["ml", "dl", "rl"]
    assert "arbre_vix" in sections["ml"] and "melange_vix" in sections["ml"] and "reseau_vix" not in sections["ml"]
    assert "reseau_vix" in sections["dl"] and "arbre_vix" not in sections["dl"]
    assert all(n in sections["rl"] for n in ("agent_ppo", "agent_dqn", "agent_a2c"))
    assert not any(n in sections["ml"] + sections["dl"] for n in ("agent_ppo", "agent_dqn"))
    assert 'history-table-cls' in sections["ml"] and 'history-table-cls' in sections["dl"] and 'history-table-rl' in sections["rl"]


def test_the_family_tabs_carry_one_count_each(client, seeded):
    page = client.get("/runs").text
    tabs = re.search(r'<nav class="kind-tabs family-tabs".*?</nav>', page, re.S).group(0)
    counts = [int(c) for c in re.findall(r'class="kind-count">(\d+)<', tabs)]
    assert counts == [6, 2, 1, 3]                                   # tous, ML, DL, RL
    assert 'href="/runs?family=dl"' in tabs and 'href="/runs?family=rl"' in tabs


def test_a_family_tab_shows_that_family_only(client, seeded):
    dl = client.get("/runs?family=dl").text
    assert list(_sections(dl)) == ["dl"] and "reseau_vix" in dl
    assert not any(n in dl for n in ("arbre_vix", "melange_vix", "agent_ppo"))
    assert "history-section-title" not in dl                        # un seul tableau : pas besoin de titre de section
    ml = client.get("/runs?family=ml").text
    assert "arbre_vix" in ml and "melange_vix" in ml and "reseau_vix" not in ml and "agent_ppo" not in ml


def test_the_rl_table_has_strategy_columns_instead_of_classification_ones(client, seeded):
    rl = client.get("/runs?family=rl").text
    assert "agent_ppo" in rl and "agent_dqn" in rl and "arbre_vix" not in rl
    assert "history-table-rl" in rl and "history-table-cls" not in rl
    assert ">0.80<" in rl and ">0.50<" in rl and "+0.30" in rl     # Sharpe, Sharpe B&H, écart
    assert "+20.0 %" in rl and "-10.0 %" in rl and "64.0 %" in rl  # rendement, perte maximale, DSR
    assert ">AUC<" not in rl and "DM p" not in rl
    assert 'name="run_ids"' not in rl and "compare-runs-form" not in rl      # pas de comparaison de runs RL
    assert "hint kind-hint" in rl and "kind=directional" not in rl           # pas de type directionnel/alpha pour le RL


def test_ml_and_dl_tables_keep_compare_and_actions(client, seeded):
    page = client.get("/runs").text
    assert page.count('name="run_ids"') == 3 and "compare-runs-form" in page
    assert "/runs/run_dl/delete" in page and 'data-rename="run_ml"' in page


def test_an_rl_error_counts_as_failed_and_a_queued_job_is_listed(client, seeded):
    failed = client.get("/runs?family=rl&status=failed").text
    assert "agent_dqn" in failed and "agent_ppo" not in failed and "agent_a2c" not in failed
    queued = client.get("/runs?family=rl&status=queued").text
    assert "agent_a2c" in queued and "agent_ppo" not in queued


def test_the_algorithm_filter_spans_the_chosen_family_only(client, seeded):
    rl = client.get("/runs?family=rl").text
    assert '<option value="PPO"' in rl and '<option value="MLP"' not in rl and '<option value="RandomForest"' not in rl
    dl = client.get("/runs?family=dl").text
    assert '<option value="MLP"' in dl and '<option value="PPO"' not in dl
    only_ppo = client.get("/runs?algo=PPO").text
    assert "agent_ppo" in only_ppo and "agent_dqn" not in only_ppo and "arbre_vix" not in only_ppo


def test_the_type_filter_leaves_the_rl_family_out(client, seeded):
    page = client.get("/runs?kind=directional").text
    assert list(_sections(page)) == ["ml", "dl"] and "agent_ppo" not in page
    assert "arbre_vix" in page


def test_an_unknown_family_falls_back_to_the_full_page(client, seeded):
    page = client.get("/runs?family=nope")
    assert page.status_code == 200 and list(_sections(page.text)) == ["ml", "dl", "rl"]


def test_the_scope_lines_count_each_family_on_its_own_measure(client, seeded):
    page = client.get("/runs").text
    assert re.search(r'scope-value">0 / 3<', page)                  # ML + DL : aucun résultat Diebold-Mariano dans cette base
    assert re.search(r'scope-value">1 / 1<', page)                  # RL : le seul run terminé bat acheter et garder (0,8 > 0,5)
    assert 'scope-value">0 / 3<' not in client.get("/runs?family=rl").text


def test_the_side_panel_of_an_rl_run_reads_its_result(client, seeded):
    panel = client.get(f"/runs/{seeded['done']}/panel")
    assert panel.status_code == 200
    text = panel.text
    assert "agent_ppo" in text and "PPO" in text and f"/rl?open={seeded['done']}" in text
    assert ">0.80<" in text and ">0.50<" in text and "+20.0 %" in text and "64.0 %" in text and "91.0 %" in text
    assert "2021-01-04" in text and "2024-06-28" in text and "2 min 05 s" in text


def test_the_side_panel_of_an_unfinished_or_failed_rl_run_says_so(client, seeded):
    failed = client.get(f"/runs/{seeded['error']}/panel").text
    assert "boom" in failed and "banner-error" in failed
    queued = client.get(f"/runs/{seeded['queued']}/panel")
    assert queued.status_code == 200 and "agent_a2c" in queued.text


def test_the_side_panel_of_an_ml_run_is_unchanged(client, seeded):
    assert client.get("/runs/run_ml/panel").status_code == 200
    assert client.get("/runs/inconnu/panel").status_code == 404


def test_an_empty_history_points_to_the_three_launch_pages(client):
    page = client.get("/runs")
    assert page.status_code == 200 and "history-section" not in page.text
    assert all(f'href="{url}"' in page.text for url in ("/ml", "/dl", "/rl"))


def test_the_page_renders_in_english_too(client, seeded):
    page = client.get("/runs?family=rl&lang=en")
    assert page.status_code == 200 and "agent_ppo" in page.text
    assert "Model family (ML, DL, RL)" in page.text
    panel = client.get(f"/runs/{seeded['done']}/panel?lang=en").text
    assert "Out-of-sample period" in panel and "Cumulative trials" in panel
