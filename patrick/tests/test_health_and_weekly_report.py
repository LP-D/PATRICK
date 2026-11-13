"""Page « Santé » (`tracking/health.py`) et rapport hebdomadaire (`tracking/weekly_report.py`)."""
from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_fund_selection import World

from patrick import live_refresh
from patrick.tracking import db as trackdb
from patrick.tracking import health, relaunch_stats, weekly_report
from patrick.webapp.app import app

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)          # un lundi
SCHTASKS = (
    '"PC","\\Patrick-DailyPredict","16/11/2026 21:05:00","Prêt","Interactif","15/11/2026 21:05:01","0","Léon"\r\n'
    '"PC","\\PATRICK-SauvegardeBase","16/11/2026 22:30:00","Prêt","Interactif","15/11/2026 22:30:01","267014","Léon"\r\n'
    '"PC","\\Microsoft\\Windows\\Autre","N/A","Prêt","Interactif","N/A","0","SYSTEM"\r\n')


def _fake_run(stdout):
    return lambda *args, **kwargs: SimpleNamespace(stdout=stdout)


def _by_key(items):
    return {c["key"]: c for c in items}


def test_scheduled_tasks_keep_only_the_platforms_and_flag_a_failed_one():
    tasks = health.scheduled_tasks(_fake_run(SCHTASKS.encode("cp850")))
    assert [(t["name"], t["last_result"]) for t in tasks] == [("Patrick-DailyPredict", "0"), ("PATRICK-SauvegardeBase", "267014")]
    assert health._tasks(_fake_run(SCHTASKS))["status"] == "warning"                       # la sauvegarde a été interrompue
    assert health._tasks(_fake_run(SCHTASKS.replace("267014", "0")))["status"] == "ok"

    def missing(*args, **kwargs):
        raise OSError("schtasks absent")
    assert health.scheduled_tasks(missing) == [] and health._tasks(missing)["status"] == "unknown"


def test_an_empty_platform_reports_facts_without_crashing(conn, tmp_path):
    items = _by_key(health.checks(conn, NOW, _fake_run(""), db_file=str(tmp_path / "patrick.db")))

    assert set(items) == {"tasks", "backup", "signals", "live_failures", "job_errors", "worker", "pooled", "drift", "disk"}
    assert items["signals"]["status"] == "unknown" and items["live_failures"]["status"] == "ok" and items["job_errors"]["status"] == "ok"
    assert items["worker"]["status"] == "ok" and items["pooled"]["status"] == "warning" and items["drift"]["status"] == "unknown"
    assert items["disk"]["value"] > 0


def test_checks_see_stale_signals_lost_series_and_a_dead_worker(conn, monkeypatch, tmp_path):
    world = World(conn, monkeypatch)
    world.cell("AAPL", 1, live=("2026-11-13", 3, 0.6))                     # vendredi : normal un lundi matin
    relaunch_stats.record_live_failure(conn, "r1", "Training pool columns missing from the fresh data: ['OJ=F_vol_10d'] -- x")
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'queued')")
    conn.commit()

    items = _by_key(health.checks(conn, NOW, _fake_run(""), db_file=str(tmp_path / "patrick.db")))

    assert items["signals"]["status"] == "ok" and items["signals"]["value"] == "2026-11-13"
    assert items["live_failures"]["status"] == "error" and items["live_failures"]["detail"] == [{"series": "OJ=F", "n_models": 1}]
    assert items["worker"]["status"] == "error" and items["worker"]["detail"] == 1          # un job en file, aucun worker vivant
    assert health.overall(list(items.values())) == "error"
    late = _by_key(health.checks(conn, datetime(2026, 11, 25, tzinfo=UTC), _fake_run(""), db_file=str(tmp_path / "patrick.db")))
    assert late["signals"]["status"] == "error"                                              # douze jours sans signal


def test_a_failing_check_never_hides_the_others(conn, monkeypatch, tmp_path):
    monkeypatch.setattr(health, "_backup", lambda now: 1 / 0)

    items = _by_key(health.checks(conn, NOW, _fake_run(""), db_file=str(tmp_path / "patrick.db")))

    assert items["backup"]["status"] == "unknown" and "ZeroDivisionError" in items["backup"]["detail"] and len(items) == 9


