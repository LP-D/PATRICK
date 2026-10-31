"""Historique allégé : index léger + enrichissement des seules lignes affichées, pagination, runs vides masqués, et runs arrêtés à la main
qui montrent ce qu'ils ont effectué (statut « stopped », résultats provisoires du meilleur essai déjà évalué). Vraies routes, vraie base
temporaire ; aucun entraînement."""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import class_balance, db, jobs
from patrick.webapp import app as app_module
from patrick.webapp.app import app
from patrick.webapp.forms import default_config_dict


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_NO_AUTO_WORKER", "1")


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _config(name: str, algos: list[str], target: str) -> str:
    config = default_config_dict()
    config["name"] = name
    config["objective"].update({"target_symbol": target, "horizons": [5], "regimes": ["GLOBAL"]})
    config["models"]["algos"] = algos
    config["sampler"]["candidates"] = ["SMOTE"]
    return json.dumps(config)


def _run(conn, run_id: str, name: str = "", algos=("RandomForest",), target: str = "^VIX", status: str = "running",
         error: str | None = None, job_id: str | None = None, trials: list[tuple[str, list[float]]] = ()):
    """Un run avec ses essais (algo, F1 par pli) ; jamais de meilleur essai : c'est ce que laisse un arrêt."""
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, run_id, target, 5, "snap1", _config(name or run_id, list(algos), target), f"cfg_{run_id}", "sha", 42, job_id=job_id)
    for algo, folds in trials:
        trial_id = db.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", 8, "shap")
        for index, f1 in enumerate(folds, start=1):
            db.add_fold_metrics(conn, trial_id, index, "test", {"F1_dir": f1, "AUC_ovr_4cls": 0.5 + f1 / 10})
    if status != "running":
        db.finish_run(conn, run_id, status=status, error=error)


def _done_run(conn, run_id: str, name: str, target: str = "^VIX"):
    _run(conn, run_id, name, target=target, trials=[("RandomForest", [0.6, 0.62])])
    trial_id = conn.execute("SELECT trial_id FROM trial WHERE run_id = ?", (run_id,)).fetchone()[0]
    db.mark_best_trial(conn, trial_id)
    db.finish_run(conn, run_id, status="done", n_trials=1)


def _rows(page: str) -> list[str]:
    return re.findall(r'<tr class="history-row" data-run-id="([^"]+)"', page)


# ------------------------------------------------------------------------------------------------------ index et enrichissement


def test_the_light_index_carries_what_filters_and_pages_need_without_any_figure(tmp_path):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r_done", "fini")
    _run(conn, "r_dl", "reseau", algos=("MLP", "GRU"), status="failed", error="boom", trials=[("MLP", [0.5])])
    _run(conn, "r_stop", "arrete", status="failed", error=db.USER_STOPPED_ERROR)
    index = {r["run_id"]: r for r in db.list_run_index(conn)}
    conn.close()
    assert index["r_done"]["name"] == "fini" and index["r_done"]["algorithms"] == ["RandomForest"] and index["r_done"]["scheme"] == "walkforward"
    assert index["r_dl"]["family"] == "dl" and index["r_dl"]["status_label"] == "failed" and index["r_dl"]["has_trials"]
    assert index["r_stop"]["status_label"] == "stopped" and index["r_stop"]["status"] == "failed"
    assert index["r_stop"]["empty"] and not index["r_dl"]["empty"] and not index["r_done"]["empty"]
    assert "best_auc" not in index["r_done"] and "class_balance" not in index["r_done"]          # aucun chiffre : rien n'est calculé


def test_a_corrupt_config_does_not_break_the_index(tmp_path):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r_ok", "ok")
    with conn:
        conn.execute("UPDATE run SET config_json = '{not json' WHERE run_id = 'r_ok'")
    row = db.list_run_index(conn)[0]
    conn.close()
    assert row["run_id"] == "r_ok" and row["name"] is None and row["scheme"] == "walkforward" and row["algorithms"] == []


