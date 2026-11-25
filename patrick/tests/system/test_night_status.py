"""D21 : état de la dernière nuit lu dans la fin de `runs/nightly.log` et le marqueur du cycle des fonds."""
from __future__ import annotations

import datetime as dt
import json

from patrick.system import night_status as ns

NIGHT = """2026-11-21 23:00:04 ===== passage de nuit (fin : hibernate, inactivite requise : 10 min)
2026-11-21 23:00:04 == mise a jour : python -m patrick.desktop update
2026-11-21 23:00:05    termine (code 0) en 2 s
2026-11-21 23:00:16 == predictions utiles aux fonds et pilote automatique : python daily_predict.py --funds-only
 b r u i t   U T F - 1 6   d e   P y t h o n
\x002026-11-21 23:45:36    termine (code {funds}) en 2 720 s
2026-11-21 23:45:36 == sauvegarde : python backup_db.py
2026-11-21 23:45:45    termine (code {backup}) en 9 s
2026-11-21 23:48:22 == autres predictions : python daily_predict.py --skip-funds
2026-11-22 11:02:00    termine (code 1) en 40 000 s
2026-11-22 11:02:01 == fin : mise en hibernate du PC
"""
NOW = dt.datetime(2026, 11, 22, 12, 0).astimezone()


def _setup(tmp_path, funds=0, backup=0, stamp_day="2026-11-21", older=""):
    (tmp_path / "nightly.log").write_text(older + NIGHT.format(funds=funds, backup=backup), encoding="utf-8")
    if stamp_day:
        (tmp_path / "funds-cycle.json").write_text(json.dumps({"day": stamp_day}), encoding="utf-8")
    return tmp_path


def test_a_complete_night_is_ok_even_if_some_predictions_failed(tmp_path):
    out = ns.night_status(_setup(tmp_path), NOW)
    assert out["status"] == "ok" and out["funds_cycle"] is True and out["failed_steps"] == []
    assert out["started"] == "2026-11-21T23:00" and out["ended"] == "2026-11-22T11:02"


def test_a_failed_side_step_makes_it_partial_and_a_missing_fund_cycle_makes_it_failed(tmp_path):
    assert ns.night_status(_setup(tmp_path, backup=1), NOW)["failed_steps"] == ["sauvegarde"]
    assert ns.night_status(_setup(tmp_path, backup=1), NOW)["status"] == "partial"
    assert ns.night_status(_setup(tmp_path, stamp_day="2026-11-19"), NOW)["status"] == "failed"


def test_without_the_stamp_file_the_fund_step_exit_code_decides(tmp_path):
    assert ns.night_status(_setup(tmp_path, funds=1, stamp_day=None), NOW)["status"] == "ok"
    assert ns.night_status(_setup(tmp_path, funds=-1, stamp_day=None), NOW)["status"] == "failed"


def test_only_the_last_night_counts_and_an_old_one_is_missed(tmp_path):
    older = "2026-11-20 23:00:00 ===== passage de nuit\n2026-11-20 23:00:01 == sauvegarde : python b.py\n2026-11-20 23:00:02    termine (code 1) en 1 s\n"
    assert ns.night_status(_setup(tmp_path, older=older), NOW)["status"] == "ok"
    assert ns.night_status(_setup(tmp_path), NOW + dt.timedelta(days=3))["status"] == "missed"


def test_an_unfinished_night_still_written_is_running_and_no_log_is_unknown(tmp_path):
    log = tmp_path / "nightly.log"
    log.write_text(NIGHT.split("2026-11-21 23:45:36    termine")[0], encoding="utf-8")
    during = dt.datetime(2026, 11, 21, 23, 30).astimezone()
    assert ns.night_status(tmp_path, during)["status"] == "running"           # journal écrit à l'instant, pas de « fin »
    assert ns.night_status(tmp_path / "absent", NOW) == {"status": "unknown"}
