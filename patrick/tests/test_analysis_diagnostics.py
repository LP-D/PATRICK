"""Diagnostics système (`patrick/analysis/diagnostics.py`, `/diagnostics`) : lecture seule, journaux protégés contre les chemins, budget de calcul des tailles."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from patrick.analysis import diagnostics as dg
from patrick.tracking import db as trackdb
from patrick.tracking import jobs
from patrick.webapp.app import app


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(tmp_path / "fcache"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    (tmp_path / "logs").mkdir()
    dg._size_cache.clear()
    return tmp_path


def test_system_has_cpu_memory_disks_and_data_disk_flag(home):
    s = dg.system()
    assert 0 <= s["cpu_percent"] <= 100 and s["cpu_count"] >= 1 and len(s["cpu_per_core"]) == s["cpu_count"]
    assert s["memory"]["total"] > 0 and 0 <= s["memory"]["percent"] <= 100 and s["disks"] and s["home"] == str(home)
    assert any(d["holds_data"] for d in s["disks"])


def test_home_and_data_folders_come_from_paths(home):
    from patrick import paths

    assert dg.home() == paths.home_dir() == home
    by = {i["name"]: i["path"] for i in dg.storage()["items"]}
    assert by["models"] == str(paths.models_dir()) and by["backups"] == str(paths.backups_dir())
    assert by["archive"] == str(paths.archive_dir()) and by["logs"] == str(home / "logs")


def test_both_volumes_hold_data_when_the_data_root_is_on_another_disk(home, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("PATRICK_DB_PATH", "C:\\Users\\x\\.patrick\\patrick.db")
    monkeypatch.setenv("PATRICK_DATA_ROOT", "D:\\PATRICK DATA")
    parts = [SimpleNamespace(opts="rw", fstype="NTFS", mountpoint=m) for m in ("C:\\", "D:\\", "E:\\")]
    monkeypatch.setattr(dg.psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(dg.psutil, "disk_usage", lambda mount: SimpleNamespace(total=10, used=5, free=5, percent=50.0))

    holds = {d["mount"]: d["holds_data"] for d in dg.system()["disks"]}

    assert holds == {"C:\\": True, "D:\\": True, "E:\\": False}


def test_processes_finds_the_current_python_only_when_it_looks_like_patrick():
    out = dg.processes()
    assert isinstance(out, list) and all(p["role"] in ("worker", "server", "other") for p in out)


def test_app_state_reports_db_files_jobs_and_heartbeat(home):
    conn = trackdb.connect(str(home / "patrick.db"))
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'queued')")
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j2', '{}', 'done')")
    jobs.write_heartbeat(conn, os.getpid())
    conn.commit()
    a = dg.app_state(conn)
    assert a["jobs"] == {"queued": 1, "done": 1} and a["db_files"]["db"] > 0 and a["schema_version"] >= 41
    assert a["heartbeat"]["pid"] == os.getpid() and a["heartbeat"]["alive"] is True and a["heartbeat"]["age_s"] < 30


def test_storage_sums_sizes_and_reports_missing_folders(home):
    (home / "cache").mkdir()
    (home / "cache" / "a.bin").write_bytes(b"x" * 1000)
    (home / "cache" / "sub").mkdir()
    (home / "cache" / "sub" / "b.bin").write_bytes(b"y" * 500)
    res = dg.storage()
    by = {i["name"]: i for i in res["items"]}
    assert by["cache"]["bytes"] == 1500 and by["cache"]["files"] == 2 and by["cache"]["partial"] is False
    assert by["feature_cache"]["exists"] is False and by["feature_cache"]["bytes"] == 0 and res["total"] >= 1500


def test_storage_respects_the_time_budget(home, monkeypatch):
    (home / "cache").mkdir()
    for i in range(30):
        d = home / "cache" / f"d{i}"
        d.mkdir()
        (d / "f").write_bytes(b"z")
    monkeypatch.setattr(dg, "SIZE_BUDGET_S", -1.0)                  # budget déjà épuisé
    dg._size_cache.clear()
    assert dg.storage()["partial"] is True


def test_tail_log_returns_last_lines_and_refuses_paths(home):
    (home / "logs" / "worker.log").write_text("\n".join(f"line {i}" for i in range(1000)), encoding="utf-8")
    t = dg.tail_log("worker.log", 5)
    assert t["lines"] == [f"line {i}" for i in range(995, 1000)] and t["truncated"] is True
    (home / "secret.txt").write_text("nope", encoding="utf-8")
    for bad in ("../secret.txt", "..\\secret.txt", "logs/worker.log", "", "nofile.log", "a/b"):
        assert dg.tail_log(bad) is None, bad
    assert [f["name"] for f in dg.list_logs()] == ["worker.log"]
    big = home / "logs" / "big.log"
    big.write_bytes(b"a" * (dg.LOG_TAIL_BYTES * 2) + b"\nlast")
    assert dg.tail_log("big.log", 2)["lines"][-1] == "last"


def test_pages_and_api(home):
    c = TestClient(app)
    assert c.get("/diagnostics").status_code == 200 and 'href="/diagnostics"' in c.get("/").text
    r = c.get("/api/diagnostics/system")
    assert r.status_code == 200 and set(r.json()) == {"system", "processes", "app"} and "NaN" not in r.text
    assert c.get("/api/diagnostics/storage").status_code == 200
    (home / "logs" / "w.log").write_text("hello\nworld", encoding="utf-8")
    assert [x["name"] for x in c.get("/api/diagnostics/logs").json()] == ["w.log"]
    assert c.get("/api/diagnostics/log?name=w.log&lines=1").json()["lines"] == ["world"]
    assert c.get("/api/diagnostics/log?name=..%2Fpatrick.db").status_code == 404
