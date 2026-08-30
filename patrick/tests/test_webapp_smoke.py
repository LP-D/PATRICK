"""Test de fumée de l'interface web : le pipeline tourne pour de vrai, dans un
vrai `patrick worker` en process séparé (Phase 3.1) — pas de réseau : au lieu
de monkeypatcher `ingest()` (invisible pour un process séparé, qui ne partage
aucun état Python avec le process de test), on pré-remplit le cache disque du
`DataStore` avec la même donnée synthétique que `test_pipeline_smoke.py` ;
`ingest()` la retrouve normalement via son chemin de cache habituel, que ce
soit exécuté en process ou dans le worker séparé.

Chaque test isole sa propre base SQLite et son propre data lake sur
`tmp_path` via les variables d'environnement `PATRICK_DB_PATH`/
`PATRICK_STORE_ROOT` (lues à chaque appel, pas figées à l'import — cf.
`tracking.db.default_db_path`/`data.store._default_store_dir`), sans quoi
tous les tests partageraient la vraie base `~/.patrick/patrick.db`.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.webapp import forms, run_manager
from patrick.webapp.app import app

# Rapport de correction, D1 : les deux tests lancent un run pipeline complet
# via un vrai worker séparé (~50s chacun mesurés) -- exclus par défaut,
# cf. pyproject.toml.
pytestmark = pytest.mark.slow

TARGET_SYMBOL = "^VIX"


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_VIX": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Base + data lake dédiés à ce test, et arrêt automatique rapide du
    worker séparé une fois la file vide (pas de process fantôme entre tests)."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("PATRICK_WORKER_IDLE_TIMEOUT", "8")
    DataStore(root=str(tmp_path / "store")).save(f"raw_{TARGET_SYMBOL}", _synthetic_raw())


def _form_data(tmp_path) -> dict:
    return {
        "target_symbols": [TARGET_SYMBOL],
        "horizons": "3,5",
        "flat_thr": "0.003",
        "regimes": "GLOBAL",
        "start_date": "2015-01-01",
        "yf_coverage": "0.85",
        "interact_top_base": "15",
        "interact_top_pairs": "8",
        "interact_final_n": "6",
        "pool_prefilter": "60",
        "n_wf_folds": "2",
        "min_train_frac": "0.5",
        "min_train_rows": "100",
        "min_test_rows": "20",
        "selection_method": "shap",
        "n_features_grid": "5,8",
        "shap_sample": "200",
        "tuning_enabled": "on",
        "optuna_select_top_k_per_horizon": "on",
        "top_k": "2",
        "n_trials": "3",
        "cv_splits": "2",
        "output_dir": str(tmp_path / "runs"),
        "seed": "42",
        "families": ["technical", "interactions", "spike", "vol_models", "macro"],
        "vol_models": ["egarch", "kalman"],
        "sampler_candidates": ["SMOTE"],
        "algos": ["RandomForest", "XGBoost"],
    }


def _to_formdata(d: dict) -> FormData:
    """Convertit le dict de `_form_data` (valeurs `list` pour les champs
    multi-sélection) en `starlette.datastructures.FormData` -- la même forme
    que celle que `forms.build_config_dict` reçoit en production via `await
    request.form()`, sans passer par un aller-retour HTTP réel."""
    pairs = []
    for k, v in d.items():
        if isinstance(v, list):
            pairs.extend((k, item) for item in v)
        else:
            pairs.append((k, v))
    return FormData(pairs)


def _wait_for_status(client, run_id, *, not_in: set[str], deadline_s: float) -> dict:
    deadline = time.time() + deadline_s
    status = None
    while time.time() < deadline:
        status = client.get(f"/runs/{run_id}/status").json()
        if status["status"] not in not_in:
            return status
        time.sleep(0.5)
    assert status is not None, "aucune réponse du serveur"
    raise AssertionError(f"délai dépassé, statut encore {status['status']!r}: {status}")


def test_run_via_web_form_end_to_end(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["runs"]) == 1, body
    run = body["runs"][0]
    # `start_run` enfile désormais toujours en base ('queued') : la transition
    # vers 'running' est décidée par le worker séparé, jamais immédiate.
    assert run["status"] == "queued", run
    run_id = run["run_id"]

    status = _wait_for_status(client, run_id, not_in={"queued", "running"}, deadline_s=240)
    assert status["status"] == "done", status

    results = client.get(f"/runs/{run_id}/results").json()
    assert results["n_evaluations"] > 0
    assert results["final_best"] is not None
    assert "best_model" in results["artifacts"]
    assert "leaderboard_csv" in results["artifacts"]

    download = client.get(f"/runs/{run_id}/download/best_model")
    assert download.status_code == 200


def test_second_run_queues_then_auto_starts(tmp_path):
    """Un run soumis pendant qu'un autre tourne/attend n'est jamais rejeté
    (pas de 409) mais mis en file d'attente, puis démarré automatiquement dès
    que l'actif se termine (le worker séparé les traite un par un, FIFO)."""
    client = TestClient(app)

    form_a = _form_data(tmp_path)
    form_a["output_dir"] = str(tmp_path / "runs_a")
    resp_a = client.post("/runs", data=form_a)
    assert resp_a.status_code == 200, resp_a.text
    run_a = resp_a.json()["runs"][0]
    assert run_a["status"] == "queued"

    form_b = _form_data(tmp_path)
    form_b["output_dir"] = str(tmp_path / "runs_b")
    resp_b = client.post("/runs", data=form_b)
    assert resp_b.status_code == 200, resp_b.text
    run_b = resp_b.json()["runs"][0]
    assert run_b["status"] == "queued"

    # run_a doit être réclamé par le worker (unique) avant run_b : file FIFO.
    a_status = _wait_for_status(client, run_a["run_id"], not_in={"queued"}, deadline_s=90)
    assert a_status["status"] == "running", a_status

    state = client.get("/api/run-state").json()
    assert state["active_run"]["id"] == run_a["run_id"]
    assert [q["id"] for q in state["queue"]] == [run_b["run_id"]]

    b_status = _wait_for_status(client, run_b["run_id"], not_in={"queued"}, deadline_s=180)
    assert b_status["status"] in ("running", "done"), b_status


