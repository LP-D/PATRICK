"""`patrick data` : état, création et déplacement de la racine de données (spec 2026-10-21, §6).

Tout se passe sur des arbres et de petites bases sous `tmp_path` : jamais le vrai `~/.patrick`, jamais la vraie base."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from patrick import data_move
from patrick.cli import app as cli_app
from patrick.tracking import db as trackdb


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """Un PC sans racine de données réglée : tout vit dans son dossier maison `tmp_path/home`."""
    for var in ("PATRICK_DATA_ROOT", "PATRICK_STORE_ROOT", "PATRICK_CACHE_ROOT", "PATRICK_FEATURE_CACHE_ROOT"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PATRICK_DB_PATH", str(home / "patrick.db"))
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(home / "settings.json"))
    return SimpleNamespace(home=home, tmp=tmp_path)


def make_db(path: Path, artifacts: list[str | None]) -> str:
    """Petite base : un run, un essai par valeur de `trial.artifact_path`."""
    conn = trackdb.connect(str(path))
    trackdb.upsert_snapshot(conn, "snap", "h", 1, 1, "api")
    trackdb.create_run(conn, "r1", "T", 5, "snap", json.dumps({}), "cfg", "sha", 42)
    for artifact in artifacts:
        conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best, "
                     "artifact_path) VALUES ('r1', 'all', 'lgbm', 'tpe', 10, 'shap', '{}', 0, ?)", (artifact,))
    conn.commit()
    conn.close()
    return str(path)


# --- init / status -----------------------------------------------------------------------------------------------

def test_init_root_creates_the_seven_folders_and_a_readme(tmp_path):
    root = data_move.init_root(str(tmp_path / "PATRICK DATA"))

    assert root == tmp_path / "PATRICK DATA"
    assert data_move.COMPONENTS == ("store", "models", "feature_cache", "cache", "backups", "archive", "reports")
    assert all((root / name).is_dir() for name in data_move.COMPONENTS)
    assert "patrick data status" in (root / "README.txt").read_text(encoding="utf-8")


def test_init_root_refuses_a_missing_parent_and_a_relative_path_and_creates_nothing(tmp_path):
    with pytest.raises(data_move.MoveError):
        data_move.init_root(str(tmp_path / "absent" / "PATRICK DATA"))
    with pytest.raises(data_move.MoveError):
        data_move.init_root("PATRICK DATA")
    assert not (tmp_path / "absent").exists()


def test_status_without_a_data_root(pc):
    out = data_move.status()

    assert out["data_root"] is None and out["available"] is True and out["db"] == str(pc.home / "patrick.db")
    assert [c["name"] for c in out["components"]] == list(data_move.COMPONENTS)
    assert out["unresolved"] == {"artifact_paths": 0, "store_index": 0} and out["progress"] is None


def test_status_with_a_missing_data_root(pc, monkeypatch):
    absent = pc.tmp / "PATRICK DATA"
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(absent))

    out = data_move.status()

    assert out["available"] is False and out["data_root"] == str(absent)
    assert all(c["exists"] is False for c in out["components"])
    assert not absent.exists()


def test_status_counts_only_the_unresolved_absolute_paths(pc):
    model = pc.home / "models" / "1" / "a.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"x")
    make_db(pc.home / "patrick.db", [str(model), str(pc.home / "models" / "2" / "gone.joblib"),
                                     "runs\\rel\\x.joblib", None, ""])
    snap = pc.home / "store" / "snapshot=2026-07-28"
    snap.mkdir(parents=True)
    (snap / "a__1.parquet").write_bytes(b"p")
    (pc.home / "store" / "_index.json").write_text(json.dumps({"k": {"snapshots": [
        {"path": str(snap / "a__1.parquet")}, {"path": str(snap / "b__2.parquet")}]}}), encoding="utf-8")

    assert data_move.status()["unresolved"] == {"artifact_paths": 1, "store_index": 1}


def test_cli_status_and_init(pc):
    root = pc.tmp / "PATRICK DATA"

    assert CliRunner().invoke(cli_app, ["data", "init", str(root)]).exit_code == 0
    assert (root / "models").is_dir()
    out = CliRunner().invoke(cli_app, ["data", "status"])

    assert out.exit_code == 0 and "Racine de données" in out.output and "Dossier maison" in out.output
