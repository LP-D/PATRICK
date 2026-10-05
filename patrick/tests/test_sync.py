"""`patrick sync` -- partage de la base, des modèles et du magasin de données
entre deux PC, sans jamais exporter les tables du patrimoine/fonds personnels.

Chaque test crée ses propres bases SQLite légères sous `tmp_path` (jamais la
vraie base `~/.patrick/patrick.db`) et passe par la destination « dossier »,
qui n'a pas besoin de réseau; la destination GitHub est testée en
interceptant `subprocess.run`."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from patrick import sync
from patrick.tracking import db


def _make_db(path: Path, *, runs=("run_1", "run_2"), personal=True) -> None:
    conn = db.connect(str(path))
    db.upsert_snapshot(conn, "snap_1", "hash_1", 10, 5, "api")
    for run_id in runs:
        db.create_run(conn, run_id, "^VIX", 5, "snap_1", json.dumps({"name": run_id}), "cfg", "sha", 42)
    if personal:
        conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('a1', 'PEA perso', 'PEA', 'real')")
        conn.execute("INSERT INTO wealth_movement (account_id, ts, kind, symbol, quantity, price, amount, note) "
                     "VALUES ('a1', '2026-01-02', 'buy', 'ALDAT.PA', 3, 10, -30, 'note Dufour')")
        conn.execute("INSERT INTO fund_strategy (strategy_id, name, wrapper, initial_capital, opened_on) "
                     "VALUES ('s1', 'Ma strategie', 'PEA', 1000, '2026-01-01')")
    conn.commit()
    conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        conn.close()


def _push(dest: Path, src_db: Path, tmp_path: Path, **kw) -> dict:
    kw.setdefault("store_root", str(tmp_path / "no_store"))
    kw.setdefault("models_roots", [])
    return sync.push(str(dest), db_path=str(src_db), **kw)


def _pull(source: Path, dst_db: Path, tmp_path: Path, **kw) -> dict:
    kw.setdefault("store_root", str(tmp_path / "pc2_store"))
    kw.setdefault("models_dir", str(tmp_path / "pc2_models"))
    kw.setdefault("backup_dir", str(tmp_path / "pc2_backups"))
    return sync.pull(str(source), db_path=str(dst_db), **kw)


def test_personal_tables_are_wealth_fund_and_simulation(tmp_path):
    _make_db(tmp_path / "a.db")
    conn = sqlite3.connect(str(tmp_path / "a.db"))
    names = set(sync.personal_tables(conn))
    conn.close()
    assert {"wealth_account", "wealth_movement", "fund_strategy", "fund_order", "fund_price",
            "simulation"} <= names
    assert "run" not in names and "prediction" not in names


def test_push_to_folder_publishes_db_without_any_personal_row(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "share"

    manifest = _push(dest, src, tmp_path)

    gz = dest / "patrick.db.gz"
    assert gz.exists() and (dest / "manifest.json").exists()
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(gz.read_bytes()))
    assert _count(restored, "run") == 2
    for table in ("wealth_account", "wealth_movement", "fund_strategy"):
        assert _count(restored, table) == 0
    # Les pages libérées par le DELETE ne doivent pas garder la donnée en clair.
    raw = restored.read_bytes()
    assert b"ALDAT.PA" not in raw and b"Dufour" not in raw and b"Ma strategie" not in raw
    assert "wealth_movement" in manifest["excluded_tables"]
    # La source n'est pas modifiée.
    assert _count(src, "wealth_movement") == 1


def test_manifest_checksums_match_the_published_files(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)

    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    for name, meta in manifest["files"].items():
        data = (dest / name).read_bytes()
        assert meta["sha256"] == hashlib.sha256(data).hexdigest()
        assert meta["size"] == len(data)
    assert "USERNAME" not in json.dumps(manifest)


def test_include_personal_is_refused_for_github(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    with pytest.raises(sync.SyncError, match="personal|perso"):
        sync.push("github", db_path=str(src), store_root=str(tmp_path / "s"), models_roots=[],
                  include_personal=True)


def test_include_personal_to_a_folder_keeps_personal_rows(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "private_drive"
    _push(dest, src, tmp_path, include_personal=True)

    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress((dest / "patrick.db.gz").read_bytes()))
    assert _count(restored, "wealth_movement") == 1


def test_pull_on_a_fresh_pc_restores_research_data(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)

    pc2 = tmp_path / "pc2.db"
    result = _pull(dest, pc2, tmp_path)

    assert pc2.exists()
    assert _count(pc2, "run") == 2
    assert _count(pc2, "wealth_movement") == 0
    assert result["runs"] == 2


def test_pull_keeps_the_local_personal_rows(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)

    pc2 = tmp_path / "pc2.db"
    _make_db(pc2, runs=("run_1",), personal=False)
    conn = sqlite3.connect(str(pc2))
    conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('b1', 'CTO pc2', 'CTO', 'real')")
    conn.execute("INSERT INTO wealth_movement (account_id, ts, kind, amount) VALUES ('b1', '2026-02-01', 'deposit', 500)")
    conn.commit()
    conn.close()

    _pull(dest, pc2, tmp_path)

    assert _count(pc2, "run") == 2                      # la recherche vient du partage
    assert _count(pc2, "wealth_account") == 1           # le patrimoine reste celui du PC local
    conn = sqlite3.connect(str(pc2))
    assert conn.execute("SELECT name FROM wealth_account").fetchone()[0] == "CTO pc2"
    conn.close()
    assert list((tmp_path / "pc2_backups").glob("*.db"))  # sauvegarde faite avant remplacement


def test_pull_refuses_to_drop_local_runs_missing_from_the_share(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, runs=("run_1",))
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)

    pc2 = tmp_path / "pc2.db"
    _make_db(pc2, runs=("run_1", "run_local_only"), personal=False)

    with pytest.raises(sync.SyncError, match="run_local_only"):
        _pull(dest, pc2, tmp_path)
    assert _count(pc2, "run") == 2                      # rien n'a été touché

    _pull(dest, pc2, tmp_path, force=True)
    assert _count(pc2, "run") == 1


def test_pull_rejects_a_corrupted_file(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)
    (dest / "patrick.db.gz").write_bytes(b"corrompu")

    with pytest.raises(sync.SyncError, match="sha256"):
        _pull(dest, tmp_path / "pc2.db", tmp_path)
    assert not (tmp_path / "pc2.db").exists()


def test_pull_rejects_a_snapshot_newer_than_the_code(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = 9999
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(sync.SyncError, match="9999"):
        _pull(dest, tmp_path / "pc2.db", tmp_path)


def test_models_roundtrip_rewrites_artifact_paths(tmp_path):
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    models = tmp_path / "pc1_runs"
    models.mkdir()
    (models / "VIX_best_model_h1.joblib").write_bytes(b"modele-1")
    (models / "VIX_best_model_h1_meta.json").write_text('{"k": 1}', encoding="utf-8")
    conn = sqlite3.connect(str(src))
    conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best, "
                 "artifact_path) VALUES ('run_1', 'all', 'lgbm', 'tpe', 10, 'shap', '{}', 1, ?)",
                 (str(models / "VIX_best_model_h1.joblib"),))
    conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best, "
                 "artifact_path) VALUES ('run_2', 'all', 'lgbm', 'tpe', 10, 'shap', '{}', 1, 'runs/absent/x.joblib')")
    conn.commit()
    conn.close()
    dest = tmp_path / "share"

    manifest = _push(dest, src, tmp_path, models_roots=[str(tmp_path)])

    assert manifest["models"]["included"] == 1
    assert manifest["models"]["missing"] == ["runs/absent/x.joblib"]
    pc2 = tmp_path / "pc2.db"
    _pull(dest, pc2, tmp_path)
    conn = sqlite3.connect(str(pc2))
    paths = {r[0] for r in conn.execute("SELECT artifact_path FROM trial WHERE run_id = 'run_1'")}
    conn.close()
    (new_path,) = paths
    assert Path(new_path).read_bytes() == b"modele-1"
    assert Path(new_path).is_relative_to(tmp_path / "pc2_models")
    assert Path(new_path).with_name("VIX_best_model_h1_meta.json").exists()


def test_store_roundtrip_makes_index_paths_local_and_username_free(tmp_path):
    store1 = tmp_path / "pc1_store"
    (store1 / "snapshot=2026-08-19").mkdir(parents=True)
    (store1 / "snapshot=2026-08-19" / "raw_VIX__abc.parquet").write_bytes(b"parquet-1")
    entry = {"snapshot_id": "2026-08-19__raw_VIX__abc", "content_hash": "abc", "rows": 5, "cols": 6,
             "path": str(store1 / "snapshot=2026-08-19" / "raw_VIX__abc.parquet")}
    (store1 / "_index.json").write_text(json.dumps({"raw_^VIX": {"snapshots": [entry]}}), encoding="utf-8")
    (store1 / "_series_observations.json").write_text(
        json.dumps({"BTC-USD": {"date_max": "2026-10-01", "source": "yahoo"}}), encoding="utf-8")
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    dest = tmp_path / "share"
    _push(dest, src, tmp_path, store_root=str(store1))

    store2 = tmp_path / "pc2_store"
    store2.mkdir()
    local_entry = {"snapshot_id": "2026-09-30__raw_GSPC__zzz", "content_hash": "zzz", "rows": 1, "cols": 6,
                   "path": str(store2 / "snapshot=2026-09-30" / "raw_GSPC__zzz.parquet")}
    (store2 / "_index.json").write_text(json.dumps({"raw_^GSPC": {"snapshots": [local_entry]}}), encoding="utf-8")
    _pull(dest, tmp_path / "pc2.db", tmp_path, store_root=str(store2))

    index = json.loads((store2 / "_index.json").read_text(encoding="utf-8"))
    assert set(index) == {"raw_^VIX", "raw_^GSPC"}                      # fusion, rien de perdu
    (merged,) = index["raw_^VIX"]["snapshots"]
    assert Path(merged["path"]) == store2 / "snapshot=2026-08-19" / "raw_VIX__abc.parquet"
    assert Path(merged["path"]).read_bytes() == b"parquet-1"
    series = json.loads((store2 / "_series_observations.json").read_text(encoding="utf-8"))
    assert series["BTC-USD"]["date_max"] == "2026-10-01"


def test_github_transport_uses_a_rolling_release(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        done = _Done()
        if cmd[:3] == ["gh", "release", "view"]:
            done.returncode = 1                       # la release n'existe pas encore
        return done

    monkeypatch.setattr(sync.subprocess, "run", fake_run)
    src = tmp_path / "pc1.db"
    _make_db(src)

    sync.push("github", db_path=str(src), store_root=str(tmp_path / "s"), models_roots=[])

    assert any(c[:3] == ["gh", "release", "create"] and "data-latest" in c for c in calls)
    upload = next(c for c in calls if c[:3] == ["gh", "release", "upload"])
    assert "--clobber" in upload
    assert any(Path(a).name == "patrick.db.gz" for a in upload)
    assert not any("wealth" in " ".join(c) for c in calls)


def test_export_neutralises_queued_jobs_and_worker_heartbeat(tmp_path):
    """Un job en attente exporté serait exécuté par le worker de l'autre PC, et un
    battement de worker récent ferait croire qu'un worker y tourne."""
    src = tmp_path / "pc1.db"
    _make_db(src, personal=False)
    conn = sqlite3.connect(str(src))
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('q1', '{}', 'queued')")
    conn.execute("INSERT INTO job (job_id, config_json, status, worker_pid) VALUES ('r1', '{}', 'running', 4242)")
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('d1', '{}', 'done')")
    conn.execute("INSERT OR REPLACE INTO worker_heartbeat (id, pid, updated_at) VALUES (1, 4242, datetime('now'))")
    conn.commit()
    conn.close()
    dest = tmp_path / "share"
    _push(dest, src, tmp_path)

    pc2 = tmp_path / "pc2.db"
    _pull(dest, pc2, tmp_path)

    conn = sqlite3.connect(str(pc2))
    statuses = dict(conn.execute("SELECT job_id, status FROM job"))
    heartbeat = conn.execute("SELECT COUNT(*) FROM worker_heartbeat").fetchone()[0]
    pids = conn.execute("SELECT COUNT(*) FROM job WHERE worker_pid IS NOT NULL").fetchone()[0]
    conn.close()
    assert statuses == {"q1": "error", "r1": "error", "d1": "done"}
    assert heartbeat == 0 and pids == 0
    # La source n'est pas modifiée.
    conn = sqlite3.connect(str(src))
    assert conn.execute("SELECT status FROM job WHERE job_id = 'q1'").fetchone()[0] == "queued"
    conn.close()