def test_list_all_runs_keeps_its_shape_and_run_rows_reads_only_the_runs_asked(tmp_path):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r1", "un")
    _done_run(conn, "r2", "deux")
    everything = {r["run_id"]: r for r in db.list_all_runs(conn)}
    only = db.run_rows(conn, ["r2"])
    conn.close()
    assert set(everything) == {"r1", "r2"} and [r["run_id"] for r in only] == ["r2"]
    expected = {"run_id", "target", "kind", "family", "suspect", "best_auc", "holdout_auc", "holdout_f1_dir", "horizon", "status", "started_at",
                "finished_at", "n_trials", "name", "config_json", "scheme", "best_f1_dir", "dm_p_value", "dm_sample", "benchmark_f1_dir",
                "class_balance"}
    assert expected <= set(everything["r1"]) and everything["r1"]["best_f1_dir"] == pytest.approx(0.61)
    assert only[0] == everything["r2"]


# ------------------------------------------------------------------------------------------------------ runs arrêtés


def test_a_stopped_run_keeps_what_it_did_as_provisional_results(tmp_path):
    conn = db.connect(db.default_db_path())
    _run(conn, "r_stop", "arrete", status="failed", error=db.USER_STOPPED_ERROR, trials=[
        ("XGBoost", [0.90]),                          # un seul pli, chanceux : ne doit pas passer devant les finalistes
        ("RandomForest", [0.55, 0.57, 0.59]),         # évalué sur 3 plis
        ("LightGBM", [0.60, 0.62, 0.64])])            # évalué sur 3 plis, meilleur F1 moyen
    row = db.run_rows(conn, ["r_stop"])[0]
    best_trial = db.partial_best_trials(conn, ["r_stop"])["r_stop"]
    algo = conn.execute("SELECT algo FROM trial WHERE trial_id = ?", (best_trial,)).fetchone()[0]
    conn.close()
    assert algo == "LightGBM"
    assert row["partial"] and row["status_label"] == "stopped" and row["best_f1_dir"] == pytest.approx(0.62)
    assert row["best_auc"] == pytest.approx(0.562)


def test_a_finished_run_never_shows_provisional_figures(tmp_path):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r_done", "fini")
    row = db.run_rows(conn, ["r_done"])[0]
    conn.close()
    assert row["partial"] is False and row["status_label"] == "done"


def test_a_failed_run_with_trials_is_partial_too_but_an_empty_one_is_not(tmp_path):
    conn = db.connect(db.default_db_path())
    _run(conn, "r_crash", status="failed", error="orphaned", trials=[("RandomForest", [0.6])])
    _run(conn, "r_empty", status="failed", error="orphaned")
    rows = {r["run_id"]: r for r in db.run_rows(conn, ["r_crash", "r_empty"])}
    conn.close()
    assert rows["r_crash"]["partial"] and rows["r_crash"]["best_f1_dir"] == pytest.approx(0.6)
    assert not rows["r_empty"]["partial"] and rows["r_empty"]["best_f1_dir"] is None and rows["r_empty"]["empty"]


def test_stopping_a_job_records_the_runs_with_their_trial_count(tmp_path):
    conn = db.connect(db.default_db_path())
    job_id = jobs.enqueue_job(conn, json.dumps({"name": "lot"}))
    jobs.claim_next_job(conn, 4242)
    _run(conn, "r_a", job_id=job_id, trials=[("RandomForest", [0.6, 0.6]), ("XGBoost", [0.5])])
    _run(conn, "r_b", job_id=job_id)
    assert jobs.finish_user_stopped_job(conn, job_id)
    rows = {r["run_id"]: r for r in db.list_run_index(conn)}
    conn.close()
    assert rows["r_a"]["status_label"] == "stopped" and rows["r_a"]["n_trials"] == 2 and not rows["r_a"]["empty"]
    assert rows["r_b"]["status_label"] == "stopped" and rows["r_b"]["n_trials"] == 0 and rows["r_b"]["empty"]


