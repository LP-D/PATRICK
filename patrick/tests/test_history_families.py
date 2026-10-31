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
    "curves": {"dates": ["2021-01-04", "2024-06-28"], "strategy": [1.0, 1.25]},
}


def _add_rl_job(conn, name: str, algo: str, status: str, target: str = "^GSPC", result: dict | None = None,
                out_dir: str | None = None) -> str:
    cfg = RLRunConfig.model_validate({"name": name, "objective": {"target_symbol": target}, "rl": {"algo": algo},
                                      **({"output": {"dir": out_dir}} if out_dir else {})})
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
    assert all(n in sections["rl"] for n in ("agent_ppo", "agent_a2c"))
    assert "agent_dqn" not in sections["rl"]                         # échoué sans aucun résultat : un run vide, masqué par défaut
    assert not any(n in sections["ml"] + sections["dl"] for n in ("agent_ppo", "agent_dqn"))
    assert 'history-table-cls' in sections["ml"] and 'history-table-cls' in sections["dl"] and 'history-table-rl' in sections["rl"]


def test_the_family_tabs_carry_one_count_each(client, seeded):
    page = client.get("/runs").text
    tabs = re.search(r'<nav class="kind-tabs family-tabs".*?</nav>', page, re.DOTALL).group(0)
    counts = [int(c) for c in re.findall(r'class="kind-count">(\d+)<', tabs)]
    assert counts == [5, 2, 1, 2]                                   # tous, ML, DL, RL (le run RL vide est masqué)
    assert 'href="/runs?family=dl"' in tabs and 'href="/runs?family=rl"' in tabs


def test_a_family_tab_shows_that_family_only(client, seeded):
    dl = client.get("/runs?family=dl").text
    assert list(_sections(dl)) == ["dl"] and "reseau_vix" in dl
    assert not any(n in dl for n in ("arbre_vix", "melange_vix", "agent_ppo"))
    assert "history-section-title" not in dl                        # un seul tableau : pas besoin de titre de section
    ml = client.get("/runs?family=ml").text
    assert "arbre_vix" in ml and "melange_vix" in ml and "reseau_vix" not in ml and "agent_ppo" not in ml


def test_the_rl_table_has_strategy_columns_instead_of_classification_ones(client, seeded):
    rl = client.get("/runs?family=rl&vides=1").text
    assert "agent_ppo" in rl and "agent_dqn" in rl and "arbre_vix" not in rl
    assert "history-table-rl" in rl and "history-table-cls" not in rl
    assert ">0.80<" in rl and ">0.50<" in rl and "+0.30" in rl     # Sharpe, Sharpe B&H, écart
    assert "+20.0 %" in rl and "-10.0 %" in rl and "64.0 %" in rl  # rendement, perte maximale, DSR
    assert ">AUC<" not in rl and "DM p" not in rl
    assert "compare-runs-form" not in rl and "compare-rl-form" in rl         # la comparaison RL a son propre formulaire
    assert "hint kind-hint" in rl and "kind=directional" not in rl           # pas de type directionnel/alpha pour le RL


def test_ml_and_dl_tables_keep_compare_and_actions(client, seeded):
    page = client.get("/runs").text
    sections = _sections(page)
    assert (sections["ml"] + sections["dl"]).count('name="run_ids"') == 3 and "compare-runs-form" in page
    assert "/runs/run_dl/delete" in page and 'data-rename="run_ml"' in page


def test_an_rl_error_counts_as_failed_and_a_queued_job_is_listed(client, seeded):
    failed = client.get("/runs?family=rl&status=failed&vides=1").text
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

# --------------------------------------------------------------------------- comparaison et suppression des runs RL


