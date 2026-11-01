"""Pages « À faire » de la Synthèse (`/a-faire/<ligne>`, `webapp/todo_actions.py`) : ce qui est concerné, la cause, et le réentraînement adapté ;
la mise en file n'accepte que ce que la page propose."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from patrick.config.schema import RunConfig
from patrick.tracking import data_health, retrain_advisor
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.webapp import forms, run_manager, todo_actions
from patrick.webapp.app import app
from patrick.webapp.i18n import STRINGS

STAGED_ERROR = "ValueError: La présélection progressive nécessite le schéma walk-forward."


def _cfg(target: str, horizons=(1,), *, name: str | None = None, cpcv_staged: bool = False, source: str | None = None, rule: int = 1) -> str:
    cfg = forms.default_config_dict()
    cfg["name"] = name or f"{forms.slug_target(target)}_3"
    cfg["objective"].update(target_symbol=target, horizons=list(horizons), session_rule=rule)
    if source:
        cfg["objective"]["target_source"] = source
    if cpcv_staged:
        cfg["validation"]["scheme"] = "cpcv"
        cfg["selection"]["screening_mode"] = "total_window"
    return RunConfig.model_validate(cfg).model_dump_json()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    connection = trackdb.connect(str(tmp_path / "p.db"))
    trackdb.upsert_snapshot(connection, "snap", "h", None, None, None)
    yield connection
    connection.close()


@pytest.fixture
def seen(monkeypatch):
    configs: list[RunConfig] = []

    def fake_start(config):
        configs.append(config)
        return {"id": f"job{len(configs)}", "status": "queued", "queue_position": len(configs)}

    monkeypatch.setattr(run_manager, "start_run", fake_start)
    monkeypatch.setattr(run_manager, "next_run_name", lambda sym: f"{forms.slug_target(sym)}_9")
    return configs


@pytest.fixture
def client(conn):
    return TestClient(app, base_url="http://127.0.0.1:8000")


def _failed_job(conn, config_json: str, error: str) -> str:
    job_id = jobs_db.enqueue_job(conn, config_json)
    jobs_db.finish_job(conn, job_id, "error", error=error)
    return job_id


def _done_run(conn, run_id: str, target: str, horizon: int, config_json: str, started_at: str | None = None) -> None:
    trackdb.create_run(conn, run_id, target, horizon, "snap", config_json, "c", "s", 42)
    trackdb.finish_run(conn, run_id, status="done", n_trials=1)
    if started_at:
        conn.execute("UPDATE run SET started_at = ? WHERE run_id = ?", (started_at, run_id))
        conn.commit()


def _group(page: dict, gid: str) -> dict:
    return next(g for g in page["groups"] if g["id"] == gid)


# --------------------------------------------------------------------------- échecs

def test_the_staged_screening_failures_are_retrained_without_the_staged_screening(conn):
    a = _failed_job(conn, _cfg("^GSPC", cpcv_staged=True), STAGED_ERROR)
    b = _failed_job(conn, _cfg("^VIX", (2,), cpcv_staged=True), STAGED_ERROR)
    _failed_job(conn, _cfg("GC=F"), "RuntimeError: panne inconnue")
    page = todo_actions.detail(conn, "failures")
    assert page["n"] == 3
    group = _group(page, "staged_cpcv")
    assert group["kind"] == "retrain" and group["n_todo"] == 2 and group["patch"] == {"staged_screening": False}
    assert {i["source"] for i in group["lines"]} == {a, b}
    other = _group(page, "other")
    assert other["kind"] == "inspect" and other["n_todo"] == 0       # cause inconnue : rien de relancé automatiquement


def test_a_failure_already_covered_by_a_later_run_or_a_queued_job_is_not_proposed_again(conn):
    covered = _failed_job(conn, _cfg("^GSPC", (1,), cpcv_staged=True), STAGED_ERROR)
    queued = _failed_job(conn, _cfg("^VIX", (1,), cpcv_staged=True), STAGED_ERROR)
    old = _failed_job(conn, _cfg("GC=F", (1,), cpcv_staged=True), STAGED_ERROR)
    _done_run(conn, "g1", "^GSPC", 1, _cfg("^GSPC"))                                  # plus récent que l'échec
    _done_run(conn, "gc0", "GC=F", 1, _cfg("GC=F"), started_at="2020-01-01 00:00:00")  # plus ancien : ne remplace rien
    jobs_db.enqueue_job(conn, _cfg("^VIX", (1,)))
    states = {i["source"]: i["state"] for i in _group(todo_actions.detail(conn, "failures"), "staged_cpcv")["lines"]}
    assert states == {covered: "replaced", queued: "pending", old: "todo"}


def test_a_macro_target_is_never_proposed_for_a_retraining(conn):
    job = _failed_job(conn, _cfg("DGS10", cpcv_staged=True, source="fred"), STAGED_ERROR)
    line = _group(todo_actions.detail(conn, "failures"), "staged_cpcv")["lines"][0]
    assert line["source"] == job and line["state"] == "blocked" and "retirée" in line["problem"]


def test_the_launch_queues_the_proposed_retraining_with_the_staged_screening_off(client, conn, seen):
    a = _failed_job(conn, _cfg("^GSPC", cpcv_staged=True), STAGED_ERROR)
    resp = client.post("/api/a-faire/failures/launch", json={"group": "staged_cpcv", "sources": [a]})
    assert resp.status_code == 200 and resp.json()["errors"] == []
    (config,) = seen
    assert config.objective.target_symbol == "^GSPC" and config.validation.scheme == "cpcv"
    assert config.selection.screening_mode == "exhaustive"                           # sinon le moteur refuse : « walk-forward »


def test_the_launch_refuses_what_the_page_does_not_propose(client, conn, seen):
    a = _failed_job(conn, _cfg("^GSPC", cpcv_staged=True), STAGED_ERROR)
    ok = client.post("/api/a-faire/failures/launch", json={"group": "staged_cpcv", "sources": [a, "inconnu"]})
    assert ok.status_code == 400 and "inconnu" in ok.json()["errors"][0] and seen == []   # une source périmée : rien n'est mis en file
    assert client.post("/api/a-faire/failures/launch", json={"group": "staged_cpcv", "sources": []}).status_code == 400
    assert client.post("/api/a-faire/failures/launch", json={"group": "nope", "sources": [a]}).status_code == 400
    assert client.post("/api/a-faire/nope/launch", json={"group": "x", "sources": [a]}).status_code == 404


def test_a_group_to_read_only_cannot_be_launched(client, conn, seen):
    job = _failed_job(conn, _cfg("GC=F"), "RuntimeError: panne inconnue")
    assert client.post("/api/a-faire/failures/launch", json={"group": "other", "sources": [job]}).status_code == 400
    assert seen == []


def test_two_lines_of_the_same_target_are_queued_one_by_one_with_their_own_name(conn, monkeypatch):
    first = _failed_job(conn, _cfg("^GSPC", (1,), cpcv_staged=True), STAGED_ERROR)
    second = _failed_job(conn, _cfg("^GSPC", (5,), name="GSPC_4", cpcv_staged=True), STAGED_ERROR)
    names: list[str] = []

    def fake_start(config):
        names.append(config.name)
        return {"id": f"job{len(names)}", "status": "queued", "queue_position": len(names)}

    counter = iter(range(10, 20))
    monkeypatch.setattr(run_manager, "next_run_name", lambda sym: f"{forms.slug_target(sym)}_{next(counter)}")
    runs, errors = todo_actions.launch(conn, "failures", "staged_cpcv", [first, second], fake_start)
    assert errors == [] and len(runs) == 2 and len(set(names)) == 2


# --------------------------------------------------------------------------- runs suspects et champions de change

def test_suspect_runs_split_into_currency_runs_to_redo_and_macro_runs_to_leave(conn):
    _done_run(conn, "fx1", "EURUSD=X", 1, _cfg("EURUSD=X", rule=1))                                   # règle d'alignement 1
    _done_run(conn, "mac1", "FEDFUNDS", 2, _cfg("FEDFUNDS", (2,), source="fred"))                     # cible macro retirée
    page = todo_actions.detail(conn, "suspect")
    assert page["n"] == 2
    fx, macro = _group(page, "fx_rule1"), _group(page, "macro")
    assert fx["kind"] == "retrain" and fx["n_todo"] == 1 and fx["patch"] == {}
    assert macro["kind"] == "inspect" and macro["n_todo"] == 0 and macro["lines"][0]["target"] == "FEDFUNDS"


def test_a_currency_run_replaced_by_a_clean_later_run_is_not_proposed_again(conn):
    _done_run(conn, "fx1", "EURUSD=X", 1, _cfg("EURUSD=X", rule=1), started_at="2026-10-01 00:00:00")
    _done_run(conn, "fx2", "EURUSD=X", 1, _cfg("EURUSD=X", name="EURUSD_X_4", rule=2), started_at="2026-10-30 00:00:00")
    group = _group(todo_actions.detail(conn, "suspect"), "fx_rule1")
    assert group["n_todo"] == 0 and group["lines"][0]["state"] == "replaced"


def test_the_launch_redoes_a_currency_run_with_the_same_settings(client, conn, seen):
    _done_run(conn, "fx1", "EURUSD=X", 1, _cfg("EURUSD=X", rule=1))
    resp = client.post("/api/a-faire/suspect/launch", json={"group": "fx_rule1", "sources": ["fx1"]})
    assert resp.status_code == 200
    assert seen[0].objective.target_symbol == "EURUSD=X" and seen[0].objective.horizons == [1]
    assert client.post("/api/a-faire/suspect/launch", json={"group": "macro", "sources": ["mac1"]}).status_code == 400


def test_the_currency_champions_of_before_the_fix_are_listed_once_per_launch(conn):
    config = _cfg("EURUSD=X", (1, 5), rule=1)
    for run_id, horizon in (("fx_h1", 1), ("fx_h5", 5)):
        _done_run(conn, run_id, "EURUSD=X", horizon, config)
        trial = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 5, "shap")
        conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) "
                     "VALUES ('EURUSD=X', ?, ?, ?, datetime('now'), 'first')", (horizon, run_id, trial))
    conn.commit()
    page = todo_actions.detail(conn, "fx_legacy")
    (group,) = page["groups"]
    assert page["n"] == 2 and group["n"] == 1 and group["lines"][0]["n_runs"] == 2 and group["n_todo"] == 1


# --------------------------------------------------------------------------- file d'attente et pages

def test_the_queue_page_lists_the_jobs_and_proposes_nothing(conn):
    jobs_db.enqueue_job(conn, _cfg("^GSPC"))
    page = todo_actions.detail(conn, "queue")
    assert page["n"] == 1 and [g["id"] for g in page["groups"]] == ["queued"] and page["groups"][0]["kind"] == "inspect"


def test_the_page_renders_in_french_and_in_english_and_an_unknown_one_is_a_404(client, conn):
    _failed_job(conn, _cfg("^GSPC", cpcv_staged=True), STAGED_ERROR)
    fr = client.get("/a-faire/failures")
    assert fr.status_code == 200 and "Échecs de run récents" in fr.text and "Présélection progressive avec la validation CPCV" in fr.text
    assert "data-td-launch" in fr.text and 'class="td-pick"' in fr.text
    en = client.get("/a-faire/failures", params={"lang": "en"})
    assert "Recent run failures" in en.text and "Staged screening with CPCV validation" in en.text and "Relaunch the selection" in en.text
    assert client.get("/a-faire/nope").status_code == 404


def test_the_home_page_links_each_line_to_its_page(conn, client):
    _failed_job(conn, _cfg("^GSPC", cpcv_staged=True), STAGED_ERROR)
    jobs_db.enqueue_job(conn, _cfg("^VIX"))
    page = client.get("/").text
    assert 'href="/a-faire/failures"' in page and 'href="/a-faire/queue"' in page


# --------------------------------------------------------------------------- cohérence avec le reste

def test_every_group_the_pages_can_show_has_its_title_and_its_explanation():
    ids = {kind[0] for kind in data_health.ERROR_KINDS if kind[0] != "stopped"} | {"other"}
    ids |= {"fx_rule1", "fix_leak", "derived_target", "manual", "macro", "fx_champions", "running", "queued"}
    missing = sorted(k for gid in ids for k in (f"td_g_{gid}_title", f"td_g_{gid}_why") if k not in STRINGS)
    assert not missing
    assert set(todo_actions.FAILURE_PATCH) <= ids and todo_actions.KEYS == ("failures", "suspect", "fx_legacy", "queue")


def test_the_new_failure_causes_are_recognised():
    assert data_health.classify_error(STAGED_ERROR)[0] == "staged_cpcv"
    assert data_health.classify_error("PermissionError: [WinError 5] Accès refusé: 'x.tmp' -> 'x.json'")[0] == "store_locked"


def test_confirming_with_cpcv_turns_the_staged_screening_off_so_the_engine_accepts_the_run():
    diag = retrain_advisor.Diagnosis(run_id="r", target="^GSPC", horizon=1, auc_holdout=0.60, auc_test=0.60, f1_test=0.55, persistence_f1=0.40,
                                     view=forms.to_view(json.loads(_cfg("^GSPC"))))
    suggestion = next(s for s in retrain_advisor.advise(diag, limit=30) if s.key == "confirm_cpcv")
    assert suggestion.patch["scheme"] == "cpcv" and suggestion.patch["staged_screening"] is False