# --------------------------------------------------------------------------- rapport hebdomadaire

def test_the_weekly_report_covers_the_past_week_and_is_written_once(conn, monkeypatch, tmp_path):
    world = World(conn, monkeypatch)
    tid = world.cell("AAPL", 1, live=None)
    days = [dt.date(2026, 11, 9) + dt.timedelta(days=i) for i in range(5)]             # la semaine écoulée
    conn.executemany("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba, p_up) VALUES (?, ?, 'live', ?, 3, 0.6, 0.6)",
                     [(tid, d.isoformat(), 1.0 if i < 4 else 0.0) for i, d in enumerate(days)])
    relaunch_stats.record_duel(conn, job_id="j", run_id="r", target="AAPL", horizon=1, decision={"decision": "challenger_wins"})
    conn.execute("UPDATE duel_outcome SET decided_at = '2026-11-10 10:00:00'")
    conn.commit()
    today = dt.date(2026, 11, 16)

    report = weekly_report.build(conn, today)
    assert (report["start"], report["end"]) == ("2026-11-09", "2026-11-15") and weekly_report.week_start(dt.date(2026, 11, 18)) == dt.date(2026, 11, 9)
    assert report["live_week"]["n"] == 5 and report["live_week"]["rate"] == 0.8 and report["duels"] == {"challenger_wins": 1}

    path = weekly_report.write_if_due(conn, today, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == "hebdo-2026-11-09.md" and "semaine du 2026-11-09 au 2026-11-15" in text
    assert "80,0 % de bonnes directions sur 5 prédictions jugées" in text and "1 gagnés par le challenger" in text
    assert weekly_report.write_if_due(conn, today, tmp_path) is None                         # déjà écrit : jamais réécrit
    assert weekly_report.list_reports(tmp_path) == ["hebdo-2026-11-09.md"]
    assert weekly_report.read("hebdo-2026-11-09.md", tmp_path) == text
    assert weekly_report.read("../patrick.db", tmp_path) is None                             # jamais un chemin fourni par l'appelant


def test_reports_of_an_explicit_database_stay_next_to_it(tmp_path, monkeypatch):
    db_path = str(tmp_path / "base" / "patrick.db")
    (tmp_path / "base").mkdir()
    trackdb.connect(db_path).close()

    written = live_refresh.write_weekly_report(db_path)

    assert written and written.startswith(str(tmp_path / "base" / "reports"))
    assert live_refresh.write_weekly_report(db_path) is None
    monkeypatch.setattr(weekly_report, "write_if_due", lambda *a, **k: 1 / 0)
    assert live_refresh.write_weekly_report(db_path) is None                                 # une panne n'arrête jamais l'actualisation


def test_the_health_page_renders_with_its_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setattr(health.subprocess, "run", _fake_run(SCHTASKS))
    client = TestClient(app)

    page = client.get("/sante")
    assert page.status_code == 200 and "Santé de la plateforme" in page.text and "Patrick-DailyPredict" in page.text
    assert "Aucun rapport pour" in page.text and 'href="/sante"' in page.text

    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    weekly_report.write_if_due(conn, dt.date(2026, 11, 16))
    conn.close()
    assert "hebdo-2026-11-09.md" in client.get("/sante").text
    shown = client.get("/sante/rapport/hebdo-2026-11-09.md")
    assert shown.status_code == 200 and "Rapport hebdomadaire" in shown.text
    assert client.get("/sante/rapport/inconnu.md").status_code == 404
    assert client.get("/sante", headers={"Accept-Language": "en"}).status_code == 200


@pytest.mark.parametrize("hours, expected", [(None, "error"), (10, "ok"), (40, "warning"), (200, "error")])
def test_grading_by_age(hours, expected):
    assert health._graded(hours, health.BACKUP_WARN_HOURS, health.BACKUP_ERROR_HOURS) == expected