def test_batch_submit_queues_one_job_per_target(tmp_path):
    """Sélectionner plusieurs cibles dans le formulaire enfile un job par
    cible, chacun avec un nom/dossier de sortie distinct -- pas de nouvel
    orchestrateur, juste plusieurs jobs pour la même queue FIFO.

    Soumet aussi un `output_dir` explicite : c'est la seule combinaison qui
    exerce le garde-fou anti-collision de `create_run`
    (`len(targets) > 1 and raw_output_dir`) -- sans elle, un dossier partagé
    entre plusieurs cibles écraserait leurs artefacts les uns les autres, et
    rien ne le détecterait.

    ^GSPC (pas ^AORD) : univers réduit (feature/universe-reduction) --
    ^AORD a été retiré (groupe "Indices" réduit à ^GSPC/^VIX), le
    soumettre renverrait désormais 400 ("choix invalide") au lieu de 200.
    ^GSPC reste dans l'univers réduit et distinct de TARGET_SYMBOL (^VIX)."""
    DataStore(root=str(tmp_path / "store")).save("raw_^GSPC", _synthetic_raw(seed=1))
    client = TestClient(app)

    base_output_dir = str(tmp_path / "shared_runs")
    form = _form_data(tmp_path)
    form["target_symbols"] = [TARGET_SYMBOL, "^GSPC"]
    form["output_dir"] = base_output_dir
    resp = client.post("/runs", data=form)
    assert resp.status_code == 200, resp.text
    runs = resp.json()["runs"]

    assert len(runs) == 2
    assert {r["target"] for r in runs} == {TARGET_SYMBOL, "^GSPC"}
    assert len({r["run_id"] for r in runs}) == 2

    # Chaque job existe bien côté serveur, dans un état actif légitime, avec
    # un nom distinct dérivé de SA cible -- pas seulement "la réponse HTTP
    # avait 2 entrées" (assertion trop faible pour détecter un job perdu ou
    # mal routé).
    output_dirs = set()
    for r in runs:
        status = client.get(f"/runs/{r['run_id']}/status").json()
        assert status["status"] in ("queued", "running"), status
        assert status["name"].startswith(forms.slug_target(r["target"])), status

        # Le dossier de sortie réellement persisté (config du job, pas
        # simplement la réponse HTTP) doit être suffixé par le nom généré de
        # CE job, sous le dossier partagé soumis dans le formulaire -- et
        # donc distinct de celui de l'autre cible.
        config = run_manager.get_run_config(r["run_id"])
        expected_dir = f"{base_output_dir}/{status['name']}"
        assert config.output.dir == expected_dir, config.output.dir
        output_dirs.add(config.output.dir)

    assert len(output_dirs) == 2


