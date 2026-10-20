"""Registre de modèles (`patrick/analysis/model_registry.py`, `/modeles`) : champion implicite puis explicite, versions, fiche, promotion et ses refus,
journal de décision."""
from __future__ import annotations

import json

import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import model_registry as mr
from patrick.analysis import registry
from patrick.tracking import champions
from patrick.tracking import db as trackdb
from patrick.webapp.app import app
from patrick.webapp.forms import default_config_dict


def _add_run(conn, info, run_id, *, started="2027-03-01 10:00:00", artifact=None):
    cfg = default_config_dict()
    cfg["objective"].update({"target_symbol": "TST", "horizons": [2], "regimes": ["GLOBAL"]})
    trackdb.create_run(conn, run_id, "TST", 2, info["snapshot_id"], json.dumps(cfg), "h", "sha", 1)
    conn.execute("UPDATE run SET started_at = ? WHERE run_id = ?", (started, run_id))
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", "LightGBM", "SMOTE", 6, "shap")
    trackdb.mark_best_trial(conn, tid, artifact_path=artifact)
    trackdb.add_fold_metrics(conn, tid, 0, "holdout", {"F1_dir": 0.57})
    trackdb.finish_run(conn, run_id, status="done", n_trials=1)
    return tid


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, run_id="old")
    model = tmp_path / "old.joblib"
    model.write_bytes(b"x")
    conn.execute("UPDATE trial SET artifact_path = ? WHERE run_id = 'old' AND is_best = 1", (str(model),))
    new_model = tmp_path / "new.joblib"
    new_model.write_bytes(b"y")
    _add_run(conn, info, "newer", artifact=str(new_model))
    _add_run(conn, info, "nofile", started="2027-04-01 10:00:00", artifact=str(tmp_path / "gone.joblib"))
    conn.commit()
    yield conn, info
    registry.clear_cache()


def test_overview_uses_latest_run_as_implicit_champion(seeded):
    conn, _ = seeded
    d = mr.overview(conn)
    row = d["items"][0]
    assert row["target"] == "TST" and row["horizon"] == 2 and row["implicit"] is True
    assert row["run_id"] == "nofile" and row["artifact_exists"] is False and row["n_versions"] == 3
    assert d["counts"] == {"pairs": 1, "explicit": 0, "no_file": 1, "stale": d["counts"]["stale"]}


def test_explicit_champion_wins_over_latest(seeded):
    conn, _ = seeded
    tid = conn.execute("SELECT trial_id FROM trial WHERE run_id = 'newer' AND is_best = 1").fetchone()[0]
    champions.promote(conn, "TST", 2, "newer", tid, "won_duel", 0.57)
    row = mr.overview(conn)["items"][0]
    assert row["run_id"] == "newer" and row["implicit"] is False and row["reason"] == "won_duel" and row["artifact_exists"] is True
    assert mr.overview(conn)["counts"]["explicit"] == 1


def test_promote_version_changes_title_and_writes_journal(seeded):
    conn, _ = seeded
    out = mr.promote_version(conn, "TST", 2, "newer")
    assert out["run_id"] == "newer" and out["previous"] == "nofile"
    cur = champions.current(conn, "TST", 2)
    assert cur["run_id"] == "newer" and cur["implicit"] is False and cur["reason"] == "manual"
    entries = trackdb.list_phase9_journal_entries(conn)
    assert entries and entries[0]["action"] == "champion_promote"
    assert "newer" in json.dumps(entries[0]["after"])


@pytest.mark.parametrize("run_id, code", [("nope", "version_unknown"), ("nofile", "model_file_missing")])
def test_promote_refuses_unknown_and_missing_model(seeded, run_id, code):
    conn, _ = seeded
    with pytest.raises(ValueError, match=code):
        mr.promote_version(conn, "TST", 2, run_id)
    assert champions.current(conn, "TST", 2)["implicit"] is True          # rien n'a changé


def test_card_collects_versions_limits_and_archive(seeded):
    conn, _ = seeded
    conn.execute("INSERT INTO model_archive (target, horizon, run_id, role, algo, n_features, wf_metrics_json, duel_json) VALUES "
                 "('TST', 2, 'dead', 'replaced_champion', 'XGBoost', 5, ?, ?)",
                 (json.dumps({"F1_dir": 0.51}), json.dumps({"winner": "challenger", "champion": {"f1_dir": 0.5}, "challenger": {"f1_dir": 0.57}})))
    conn.commit()
    card = mr.model_card(conn, "TST", 2, "card")
    assert card["current"]["run_id"] == "nofile" and len(card["versions"]) == 3
    assert [v["current"] for v in card["versions"]].count(True) == 1
    keys = {x["key"] for x in card["limits"]}
    assert "no_file" in keys and "few_live" in keys                          # fichier absent ; aucun signal live jugé
    assert card["archive"][0]["role"] == "replaced_champion" and card["archive"][0]["duel"]["challenger"]["f1_dir"] == 0.57
    assert card["data"]["snapshot_id"] and card["guardrails"]["trials"] >= 1
    assert mr.model_card(conn, "NOPE", 1, "card") is None
    json.dumps(card, allow_nan=False)


def test_limits_are_sorted_with_warnings_first():
    out = mr.limits({"guide": [{"level": "warn", "key": "acc_vs_majority", "params": {}}], "guardrails": {"reads_recorded": 1, "reads_inferred": 1, "duels": 1,
                     "verdict": "within_noise", "trials": 500, "p_deflated": 0.4}, "live": {"judged": 3}, "drift": "retrain", "age_days": 200, "stability": 0.3,
                     "artifact_exists": True})
    levels = [x["level"] for x in out]
    assert levels == sorted(levels, key=lambda lv: 0 if lv == "warn" else 1)
    assert {x["key"] for x in out} >= {"g_acc_vs_majority", "holdout_reads", "within_noise", "few_live", "drift_retrain", "stale", "unstable_selection"}


def test_pages_and_api(seeded):
    conn, _ = seeded
    conn.close()
    c = TestClient(app)
    assert c.get("/modeles").status_code == 200 and 'href="/modeles"' in c.get("/").text
    page = c.get("/modeles/fiche?target=TST&horizon=2")
    assert page.status_code == 200 and 'data-target="TST"' in page.text
    assert c.get("/api/modeles/overview").json()["counts"]["pairs"] == 1
    card = c.get("/api/modeles/card?target=TST&horizon=2")
    assert card.status_code == 200 and card.json()["current"]["run_id"] == "nofile"
    assert c.get("/api/modeles/card?target=NOPE&horizon=2").status_code == 404
    bad = c.post("/api/modeles/promote", json={"target": "TST", "horizon": 2, "run_id": "nofile"})
    assert bad.status_code == 400 and bad.json()["detail"] == "model_file_missing"
    ok = c.post("/api/modeles/promote", json={"target": "TST", "horizon": 2, "run_id": "newer"})
    assert ok.status_code == 200 and ok.json()["run_id"] == "newer"
    assert c.get("/api/modeles/card?target=TST&horizon=2").json()["current"]["run_id"] == "newer"
