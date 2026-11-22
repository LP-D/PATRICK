"""Panneau « Avancement » : le journal brut du pipeline est réécrit en phrases
lisibles (`webapp/progress_steps.py`), servies par `/runs/{id}/status`."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import db, jobs
from patrick.webapp import progress_steps
from patrick.webapp.app import app

RAW_LOG = [
    "[DATA] Ingestion...",
    "  [yfinance] 8/8 tickers kept (coverage>=85%) in 1.6s",
    "  [QUALITY] 2/10 series excluded from the universe (20%):",
    "    - CL=F: rendement_aberrant -- change of -55.9 on 2020-04-20 (robust z=42.4, threshold 40.0)",
    "[INGEST] (4892, 9) (3.8s) | cible=ERF.PA",
    "[FEATURES] base pool: 196 columns (13.1s)",
    "  Fold 1: train -> 2014-12-31 | test 2015-01-01 -> 2017-08-16",
    "  h= 5d fold1: 6 cumulative rows [61s]",
    "  h= 5d fold2: 12 cumulative rows [83s]",
    "",
    "[SCAN] 48 evaluations in 2.8min",
    "[BEST before Optuna] h=5d GLOBAL N=8 SMOTE RandomForest -> F1_dir=0.5128",
    "  h=5d GLOBAL N=8 SMOTE RandomForest: cv_F1_dir=0.5425 params={'n_estimators': 202}",
    "[EXPORT] runs/x/x_phase_timing.txt",
    "[EXPORT] phase timing log -> runs/x/x_h5_phase_timing.txt",
    "   1  RandomForest N=15     2   0.502    0.528     0.020        0.266",
]


def _texts(steps):
    return [s["text"] for s in steps]


def test_recognised_lines_become_sentences_in_french():
    steps = progress_steps.humanize_log(RAW_LOG, "fr")
    texts = _texts(steps)
    assert "Téléchargement des données de marché…" in texts
    assert "Yahoo Finance : 8 séries retenues sur 8 demandées." in texts
    assert "Données prêtes : 4 892 séances, 9 séries (3,8 s). Cible : ERF.PA." in texts
    assert "Découpage de validation, pli 1 : test du 01/01/2015 au 16/08/2017." in texts
    assert "Balayage terminé : 48 évaluations en 2,8 min." in texts
    assert ("Meilleure configuration avant réglage (horizon 5 j) : RandomForest, 8 variables, "
            "F1 directionnel 0,513.") in texts


def test_same_log_in_english():
    texts = _texts(progress_steps.humanize_log(RAW_LOG, "en"))
    assert "Data ready: 4,892 sessions, 9 series (3.8s). Target: ERF.PA." in texts
    assert "Sweep finished: 48 evaluations in 2.8 min." in texts


def test_no_raw_code_survives_in_any_step():
    for lang in ("fr", "en"):
        for text in _texts(progress_steps.humanize_log(RAW_LOG, lang)):
            assert not any(tag in text for tag in ("[", "]", "->", "F1_dir", "cumulative", "params=", ".txt"))


def test_unrecognised_noise_is_dropped():
    steps = progress_steps.humanize_log(["", "   ", "   1  RandomForest N=15     2   0.502", "traceback blah"], "fr")
    assert steps == []


def test_sweep_lines_collapse_into_the_latest_one():
    steps = progress_steps.humanize_log(
        ["  h= 5d fold1: 6 cumulative rows [61s]", "  h= 5d fold2: 12 cumulative rows [83s]",
         "  h= 5d fold3: 18 cumulative rows [99s]"], "fr")
    assert _texts(steps) == [
        "Balayage des configurations — horizon 5 j, pli 3 évalué (18 évaluations, 99 s)."]


def test_levels_flag_warnings_and_quality_exclusions():
    steps = progress_steps.humanize_log(
        ["  [QUALITY] 2/10 series excluded from the universe (20%):",
         "    - CL=F: trou_de_cotation -- gap of ~13 business days",
         "  [WARN] something unexpected happened here"], "fr")
    assert [s["level"] for s in steps] == ["warn", "warn", "warn"]
    assert "CL=F écartée (trou dans les cotations)" in steps[1]["text"]
    assert "journal technique" in steps[2]["text"]


def test_identical_consecutive_warnings_are_shown_once():
    steps = progress_steps.humanize_log(["  [WARN] a", "  [WARN] b", "  [WARN] c"], "fr")
    assert len(steps) == 1


def test_only_the_last_steps_are_kept():
    lines = [f"[SCREENING] h={h}d GLOBAL: 3/9 finalistes pour les folds suivants." for h in range(1, 80)]
    steps = progress_steps.humanize_log(lines, "fr", max_steps=10)
    assert len(steps) == 10
    assert "horizon 79 j" in steps[-1]["text"]


@pytest.mark.parametrize("lang,expected", [("fr", "Balayage terminé"), ("en", "Sweep finished")])
def test_status_route_returns_readable_steps_next_to_the_raw_log(tmp_path, monkeypatch, lang, expected):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO job (job_id, config_json, status, worker_pid, log_tail) VALUES (?, ?, 'running', 1, ?)",
            ("j1", json.dumps({"name": "j1"}), json.dumps(["[SCAN] 48 evaluations in 2.8min"])),
        )
    conn.close()
    assert jobs  # module imported for the schema side effects only

    data = TestClient(app).get(f"/runs/j1/status?lang={lang}").json()
    assert data["log_tail"] == ["[SCAN] 48 evaluations in 2.8min"]
    assert expected in data["steps"][0]["text"]


def test_launch_page_hosts_the_steps_list_and_a_collapsed_raw_log(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    html = TestClient(app).get("/ml").text
    assert 'id="steps-list"' in html
    assert '<details class="log-raw">' in html and 'id="log-tail"' in html