def test_the_history_shows_a_stopped_run_with_its_scores_and_the_partial_tag(client):
    conn = db.connect(db.default_db_path())
    _run(conn, "r_stop", "arrete_vix", status="failed", error=db.USER_STOPPED_ERROR, trials=[("RandomForest", [0.6, 0.64])])
    conn.close()
    page = client.get("/runs?family=ml").text
    row = re.search(r'<tr class="history-row" data-run-id="r_stop".*?</tr>', page, re.DOTALL).group(0)
    assert "stopped" in row and "failed" not in row
    assert ">0.620<" in row and "tag-partial" in row                  # F1 moyen des plis du meilleur essai déjà évalué
    only_stopped = client.get("/runs?family=ml&status=stopped").text
    only_failed = client.get("/runs?family=ml&status=failed&vides=1").text
    assert "r_stop" in _rows(only_stopped) and "r_stop" not in _rows(only_failed)


def test_the_side_panel_of_a_stopped_run_warns_and_lists_its_provisional_folds(client):
    conn = db.connect(db.default_db_path())
    _run(conn, "r_stop", "arrete_vix", status="failed", error=db.USER_STOPPED_ERROR, trials=[("RandomForest", [0.6, 0.64])])
    conn.close()
    text = client.get("/runs/r_stop/panel").text
    assert "Run interrompu" in text and "stopped" in text and "data-table" in text
    assert client.get("/runs/inconnu/panel").status_code == 404


def test_stopped_runs_can_be_compared_and_deleted(client):
    conn = db.connect(db.default_db_path())
    _run(conn, "r_s1", "un", status="failed", error=db.USER_STOPPED_ERROR, trials=[("RandomForest", [0.6])])
    _run(conn, "r_s2", "deux", status="failed", error=db.USER_STOPPED_ERROR, trials=[("RandomForest", [0.7])])
    conn.close()
    compare = client.get("/compare-runs?run_ids=r_s1&run_ids=r_s2")
    assert compare.status_code == 200 and "stopped" in compare.text and "0.7000" in compare.text
    assert client.post("/runs/r_s1/delete").status_code == 200
    assert client.get("/runs/r_s1/panel").status_code == 404


# ------------------------------------------------------------------------------------------------------ runs vides


def test_empty_runs_are_hidden_by_default_and_counted(client):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r_done", "fini")
    _run(conn, "r_void1", status="failed", error="orphaned: no matching process at worker startup")
    _run(conn, "r_void2", status="failed", error=db.USER_STOPPED_ERROR)
    conn.close()
    page = client.get("/runs?family=ml").text
    assert _rows(page) == ["r_done"] and "history-empties" in page
    note = re.search(r'<p class="scope-line history-empties".*?</p>', page, re.DOTALL).group(0)
    assert ">2<" in note and "vides=1" in note and "data-keep" in note
    everything = client.get("/runs?family=ml&vides=1").text
    assert sorted(_rows(everything)) == ["r_done", "r_void1", "r_void2"] and "vides=1" not in re.search(
        r'<p class="scope-line history-empties".*?</p>', everything, re.DOTALL).group(0)


def test_no_note_when_there_is_no_empty_run(client):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r_done", "fini")
    conn.close()
    assert "history-empties" not in client.get("/runs").text


# ------------------------------------------------------------------------------------------------------ pagination


def _many(n: int):
    conn = db.connect(db.default_db_path())
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    for i in range(n):
        db.create_run(conn, f"r{i:03d}", "^VIX", 5, "snap1", _config(f"run_{i:03d}", ["RandomForest"], "^VIX"), f"cfg{i}", "sha", 42)
        db.finish_run(conn, f"r{i:03d}", status="done", n_trials=1)
        with conn:
            conn.execute("UPDATE run SET started_at = ? WHERE run_id = ?", (f"2026-01-01 00:{i // 60:02d}:{i % 60:02d}", f"r{i:03d}"))
    conn.close()