def test_relaunch_reuses_config_with_fresh_name(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    run_id = resp.json()["runs"][0]["run_id"]
    _wait_for_status(client, run_id, not_in={"queued", "running"}, deadline_s=240)

    relaunch_resp = client.post(f"/runs/{run_id}/relaunch", follow_redirects=False)
    assert relaunch_resp.status_code == 303, relaunch_resp.text
    new_run_id = relaunch_resp.headers["location"].rsplit("/", 1)[-1]
    assert new_run_id != run_id

    old_config = run_manager.get_run_config(run_id)
    new_config = run_manager.get_run_config(new_run_id)
    assert new_config.objective.target_symbol == old_config.objective.target_symbol
    assert new_config.objective.horizons == old_config.objective.horizons
    assert new_config.name != old_config.name
    assert new_config.name.startswith(forms.slug_target(old_config.objective.target_symbol))


def test_relaunch_falls_back_to_run_table_for_cli_only_run(tmp_path):
    """Un run lancé en CLI (`patrick run`) n'écrit jamais de ligne `job` --
    seule une soumission via le formulaire web le fait (`run_manager.
    start_run`). `run_manager.get_run_config` (qui ne lit que `job`) renvoie
    donc `None` pour un tel run, et la relance doit basculer sur
    `run.config_json` (table remplie par TOUT run, CLI ou web) plutôt que de
    le traiter comme introuvable -- exactement le scénario que le repli de
    `relaunch_run` existe pour couvrir.

    On simule ce cas en insérant directement une ligne `run` (via
    `trackdb.upsert_snapshot`/`create_run`, sans ligne `job` correspondante)
    plutôt qu'en soumettant via `/runs` -- construire la config passe quand
    même par `forms.build_config_dict` (le même code que `create_run` en
    production), juste sans l'aller-retour HTTP. On n'attend pas que le
    pipeline relancé atteigne `done` (inutile pour vérifier le repli et le
    round-trip de config) : seule la réponse immédiate de `/relaunch` est
    vérifiée, comme suggéré en revue -- réel (vraie DB, vraie route, vraie
    queue), pas mocké."""
    client = TestClient(app)

    config_dict, errs = forms.build_config_dict(
        _to_formdata(_form_data(tmp_path)), target_symbol=TARGET_SYMBOL, name="cli_manual_run",
    )
    assert not errs, errs
    config_dict["output"]["dir"] = str(tmp_path / "cli_runs" / "cli_manual_run")
    config = RunConfig.model_validate(config_dict)

    run_id = "cli_only_run"
    conn = trackdb.connect()
    try:
        trackdb.upsert_snapshot(conn, f"snap_{run_id}", "hash", None, None, None)
        trackdb.create_run(
            conn, run_id, TARGET_SYMBOL, config.objective.horizons[0], f"snap_{run_id}",
            config.model_dump_json(), "cfghash", "sha", 42,
        )
        trackdb.finish_run(conn, run_id, status="done", n_trials=3)
    finally:
        conn.close()

    # Confirme qu'on exerce bien le repli (pas de ligne `job` pour ce run_id) --
    # sans quoi le test passerait même si `relaunch_run` ignorait le repli.
    assert run_manager.get_run_config(run_id) is None

    relaunch_resp = client.post(f"/runs/{run_id}/relaunch", follow_redirects=False)
    assert relaunch_resp.status_code == 303, relaunch_resp.text
    new_run_id = relaunch_resp.headers["location"].rsplit("/", 1)[-1]
    assert new_run_id != run_id

    new_config = run_manager.get_run_config(new_run_id)
    assert new_config.objective.target_symbol == TARGET_SYMBOL
    assert new_config.objective.horizons == config.objective.horizons
    assert new_config.name != config.name
    assert new_config.name.startswith(forms.slug_target(TARGET_SYMBOL))


def test_relaunch_404_on_unknown_run():
    client = TestClient(app)
    resp = client.post("/runs/does-not-exist/relaunch")
    assert resp.status_code == 404