def _job(job_id: str):
    conn = db.connect(db.default_db_path())
    try:
        return conn.execute("SELECT status, phase, result_json, config_json FROM job WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()


def test_rl_rows_get_a_checkbox_when_done_and_a_delete_button_unless_running(client, seeded):
    rl = _sections(client.get("/runs?vides=1").text)["rl"]
    rows = {m.group(1): m.group(0) for m in re.finditer(r'<tr class="history-row" data-run-id="(\w+)".*?</tr>', rl, re.DOTALL)}
    done, error, queued = rows[seeded["done"]], rows[seeded["error"]], rows[seeded["queued"]]
    assert 'form="compare-rl-form"' in done and 'form="compare-rl-form"' not in error and 'form="compare-rl-form"' not in queued
    assert f"/runs/{seeded['done']}/delete" in done and f"/runs/{seeded['error']}/delete" in error
    assert "/delete" not in queued                                   # un run en file ne se supprime pas
    assert "Sharpe déflaté" in done and "Delete" not in done


def test_two_rl_runs_are_compared_side_by_side(client, seeded):
    conn = db.connect(db.default_db_path())
    other = _add_rl_job(conn, "agent_b", "PPO", "done", result={**_RL_RESULT, "strategy": {"sharpe": 1.4, "total_return": 0.31, "max_drawdown": -0.2}})
    conn.close()
    page = client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids={other}")
    assert page.status_code == 200
    text = page.text
    assert "agent_ppo" in text and "agent_b" in text and f"/rl?open={other}" in text
    assert ">0.80<" in text and ">1.40<" in text                       # le Sharpe de chacun
    assert re.search(r'<td class="num pk-mono best">1\.40</td>', text) and not re.search(r'best">0\.80<', text)    # le meilleur est repéré
    assert "+31.0 %" in text and "-20.0 %" in text and "[-0.10 ; +0.70]" in text
    assert 'id="cmp-rl-data"' in text and "/static/rl_compare.js" in text and "compare-runs-table" in text
    assert "cmp-group" in text and "Résultats hors échantillon" in text
    assert "cmp-diff" in text                                          # le Sharpe diffère : ligne marquée
    assert "banner-warning" not in text                               # même cible, même période : rien à signaler


def test_the_rl_comparison_flags_different_targets_and_periods_and_draws_the_curves(client, seeded):
    conn = db.connect(db.default_db_path())
    other = _add_rl_job(conn, "agent_vix", "PPO", "done", target="^VIX", result={
        **_RL_RESULT, "curves": {"dates": ["2022-01-03", "2025-01-02"], "strategy": [1.0, 1.4]}})
    conn.close()
    text = client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids={other}").text
    assert text.count('role="note"') == 2                              # cibles ET périodes différentes
    data = json.loads(re.search(r'<script id="cmp-rl-data" type="application/json">(.*?)</script>', text, re.DOTALL).group(1))
    assert data["dates"] == ["2021-01-04", "2022-01-03", "2024-06-28", "2025-01-02"] and len(data["series"]) == 2
    assert [s["values"] for s in data["series"]] == [[1.0, 1.0, 1.25, None], [None, 1.0, 1.0, 1.4]]


def test_the_equity_curves_of_several_runs_share_one_date_grid(client, seeded):
    conn = db.connect(db.default_db_path())
    first = _add_rl_job(conn, "agent_c1", "PPO", "done", result={**_RL_RESULT, "curves": {"dates": ["2021-01-04", "2021-02-01"], "strategy": [1.0, 1.1]}})
    second = _add_rl_job(conn, "agent_c2", "PPO", "done", result={**_RL_RESULT, "curves": {"dates": ["2021-01-18", "2021-03-01"], "strategy": [1.0, 1.3]}})
    conn.close()
    text = client.get(f"/compare-runs?run_ids={first}&run_ids={second}").text
    data = json.loads(re.search(r'<script id="cmp-rl-data" type="application/json">(.*?)</script>', text, re.DOTALL).group(1))
    assert data["dates"] == ["2021-01-04", "2021-01-18", "2021-02-01", "2021-03-01"]
    one, two = (s["values"] for s in data["series"])
    assert one == [1.0, 1.0, 1.1, None]                                 # report de la dernière valeur, vide après la fin du run
    assert two == [None, 1.0, 1.0, 1.3]                                 # vide avant le début du run


def test_an_unfinished_rl_run_can_still_be_compared_with_dashes(client, seeded):
    text = client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids={seeded['queued']}").text
    assert "agent_a2c" in text and "—" in text


def test_rl_runs_are_never_compared_with_ml_or_dl_runs(client, seeded):
    mixed = client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids=run_ml")
    assert mixed.status_code == 400 and "reinforcement learning" in mixed.json()["detail"]
    assert client.get(f"/compare-runs?run_ids={seeded['done']}").status_code == 400            # 2 à 4 runs
    assert client.get("/compare-runs?run_ids=run_ml&run_ids=run_dl").status_code == 200       # ML et DL se comparent toujours
    assert client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids=inconnu").status_code == 400


def test_the_rl_comparison_page_renders_in_english(client, seeded):
    conn = db.connect(db.default_db_path())
    other = _add_rl_job(conn, "agent_b", "PPO", "done", result=_RL_RESULT)
    conn.close()
    text = client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids={other}&lang=en").text
    assert "Out-of-sample results" in text and "Reward" in text and "Buy-and-hold Sharpe" in text


def test_deleting_a_done_rl_run_hides_it_but_it_still_counts_as_a_trial(client, seeded):
    from patrick.rl.run import count_prior_rl_runs
    db_path = db.default_db_path()
    before = count_prior_rl_runs(db_path, "^GSPC")
    response = client.post(f"/runs/{seeded['done']}/delete", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/runs"
    status, phase, result_json, config_json = _job(seeded["done"])
    assert (status, phase, result_json) == ("done", "deleted", None) and "GSPC" in config_json
    assert count_prior_rl_runs(db_path, "^GSPC") == before == 1        # la tentative supprimée reste dans le Sharpe déflaté
    assert "agent_ppo" not in client.get("/runs").text
    assert [r for r in client.get("/api/rl/runs").json()["runs"] if r["name"] == "agent_ppo"] == []
    assert client.get(f"/runs/{seeded['done']}/panel").status_code == 404
    assert client.get(f"/rl?open={seeded['done']}").status_code == 404
    assert client.post(f"/runs/{seeded['done']}/delete").status_code == 404                       # déjà supprimé
    assert client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids={seeded['error']}").status_code == 400


def test_deleting_a_failed_rl_run_removes_its_row(client, seeded):
    assert client.post(f"/runs/{seeded['error']}/delete").status_code == 200
    assert _job(seeded["error"]) is None


def test_a_running_or_queued_rl_run_cannot_be_deleted(client, seeded):
    response = client.post(f"/runs/{seeded['queued']}/delete", follow_redirects=False)
    assert response.status_code == 409 and _job(seeded["queued"]) is not None
    assert client.post("/runs/inconnu/delete").status_code == 404


def test_deleting_an_ml_run_still_works_next_to_rl_runs(client, seeded):
    assert client.post("/runs/run_dl/delete").status_code == 200
    page = client.get("/runs").text
    assert "reseau_vix" not in page and "arbre_vix" in page and "agent_ppo" in page


def test_deleting_an_rl_run_removes_only_its_own_result_files(client, tmp_path):
    out = tmp_path / "runs" / "agent_files"
    (out / "models").mkdir(parents=True)
    result_file, csv_file, model = out / "rl_result.json", out / "rl_oos.csv", out / "models" / "m.zip"
    for f in (result_file, csv_file, model):
        f.write_text("x")
    bystander = out / "notes.txt"                       # un fichier de l'utilisateur dans le même dossier : jamais touché
    bystander.write_text("garde-moi")
    outside = tmp_path / "ailleurs.csv"                 # un chemin hors du dossier de sortie dans les artefacts : jamais touché
    outside.write_text("garde-moi aussi")
    conn = db.connect(db.default_db_path())
    job_id = _add_rl_job(conn, "agent_files", "PPO", "done", out_dir=str(out), result={
        **_RL_RESULT, "artifacts": {"result_json": str(result_file), "oos_csv": str(csv_file), "model_seed1": str(model),
                                    "stray": str(outside)}})
    conn.close()
    assert client.post(f"/runs/{job_id}/delete").status_code == 200
    assert not result_file.exists() and not csv_file.exists() and not model.exists() and not (out / "models").exists()
    assert bystander.exists() and outside.exists() and out.exists()            # le dossier non vide reste


def test_the_output_folder_is_left_alone_when_another_run_uses_it(client, tmp_path):
    out = tmp_path / "shared"
    out.mkdir()
    result_file = out / "rl_result.json"
    result_file.write_text("x")
    conn = db.connect(db.default_db_path())
    first = _add_rl_job(conn, "agent_one", "PPO", "done", out_dir=str(out), result={**_RL_RESULT, "artifacts": {"result_json": str(result_file)}})
    _add_rl_job(conn, "agent_two", "PPO", "done", out_dir=str(out), result=_RL_RESULT)
    conn.close()
    assert client.post(f"/runs/{first}/delete").status_code == 200
    assert result_file.exists()                                         # l'autre run en a besoin


def test_a_delete_comes_back_to_the_view_it_started_from(client, seeded):
    back = client.post(f"/runs/{seeded['error']}/delete", headers={"referer": "http://localhost/runs?family=rl&status=failed"}, follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/runs?family=rl&status=failed"
    other = client.post("/runs/run_dl/delete", headers={"referer": "http://elsewhere.example/predictions?x=1"}, follow_redirects=False)
    assert other.headers["location"] == "/runs"                       # never an outside address or another page


def test_equal_values_do_not_crown_a_best_run(client, seeded):
    conn = db.connect(db.default_db_path())
    twin = _add_rl_job(conn, "agent_twin", "PPO", "done", result=_RL_RESULT)
    conn.close()
    text = client.get(f"/compare-runs?run_ids={seeded['done']}&run_ids={twin}").text
    assert not re.search(r'<td class="[^"]*\bbest\b', text)