def test_one_family_is_paginated_most_recent_first(client):
    _many(120)
    first = client.get("/runs?family=ml").text
    assert len(_rows(first)) == 50 and _rows(first)[0] == "r119" and _rows(first)[-1] == "r070"
    assert "Page 1 / 3" in first and 'rel="next"' in first and 'rel="prev"' not in first
    third = client.get("/runs?family=ml&page=3").text
    assert _rows(third) == [f"r{i:03d}" for i in range(19, -1, -1)] and "Page 3 / 3" in third and 'rel="next"' not in third
    assert 'rel="prev"' in third
    assert client.get("/runs?family=ml&page=99").text.count("Page 3 / 3") == 1          # une page trop loin revient à la dernière
    assert client.get("/runs?family=ml&page=0").status_code == 422


def test_the_pager_keeps_the_filters(client):
    _many(60)
    page = client.get("/runs?family=ml&target=%5EVIX&q=run_").text
    pager = re.search(r'<nav class="history-pager".*?</nav>', page, re.DOTALL).group(0)
    assert "family=ml" in pager and "target=%5EVIX" in pager and "q=run_" in pager and "page=2" in pager


def test_the_all_view_shows_a_preview_per_family_with_a_link_to_the_rest(client):
    _many(30)
    page = client.get("/runs").text
    ml = re.search(r'<section class="history-section" data-family="ml">.*?</section>', page, re.DOTALL).group(0)
    assert len(_rows(ml)) == 12 and "history-more" in ml and "/runs?family=ml" in ml and "(les 12 plus récents ci-dessus)" in ml
    assert 'class="kind-count">30<' in ml                                                  # le titre porte le total, pas la tranche
    assert "history-pager" not in page


def test_the_dm_scope_counts_every_filtered_run_not_only_the_page(client):
    _many(70)
    conn = db.connect(db.default_db_path())
    for i in (0, 1, 2):                               # trois runs anciens (hors de la première page) ont un résultat Diebold-Mariano
        db.save_dm_result(conn, f"r{i:03d}", {"baseline": "majority", "dm_stat": 2.0, "p_value": 0.03}, sample="holdout")
    conn.close()
    page = client.get("/runs?family=ml").text
    assert re.search(r'scope-value">3 / 70<', page) and "r000" not in _rows(page)


def test_only_the_shown_rows_are_enriched(client, monkeypatch):
    _many(80)
    seen: list[int] = []
    real = class_balance.for_runs

    def spy(conn, run_ids, best_trial_by_run=None):
        seen.append(len(run_ids))
        return real(conn, run_ids, best_trial_by_run)

    monkeypatch.setattr(class_balance, "for_runs", spy)
    client.get("/runs?family=ml")
    client.get("/runs")
    assert seen and max(seen) <= app_module.HISTORY_PAGE_SIZE                                # jamais les 80 runs d'un coup


def test_the_panel_and_the_comparison_do_not_read_every_run(client, monkeypatch):
    _many(5)
    monkeypatch.setattr(db, "list_all_runs", lambda *a, **k: pytest.fail("relit tous les runs"))
    assert client.get("/runs/r001/panel").status_code == 200
    assert client.get("/compare-runs?run_ids=r001&run_ids=r002").status_code == 200


def test_the_analyses_view_counts_without_reading_every_run(client, monkeypatch):
    _many(5)
    monkeypatch.setattr(db, "list_all_runs", lambda *a, **k: pytest.fail("relit tous les runs"))
    assert client.get("/runs?vue=analyses").status_code == 200


def test_everything_renders_in_english(client):
    conn = db.connect(db.default_db_path())
    _run(conn, "r_stop", "arrete_vix", status="failed", error=db.USER_STOPPED_ERROR, trials=[("RandomForest", [0.6])])
    _run(conn, "r_void", status="failed", error="orphaned")
    conn.close()
    page = client.get("/runs?family=ml&lang=en").text
    assert "partial" in page and "EMPTY RUNS" in page and "run(s) shown out of" in page


