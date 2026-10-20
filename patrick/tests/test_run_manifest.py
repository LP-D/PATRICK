"""Manifeste de run (audit externe du 2026-10-19) : de quoi refaire ou comparer un run, sans supposer.

Un résultat qui ne se reproduit pas sur une autre machine (voir la saga du golden master dans `KNOWN_ISSUES.md`) a
trois causes possibles : le code, les données, l'environnement. Le manifeste les consigne ensemble, à la création du run :
SHA git, empreinte des données (snapshot), empreinte de la configuration, graine, bibliothèques, empreinte de
l'environnement installé, empreinte du fichier de contraintes, plateforme (système, processeur, BLAS, instructions SIMD).
"""
from __future__ import annotations

import json

from typer.testing import CliRunner

from patrick.cli import app
from patrick.tracking import db as trackdb
from patrick.tracking import manifest


def _run(conn, run_id="r1", config_hash="cfg123", data_hash="data456"):
    trackdb.upsert_snapshot(conn, "snap1", data_hash, 12, 3, "api")
    trackdb.create_run(conn, run_id, target="^T", horizon=5, snapshot_id="snap1", config_json="{}",
                       config_hash=config_hash, git_sha="abc1234", seed=42)


def test_the_platform_fingerprint_describes_the_machine_and_survives_json():
    fp = manifest.platform_fingerprint()
    assert {"python", "implementation", "os", "machine", "cpu_count", "numpy", "blas", "numpy_simd"} <= set(fp)
    assert fp["cpu_count"] >= 1 and fp["python"].count(".") == 2
    assert json.loads(json.dumps(fp)) == fp


def test_the_environment_digest_follows_the_installed_versions(monkeypatch):
    packages = {"numpy": "2.4.0", "pandas": "2.3.1"}
    monkeypatch.setattr(manifest, "installed_packages", lambda: dict(packages))
    first = manifest.environment_digest()
    assert first == manifest.environment_digest()
    packages["pandas"] = "2.3.2"
    assert manifest.environment_digest() != first
    packages["pandas"] = "2.3.1"
    packages["newlib"] = "1.0"
    assert manifest.environment_digest() != first


def test_a_run_records_its_launch_manifest(conn):
    _run(conn)
    stored = json.loads(conn.execute("SELECT manifest_json FROM run WHERE run_id = 'r1'").fetchone()[0])
    assert stored["environment_digest"] == manifest.environment_digest()
    assert stored["platform"]["python"] == manifest.platform_fingerprint()["python"]
    assert "constraints_digest" in stored


def test_the_manifest_gathers_code_data_config_and_environment(conn):
    _run(conn)
    m = manifest.build_manifest(conn, "r1")
    assert (m["git_sha"], m["seed"], m["config_hash"]) == ("abc1234", 42, "cfg123")
    assert m["data"] == {"snapshot_id": "snap1", "data_hash": "data456", "n_tickers": 12, "n_fred_series": 3,
                         "fred_source": "api"}
    assert m["libraries"]["python"] and m["platform"]["os"] and m["environment_digest"]
    assert m["recorded_at_launch"] is True


def test_a_run_from_before_the_manifest_says_what_it_does_not_know(conn):
    _run(conn)
    with conn:
        conn.execute("UPDATE run SET manifest_json = NULL WHERE run_id = 'r1'")
    m = manifest.build_manifest(conn, "r1")
    assert m["recorded_at_launch"] is False and m["platform"] is None and m["environment_digest"] is None
    assert m["git_sha"] == "abc1234"                      # le reste vient des colonnes d'origine


def test_an_unknown_run_is_refused(conn):
    import pytest

    with pytest.raises(KeyError):
        manifest.build_manifest(conn, "nope")


def test_the_cli_prints_the_manifest_as_json(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)
    _run(conn)
    conn.close()
    result = CliRunner().invoke(app, ["manifest", "r1"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["config_hash"] == "cfg123"
    missing = CliRunner().invoke(app, ["manifest", "absent"])
    assert missing.exit_code != 0