# ------------------------------------------------------------------------------------------------------ runs RL


def _rl_job(conn, name: str, status: str, result: str | None = None, error: str | None = None) -> str:
    from patrick.rl.config import RLRunConfig
    cfg = RLRunConfig.model_validate({"name": name, "objective": {"target_symbol": "^GSPC"}, "rl": {"algo": "PPO"}})
    job_id = jobs.enqueue_job(conn, cfg.model_dump_json())
    if status in ("done", "error"):
        jobs.claim_next_job(conn, 1)
        jobs.finish_job(conn, job_id, status, result_json=result, error=error)
    return job_id


_RESULT = json.dumps({"strategy": {"sharpe": 0.8, "total_return": 0.2, "max_drawdown": -0.1}, "baselines": {"buy_hold": {"sharpe": 0.5}},
                      "stats": {"dsr": {"dsr": 0.64}}})


def test_the_light_rl_history_gives_the_same_rows_as_the_full_reading(tmp_path):
    from patrick.webapp import rl_routes
    conn = db.connect(db.default_db_path())
    _rl_job(conn, "agent_done", "done", _RESULT)
    _rl_job(conn, "agent_err", "error", error=db.USER_STOPPED_ERROR)
    _rl_job(conn, "agent_queued", "queued")
    conn.close()
    assert rl_routes.list_rl_history() == rl_routes.list_rl_jobs(None) or (
        [{k: v for k, v in r.items() if k != "created_at"} for r in rl_routes.list_rl_history()]
        == [{k: v for k, v in r.items() if k != "created_at"} for r in rl_routes.list_rl_jobs(None)])
    done = next(r for r in rl_routes.list_rl_history() if r["name"] == "agent_done")
    assert (done["sharpe"], done["sharpe_buy_hold"], done["total_return"], done["max_drawdown"], done["dsr"]) == (0.8, 0.5, 0.2, -0.1, 0.64)


def test_an_unreadable_rl_result_does_not_break_the_history(client):
    from patrick.webapp import rl_routes
    conn = db.connect(db.default_db_path())
    _rl_job(conn, "agent_ok", "done", _RESULT)
    broken = _rl_job(conn, "agent_broken", "done", "{not json")
    conn.close()
    names = {r["name"]: r for r in rl_routes.list_rl_history()}
    assert set(names) == {"agent_ok", "agent_broken"} and names["agent_broken"]["sharpe"] is None
    page = client.get("/runs?family=rl")
    assert page.status_code == 200 and broken in _rows(page.text)


def test_a_stopped_rl_run_is_labelled_stopped_and_counted_as_empty(client):
    conn = db.connect(db.default_db_path())
    _rl_job(conn, "agent_done", "done", _RESULT)
    stopped = _rl_job(conn, "agent_stop", "error", error=db.USER_STOPPED_ERROR)
    conn.close()
    assert stopped not in _rows(client.get("/runs?family=rl").text)
    shown = client.get("/runs?family=rl&vides=1").text
    row = re.search(rf'<tr class="history-row" data-run-id="{stopped}".*?</tr>', shown, re.DOTALL).group(0)
    assert "stopped" in row
    assert stopped in _rows(client.get("/runs?family=rl&status=stopped&vides=1").text)


def test_callers_that_do_not_show_the_class_balance_can_skip_it(tmp_path, monkeypatch):
    conn = db.connect(db.default_db_path())
    _done_run(conn, "r1", "un")
    calls = []
    monkeypatch.setattr(class_balance, "for_runs", lambda *a, **k: calls.append(1) or {})
    skipped = db.list_all_runs(conn, with_balance=False)
    assert calls == [] and skipped[0]["class_balance"] is None and skipped[0]["best_f1_dir"] == pytest.approx(0.61)
    db.list_all_runs(conn)
    conn.close()
    assert calls == [1]                                              # par défaut la répartition est toujours lue
